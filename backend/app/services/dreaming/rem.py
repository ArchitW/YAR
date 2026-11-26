"""REM Associative Dreaming & Synthetic Rehearsal Engine (Sleep Phase)."""

from __future__ import annotations

import logging
import math
import os
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct, SparseVector
from sqlalchemy.orm import Session

from ...core.config import get_qdrant_client
from ...models.document import Document
from ...models.memory import MemoryEdge, MemoryNode
from ...services.chunking import adaptive_chunk
from ...services.embeddings import embed, embed_sparse
from ...services.memory import MemoryService
from ..providers import LLMProvider, get_provider

logger = logging.getLogger(__name__)

qdrant = get_qdrant_client()
COLLECTION = "yar_chunks"

DREAM_SYSTEM_PROMPT = (
    "You are YAR's REM Dream Engine. Your role is associative knowledge discovery across "
    "disparate workspace documents. Analyze two separate document components to discover "
    "non-obvious dependencies, potential integration conflicts, or latent architectural synergies."
)


def compute_cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Calculate cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_prod = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    return dot_prod / (norm_a * norm_b) if (norm_a > 0.0 and norm_b > 0.0) else 0.0


class REMDreamer:
    """Discovers cross-document associations and synthesizes pre-computed insights."""

    @classmethod
    def sample_associative_pairs(
        cls,
        workspace_id: int,
        chunks: list[dict[str, Any]],
        min_similarity: float = 0.55,
        max_similarity: float = 0.78,
    ) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
        """Identify chunk pairs across disparate files in the associative sweet spot."""
        pairs: list[tuple[dict[str, Any], dict[str, Any], float]] = []
        if len(chunks) < 2:
            return pairs

        texts = [c.get("text", "") for c in chunks]
        vectors = embed(texts)

        for i in range(len(chunks)):
            for j in range(i + 1, len(chunks)):
                file_a, file_b = chunks[i].get("file_name"), chunks[j].get("file_name")
                if file_a and file_b and file_a == file_b:
                    continue

                sim = compute_cosine_similarity(vectors[i], vectors[j])
                if min_similarity <= sim <= max_similarity:
                    pairs.append((chunks[i], chunks[j], round(sim, 4)))
        return pairs

    @classmethod
    def synthesize_cross_document_insights(
        cls,
        workspace_id: int,
        chunk_a: dict[str, Any],
        chunk_b: dict[str, Any],
        provider: LLMProvider | None = None,
    ) -> dict[str, Any]:
        """Synthesize cross-document connections and latent synergies."""
        file_a = chunk_a.get("file_name", "Component A")
        file_b = chunk_b.get("file_name", "Component B")
        text_a, text_b = str(chunk_a.get("text", "")).strip(), str(chunk_b.get("text", "")).strip()

        llm = provider or get_provider()
        if llm is not None:
            try:
                user_prompt = f"Component 1 ({file_a}):\n{text_a}\n\nComponent 2 ({file_b}):\n{text_b}"
                raw = llm.complete(DREAM_SYSTEM_PROMPT, user_prompt)
                return cls._format_insight_payload(file_a, file_b, raw, chunk_a, chunk_b)
            except Exception:
                logger.warning("LLM dream synthesis failed; falling back to heuristic", exc_info=True)

        return cls._extractive_insight(file_a, file_b, text_a, text_b, chunk_a, chunk_b)

    @staticmethod
    def _format_insight_payload(
        file_a: str, file_b: str, text: str, c_a: dict[str, Any], c_b: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "title": f"Synergy: {file_a} & {file_b}",
            "synthesis": text,
            "cited_chunk_ids": [c_a.get("id"), c_b.get("id")],
            "source_files": [file_a, file_b],
        }

    @staticmethod
    def _extractive_insight(
        file_a: str, file_b: str, text_a: str, text_b: str, c_a: dict[str, Any], c_b: dict[str, Any]
    ) -> dict[str, Any]:
        synthesis = (
            f"Associative connection between {file_a} and {file_b}: "
            f"{text_a[:140]} relates directly to {text_b[:140]}."
        )
        return {
            "title": f"Associative Connection: {file_a} & {file_b}",
            "synthesis": synthesis,
            "cited_chunk_ids": [c_a.get("id"), c_b.get("id")],
            "source_files": [file_a, file_b],
        }

    @classmethod
    def generate_synthetic_qa(
        cls,
        workspace_id: int,
        chunk_a: dict[str, Any],
        chunk_b: dict[str, Any],
        insight: dict[str, Any],
        provider: LLMProvider | None = None,
    ) -> dict[str, str]:
        """Generate multi-hop question and grounded answer."""
        file_a, file_b = chunk_a.get("file_name", "Doc A"), chunk_b.get("file_name", "Doc B")
        llm = provider or get_provider()
        if llm is not None:
            try:
                prompt = f"Based on insight between {file_a} and {file_b}:\n{insight['synthesis']}\nReturn Q: and A:"
                resp = llm.complete("Generate multi-hop Q&A.", prompt)
                if "Q:" in resp and "A:" in resp:
                    parts = resp.split("A:", 1)
                    q = parts[0].replace("Q:", "").strip()
                    a = parts[1].strip()
                    return {"question": q, "answer": a}
            except Exception:
                logger.warning("LLM synthetic QA failed; using heuristic fallback", exc_info=True)

        return {
            "question": f"How does {file_a} relate to {file_b}?",
            "answer": f"Analysis across {file_a} and {file_b} shows: {insight['synthesis']}",
        }

    @classmethod
    def index_dream_insight(
        cls,
        db: Session,
        workspace_id: int,
        dream_data: dict[str, Any],
        qdrant_client: Any | None = None,
    ) -> MemoryNode:
        """Persist dream insight to relational graph and vectorize into Qdrant."""
        title = dream_data.get("title", "Synthesized Insight")
        synthesis = dream_data.get("synthesis", "")
        summary = dream_data.get("summary") or (synthesis[:140] + ("..." if len(synthesis) > 140 else ""))

        node = MemoryService.add_node(
            db=db,
            workspace_id=workspace_id,
            node_type="dream_insight",
            name=title,
            content=synthesis,
            summary=summary,
            importance_score=dream_data.get("importance_score", 0.75),
            properties={
                "multi_hop_query": dream_data.get("multi_hop_query"),
                "synthetic_answer": dream_data.get("synthetic_answer"),
                "cited_chunk_ids": dream_data.get("cited_chunk_ids", []),
                "source_files": dream_data.get("source_files", []),
            },
        )
        db.flush()

        cls._upsert_to_qdrant(workspace_id, node, dream_data, qdrant_client)
        return node

    @classmethod
    def _upsert_to_qdrant(
        cls,
        workspace_id: int,
        node: MemoryNode,
        dream_data: dict[str, Any],
        client: Any | None = None,
    ) -> None:
        """Upsert dream vector into Qdrant collection."""
        from ...routers.documents import ensure_collection

        target_client = client or qdrant
        try:
            ensure_collection(target_client)
            text = f"{node.name}\n\n{node.content}"
            dvec = embed([text])[0]
            sp = embed_sparse(text)
            point = PointStruct(
                id=str(uuid.uuid4()),
                vector={"dense": dvec, "sparse": SparseVector(indices=sp["indices"], values=sp["values"])},
                payload={
                    "workspace_id": workspace_id,
                    "is_dream": True,
                    "dream_insight_id": node.id,
                    "dream_title": node.name,
                    "text": node.content,
                    "file_name": f"Dream Insight: {node.name}",
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "cited_chunk_ids": dream_data.get("cited_chunk_ids", []),
                    "source_files": dream_data.get("source_files", []),
                },
            )
            target_client.upsert(COLLECTION, points=[point])
        except Exception:
            logger.warning("Could not upsert dream insight %s to Qdrant", node.id, exc_info=True)

    @classmethod
    def load_workspace_chunks(cls, db: Session, workspace_id: int) -> list[dict[str, Any]]:
        """Extract candidate document chunks from database for dreaming."""
        docs = db.query(Document).filter_by(workspace_id=workspace_id).all()
        chunks: list[dict[str, Any]] = []
        for doc in docs:
            if not doc.content:
                continue
            doc_chunks = adaptive_chunk(doc.content)
            for idx, c_text in enumerate(doc_chunks):
                chunks.append({
                    "id": f"{doc.id}_{idx}",
                    "document_id": doc.id,
                    "file_name": doc.name,
                    "text": c_text,
                    "chunk_index": idx,
                })
        return chunks

    @classmethod
    def run_dream_cycle(
        cls,
        db: Session,
        workspace_id: int,
        provider: LLMProvider | None = None,
        max_dreams: int = 3,
        qdrant_client: Any | None = None,
    ) -> dict[str, Any]:
        """Execute sleep phase REM dreaming cycle."""
        logger.info("Starting REM dream cycle for workspace %d", workspace_id)
        chunks = cls.load_workspace_chunks(db, workspace_id)
        pairs = cls.sample_associative_pairs(workspace_id, chunks)
        indexed_nodes: list[str] = []

        for chunk_a, chunk_b, _ in pairs[:max_dreams]:
            insight = cls.synthesize_cross_document_insights(workspace_id, chunk_a, chunk_b, provider)
            qa = cls.generate_synthetic_qa(workspace_id, chunk_a, chunk_b, insight, provider)
            insight["multi_hop_query"] = qa.get("question")
            insight["synthetic_answer"] = qa.get("answer")

            node = cls.index_dream_insight(db, workspace_id, insight, qdrant_client)
            indexed_nodes.append(node.id)

        db.flush()
        return {
            "workspace_id": workspace_id,
            "pairs_sampled": len(pairs),
            "indexed_dream_count": len(indexed_nodes),
            "dream_node_ids": indexed_nodes,
        }
