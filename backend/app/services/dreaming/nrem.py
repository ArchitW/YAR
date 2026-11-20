"""NREM Synaptic Pruning & Deduplication Engine (Sleep Phase Consolidation)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ...models.memory import MemoryNode
from ..memory import MemoryService

logger = logging.getLogger(__name__)


def calculate_jaccard_similarity(text_a: str, text_b: str) -> float:
    """Calculate token Jaccard similarity between two texts."""
    toks_a = set(re.findall(r"\w+", text_a.lower()))
    toks_b = set(re.findall(r"\w+", text_b.lower()))
    if not toks_a or not toks_b:
        return 0.0
    return len(toks_a & toks_b) / len(toks_a | toks_b)


def extract_preference_topic(content: str) -> tuple[str, str] | None:
    """Extract (subject_key, value) from preference or convention statement."""
    text = content.strip().lower()
    match_pref = re.search(r"\b(?:i\s+prefer|preference\s+is)\s+([^.!?\n]+)", text)
    if match_pref:
        val = match_pref.group(1).strip()
        for cat in ("database", "db", "auth", "orm", "framework", "style", "language"):
            if cat in val:
                return (cat, val)
        return ("preference", val)

    match_never = re.search(r"\bnever\s+use\s+([a-zA-Z0-9_-]+)", text)
    if match_never:
        return (f"use_{match_never.group(1)}", "forbidden")

    match_always = re.search(r"\balways\s+use\s+([a-zA-Z0-9_-]+)", text)
    if match_always:
        return (f"use_{match_always.group(1)}", "required")
    return None


def is_contradiction(node_a: MemoryNode, node_b: MemoryNode) -> bool:
    """Check if newer node_b contradicts older node_a."""
    props_a, props_b = node_a.properties or {}, node_b.properties or {}
    key_a, key_b = props_a.get("attribute_key"), props_b.get("attribute_key")
    if key_a and key_b and key_a == key_b:
        return props_a.get("attribute_value") != props_b.get("attribute_value")

    topic_a = extract_preference_topic(node_a.content)
    topic_b = extract_preference_topic(node_b.content)
    if topic_a and topic_b and topic_a[0] == topic_b[0]:
        return topic_a[1] != topic_b[1]

    switch = re.search(r"\bswitched\s+(?:from\s+(\w+)\s+)?to\s+(\w+)", node_b.content.lower())
    if switch and switch.group(1) and switch.group(1) in node_a.content.lower():
        return True
    return False


def extract_dossier_elements(content: str) -> list[tuple[str, str, str, dict[str, Any]]]:
    """Extract candidate (node_type, name, content, properties) from text."""
    results: list[tuple[str, str, str, dict[str, Any]]] = []
    text = content.strip()

    pref_m = re.search(r"\b(?:i\s+prefer|my\s+preference\s+is)\s+([^.!?\n]+)", text, re.IGNORECASE)
    if pref_m:
        val = pref_m.group(1).strip()
        top = extract_preference_topic(text)
        props = {"attribute_key": top[0], "attribute_value": val} if top else {}
        results.append(("user_preference", f"Preference: {val[:40]}", text, props))

    rule_m = re.search(r"\b(?:our\s+rule\s+is|we\s+decided\s+to|always)\s+([^.!?\n]+)", text, re.IGNORECASE)
    if rule_m:
        val = rule_m.group(1).strip()
        results.append(("concept", f"Invariant: {val[:40]}", text, {"rule": val}))
    return results


class NREMConsolidator:
    """Consolidation engine for noise pruning, deduplication, and contradiction resolution."""

    @classmethod
    def prune_noise(
        cls,
        db: Session,
        workspace_id: int,
        threshold_hours: float = 48.0,
        importance_cutoff: float = 0.3,
    ) -> int:
        """Archive low-importance episodic memories older than threshold_hours."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=threshold_hours)
        stmt = select(MemoryNode).where(
            and_(
                MemoryNode.workspace_id == workspace_id,
                MemoryNode.invalidated_at.is_(None),
                MemoryNode.node_type == "episodic_memory",
                MemoryNode.importance_score < importance_cutoff,
            )
        )
        pruned_count = 0
        for node in db.scalars(stmt).all():
            created_at = node.created_at
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at and created_at <= cutoff:
                node.invalidated_at = now
                props = dict(node.properties or {})
                props.update({"pruned": True, "prune_reason": "nrem_noise_filter"})
                node.properties = props
                flag_modified(node, "properties")
                pruned_count += 1
        db.flush()
        return pruned_count

    @classmethod
    def deduplicate(
        cls,
        db: Session,
        workspace_id: int,
        similarity_threshold: float = 0.85,
    ) -> int:
        """Cluster and merge near-duplicate active memories."""
        stmt = select(MemoryNode).where(
            and_(MemoryNode.workspace_id == workspace_id, MemoryNode.invalidated_at.is_(None))
        ).order_by(MemoryNode.created_at.asc())
        nodes = list(db.scalars(stmt).all())
        deduped_count = 0

        for i, node_a in enumerate(nodes):
            if node_a.invalidated_at is not None:
                continue
            for node_b in nodes[i + 1:]:
                if node_b.invalidated_at is not None or node_a.node_type != node_b.node_type:
                    continue
                if calculate_jaccard_similarity(node_a.content, node_b.content) >= similarity_threshold:
                    canon, dup = cls._select_canonical(node_a, node_b)
                    canon.access_count += dup.access_count
                    MemoryService.invalidate_node(
                        db, dup.id, superseded_by_id=canon.id, reason="semantic_deduplication"
                    )
                    deduped_count += 1
                    if dup == node_a:
                        break
        db.flush()
        return deduped_count

    @staticmethod
    def _select_canonical(node_a: MemoryNode, node_b: MemoryNode) -> tuple[MemoryNode, MemoryNode]:
        """Determine canonical memory node vs duplicate to supersede."""
        return (node_b, node_a) if node_b.importance_score > node_a.importance_score else (node_a, node_b)

    @classmethod
    def resolve_contradictions(cls, db: Session, workspace_id: int) -> int:
        """Detect conflicting statements; newer statement supersedes older record."""
        stmt = select(MemoryNode).where(
            and_(MemoryNode.workspace_id == workspace_id, MemoryNode.invalidated_at.is_(None))
        ).order_by(MemoryNode.created_at.asc())
        nodes = list(db.scalars(stmt).all())
        resolved_count = 0

        for i, older in enumerate(nodes):
            if older.invalidated_at is not None:
                continue
            for newer in nodes[i + 1:]:
                if newer.invalidated_at is not None:
                    continue
                if is_contradiction(older, newer):
                    MemoryService.invalidate_node(
                        db, older.id, superseded_by_id=newer.id, reason="contradiction_resolved"
                    )
                    resolved_count += 1
                    break
        db.flush()
        return resolved_count

    @classmethod
    def sync_to_dossier(cls, db: Session, workspace_id: int) -> list[MemoryNode]:
        """Extract high-salience facts from unsynced episodic records into the active dossier."""
        stmt = select(MemoryNode).where(
            and_(
                MemoryNode.workspace_id == workspace_id,
                MemoryNode.invalidated_at.is_(None),
                MemoryNode.node_type == "episodic_memory",
                MemoryNode.importance_score >= 0.7,
            )
        )
        created_nodes: list[MemoryNode] = []
        for node in db.scalars(stmt).all():
            props = dict(node.properties or {})
            if props.get("dossier_synced"):
                continue
            for node_type, name, content, elem_props in extract_dossier_elements(node.content):
                dossier_node = MemoryService.add_node(
                    db=db,
                    workspace_id=workspace_id,
                    node_type=node_type,
                    name=name,
                    content=content,
                    importance_score=node.importance_score,
                    properties=elem_props,
                    user_id=node.user_id,
                )
                MemoryService.add_edge(
                    db=db,
                    workspace_id=workspace_id,
                    source_id=node.id,
                    target_id=dossier_node.id,
                    relation_type="extracted_from",
                    weight=1.0,
                )
                created_nodes.append(dossier_node)
            props["dossier_synced"] = True
            node.properties = props
            flag_modified(node, "properties")

        if created_nodes:
            cls.resolve_contradictions(db, workspace_id)
        db.flush()
        return created_nodes

    @classmethod
    def consolidate(
        cls,
        db: Session,
        workspace_id: int,
        threshold_hours: float = 48.0,
        similarity_threshold: float = 0.85,
    ) -> dict[str, Any]:
        """Execute full NREM sleep consolidation cycle."""
        logger.info("Starting NREM consolidation cycle for workspace %d", workspace_id)
        pruned = cls.prune_noise(db, workspace_id, threshold_hours=threshold_hours)
        deduped = cls.deduplicate(db, workspace_id, similarity_threshold=similarity_threshold)
        contradictions = cls.resolve_contradictions(db, workspace_id)
        synced = cls.sync_to_dossier(db, workspace_id)
        db.flush()

        stats = {
            "workspace_id": workspace_id,
            "pruned_noise_count": pruned,
            "deduplicated_count": deduped,
            "contradictions_resolved_count": contradictions,
            "synced_dossier_count": len(synced),
        }
        logger.info("Completed NREM consolidation for workspace %d: %s", workspace_id, stats)
        return stats
