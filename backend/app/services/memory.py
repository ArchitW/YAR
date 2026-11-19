"""Cognitive Memory Service: In-Session Awake Stream, Living Dossier, and Graph Operations."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models.memory import MemoryEdge, MemoryNode

logger = logging.getLogger(__name__)

# Heuristic patterns for salience classification
HIGH_IMPORTANCE_PATTERNS = [
    r"\bi\s+prefer\b",
    r"\bmy\s+preference\b",
    r"\balways\s+(use|do|make)\b",
    r"\bnever\s+(use|do|make)\b",
    r"\bremember\s+(that|to)?\b",
    r"\bwe\s+decided\b",
    r"\bour\s+rule\s+is\b",
    r"\bi\s+want\s+you\s+to\b",
    r"\barchitectural\s+decision\b",
    r"\bdo\s+not\s+(ever)?\b",
]

TRANSIENT_NOISE_PATTERNS = [
    r"^(ok|okay|k|thanks|thank\s+you|cool|nice|got\s+it|looks\s+good|proceed|yes|no|yep|nope)[.!]?$",
]


def score_importance(text: str) -> float:
    """Heuristic importance scoring for in-session messages."""
    text_lower = text.strip().lower()

    for pattern in TRANSIENT_NOISE_PATTERNS:
        if re.search(pattern, text_lower):
            return 0.2

    for pattern in HIGH_IMPORTANCE_PATTERNS:
        if re.search(pattern, text_lower):
            return 0.85

    # Moderate length statements with substantive verbs
    if len(text.split()) > 25:
        return 0.65

    return 0.5


def calculate_recency_score(last_accessed_at: datetime | None, half_life_hours: float = 72.0) -> float:
    """Exponential half-life recency decay: S_recency = 0.5^(dt / half_life)."""
    if last_accessed_at is None:
        return 1.0

    now = datetime.now(timezone.utc)
    # Ensure timezone awareness compatibility
    if last_accessed_at.tzinfo is None:
        last_accessed_at = last_accessed_at.replace(tzinfo=timezone.utc)

    elapsed_seconds = max(0.0, (now - last_accessed_at).total_seconds())
    elapsed_hours = elapsed_seconds / 3600.0
    return float(0.5 ** (elapsed_hours / half_life_hours))


def calculate_lexical_relevance(query: str, text: str) -> float:
    """Calculate query token recall and lexical overlap relevance."""
    q_tokens = set(re.findall(r"\w+", query.lower()))
    t_tokens = set(re.findall(r"\w+", text.lower()))

    if not q_tokens or not t_tokens:
        return 0.0

    intersection = q_tokens.intersection(t_tokens)
    if not intersection:
        return 0.0

    # Query token recall: what fraction of the search terms are present?
    query_recall = len(intersection) / len(q_tokens)
    # Jaccard overlap
    jaccard = len(intersection) / len(q_tokens.union(t_tokens))

    query_lower = query.lower().strip()
    text_lower = text.lower().strip()
    phrase_bonus = 0.2 if query_lower in text_lower else 0.0

    relevance = (0.6 * query_recall) + (0.4 * jaccard) + phrase_bonus
    return min(1.0, relevance)


class MemoryService:
    """Orchestrates memory node/edge persistence, living dossier management, and tri-factor retrieval."""

    @staticmethod
    def add_node(
        db: Session,
        workspace_id: int,
        node_type: str,
        name: str,
        content: str,
        summary: str | None = None,
        importance_score: float = 0.5,
        confidence: float = 1.0,
        properties: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> MemoryNode:
        """Create and persist a new universal MemoryNode."""
        importance = max(0.1, min(1.0, importance_score))
        confidence_val = max(0.0, min(1.0, confidence))

        if summary is None:
            summary = content[:140] + ("..." if len(content) > 140 else "")

        node = MemoryNode(
            workspace_id=workspace_id,
            user_id=user_id,
            node_type=node_type,
            name=name,
            content=content,
            summary=summary,
            importance_score=importance,
            confidence=confidence_val,
            properties=properties or {},
        )
        db.add(node)
        db.flush()
        return node

    @staticmethod
    def add_edge(
        db: Session,
        workspace_id: int,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 1.0,
        properties: dict[str, Any] | None = None,
    ) -> MemoryEdge:
        """Create and persist a directed relationship between two MemoryNodes."""
        edge = MemoryEdge(
            workspace_id=workspace_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            weight=max(0.0, min(1.0, weight)),
            properties=properties or {},
        )
        db.add(edge)
        db.flush()
        return edge

    @classmethod
    def record_interaction(
        cls,
        db: Session,
        workspace_id: int,
        role: str,
        content: str,
        user_id: int | None = None,
    ) -> MemoryNode:
        """Log an episodic interaction event and auto-extract high-salience preferences."""
        importance = score_importance(content)
        name = f"Interaction: {role} ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')})"

        node = cls.add_node(
            db=db,
            workspace_id=workspace_id,
            node_type="episodic_memory",
            name=name,
            content=content,
            importance_score=importance,
            properties={"role": role},
            user_id=user_id,
        )

        # Check for explicit user preference declaration
        if role == "user" and importance >= 0.8:
            cls._extract_and_link_preference(db, workspace_id, node, content, user_id)

        return node

    @classmethod
    def _extract_and_link_preference(
        cls,
        db: Session,
        workspace_id: int,
        source_node: MemoryNode,
        content: str,
        user_id: int | None = None,
    ) -> None:
        """Auto-generate a user preference entity node and link it to the episodic source."""
        pref_node = cls.add_node(
            db=db,
            workspace_id=workspace_id,
            node_type="user_preference",
            name=f"Preference: {content[:40]}...",
            content=content,
            importance_score=0.9,
            properties={"auto_extracted": True},
            user_id=user_id,
        )
        cls.add_edge(
            db=db,
            workspace_id=workspace_id,
            source_id=source_node.id,
            target_id=pref_node.id,
            relation_type="extracted_from",
            weight=1.0,
        )

    @staticmethod
    def get_active_dossier(db: Session, workspace_id: int) -> list[dict[str, Any]]:
        """Retrieve persistent entity attributes, user preferences, and macro concepts."""
        stmt = select(MemoryNode).where(
            and_(
                MemoryNode.workspace_id == workspace_id,
                MemoryNode.invalidated_at.is_(None),
                MemoryNode.node_type.in_(["entity", "user_preference", "concept"]),
            )
        ).order_by(MemoryNode.importance_score.desc())

        nodes = db.scalars(stmt).all()
        return [node.to_dict() for node in nodes]

    @classmethod
    def retrieve_memories(
        cls,
        db: Session,
        workspace_id: int,
        query: str,
        top_k: int = 5,
        min_score: float = 0.2,
    ) -> list[dict[str, Any]]:
        """Retrieve memories and dream insights using tri-factor scoring (Recency * Importance * Relevance)."""
        stmt = select(MemoryNode).where(
            and_(
                MemoryNode.workspace_id == workspace_id,
                MemoryNode.invalidated_at.is_(None),
                MemoryNode.node_type.in_(["episodic_memory", "dream_insight"]),
            )
        )
        nodes = list(db.scalars(stmt).all())
        if not nodes:
            return []

        scored_memories = []
        for node in nodes:
            s_rec = calculate_recency_score(node.last_accessed_at)
            s_imp = node.importance_score
            s_rel = calculate_lexical_relevance(query, f"{node.name} {node.content} {node.summary or ''}")

            # Tri-factor weighted score
            tri_score = (0.2 * s_rec) + (0.3 * s_imp) + (0.5 * s_rel)

            if tri_score >= min_score or s_rel > 0.3:
                scored_memories.append((tri_score, node))

        # Sort descending by score
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        top_results = scored_memories[:top_k]

        # Update access count & timestamp on retrieved items
        now = datetime.now(timezone.utc)
        result_dicts = []
        for score, node in top_results:
            node.access_count += 1
            node.last_accessed_at = now
            m_dict = node.to_dict()
            m_dict["retrieval_score"] = round(score, 4)
            result_dicts.append(m_dict)

        db.flush()
        return result_dicts

    @staticmethod
    def invalidate_node(
        db: Session,
        node_id: str,
        superseded_by_id: str | None = None,
        reason: str | None = None,
    ) -> bool:
        """Soft-invalidate a node and optionally record a superseding directed edge."""
        node = db.get(MemoryNode, node_id)
        if not node or node.invalidated_at is not None:
            return False

        now = datetime.now(timezone.utc)
        node.invalidated_at = now

        if superseded_by_id:
            edge = MemoryEdge(
                workspace_id=node.workspace_id,
                source_id=superseded_by_id,
                target_id=node.id,
                relation_type="supersedes",
                weight=1.0,
                properties={"reason": reason or "temporal_update"},
            )
            db.add(edge)

        db.flush()
        return True

    @staticmethod
    def traverse_neighborhood(
        db: Session,
        root_node_id: str,
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Breadth-first search (BFS) graph traversal from root node up to max_depth."""
        root = db.get(MemoryNode, root_node_id)
        if not root:
            return {"nodes": [], "edges": []}

        visited_nodes: dict[str, dict[str, Any]] = {root.id: root.to_dict()}
        collected_edges: list[dict[str, Any]] = []

        current_level = [root.id]
        for depth in range(max_depth):
            if not current_level:
                break
            next_level = set()

            # Find all outgoing and incoming active edges
            stmt = select(MemoryEdge).where(
                and_(
                    or_(
                        MemoryEdge.source_id.in_(current_level),
                        MemoryEdge.target_id.in_(current_level),
                    ),
                    MemoryEdge.invalidated_at.is_(None),
                )
            )
            edges = db.scalars(stmt).all()

            for edge in edges:
                edge_dict = edge.to_dict()
                if edge_dict not in collected_edges:
                    collected_edges.append(edge_dict)

                neighbor_id = edge.target_id if edge.source_id in current_level else edge.source_id
                if neighbor_id not in visited_nodes:
                    neighbor = db.get(MemoryNode, neighbor_id)
                    if neighbor and neighbor.invalidated_at is None:
                        visited_nodes[neighbor.id] = neighbor.to_dict()
                        next_level.add(neighbor.id)

            current_level = list(next_level)

        return {
            "nodes": list(visited_nodes.values()),
            "edges": collected_edges,
        }

    @staticmethod
    def format_memory_context(
        dossier: list[dict[str, Any]],
        memories: list[dict[str, Any]],
    ) -> str:
        """Format retrieved dossier entities and memories for LLM prompt injection."""
        sections = []

        if dossier:
            dossier_lines = []
            for item in dossier:
                val = item.get("content") or item.get("name")
                dossier_lines.append(f"- [{item.get('node_type', 'Entity').upper()}] {item['name']}: {val}")
            sections.append("### Active User & Workspace Dossier:\n" + "\n".join(dossier_lines))

        if memories:
            memory_lines = []
            for mem in memories:
                origin = "Dream Insight" if mem.get("node_type") == "dream_insight" else "Memory"
                summary = mem.get("summary") or mem.get("content")
                memory_lines.append(f"- [{origin}] {mem['name']}: {summary}")
            sections.append("### Relevant Past Context & Insights:\n" + "\n".join(memory_lines))

        return "\n\n".join(sections).strip()
