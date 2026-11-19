"""Tests for retrieval strategies and citation schema (TKT-003, TKT-007)."""

from unittest.mock import MagicMock, patch

import pytest
from qdrant_client.models import ScoredPoint

from app.routers.documents import parse_chunk_metadata
from app.services.chat import build_context
from app.services.retrieval import retrieve, rewrite_query


class TestQueryExpansion:
    def test_rewrite_query_short_words(self):
        # Words <= 3 characters are excluded from keyword variant
        variants = rewrite_query("is it an")
        assert variants == ["is it an"]

    def test_rewrite_query_with_keywords(self):
        variants = rewrite_query("calculate fiscal quarterly earnings")
        assert len(variants) == 2
        assert variants[0] == "calculate fiscal quarterly earnings"
        assert variants[1] == "calculate fiscal quarterly earnings"


class TestRetrievalModes:
    @pytest.fixture
    def mock_embeddings(self, monkeypatch):
        monkeypatch.setattr("app.services.retrieval.embed", lambda texts: [[0.1] * 4 for _ in texts])
        monkeypatch.setattr(
            "app.services.retrieval.embed_sparse",
            lambda text: {"indices": [1], "values": [0.5]},
        )
        monkeypatch.setattr("app.services.retrieval.rerank", lambda q, cands: cands)

    def test_semantic_mode_only_runs_dense(self, mock_embeddings, monkeypatch):
        dense_point = MagicMock()
        dense_point.id = "p-dense"
        dense_point.payload = {
            "workspace_id": 1,
            "document_id": 10,
            "file_name": "annual.pdf",
            "page_number": 3,
            "text": "Dense hit",
        }

        mock_query_qdrant = MagicMock(side_effect=lambda client, vec, using, limit: [dense_point] if using == "dense" else [])
        monkeypatch.setattr("app.services.retrieval._query_qdrant", mock_query_qdrant)

        results = retrieve(workspace_id=1, query="revenue", mode="semantic")
        assert len(results) == 1
        assert results[0]["id"] == "p-dense"
        assert results[0]["page_number"] == 3

        # Verify only 'dense' was queried, never 'sparse'
        usings_called = [call.kwargs.get("using") or call.args[2] for call in mock_query_qdrant.call_args_list]
        assert "dense" in usings_called
        assert "sparse" not in usings_called

    def test_keyword_mode_only_runs_sparse(self, mock_embeddings, monkeypatch):
        sparse_point = MagicMock()
        sparse_point.id = "p-sparse"
        sparse_point.payload = {
            "workspace_id": 1,
            "document_id": 11,
            "file_name": "data.csv",
            "section": "Q3",
            "text": "Keyword hit",
        }

        mock_query_qdrant = MagicMock(side_effect=lambda client, vec, using, limit: [sparse_point] if using == "sparse" else [])
        monkeypatch.setattr("app.services.retrieval._query_qdrant", mock_query_qdrant)

        results = retrieve(workspace_id=1, query="revenue", mode="keyword")
        assert len(results) == 1
        assert results[0]["id"] == "p-sparse"
        assert results[0]["section"] == "Q3"

        # Verify only 'sparse' was queried, never 'dense'
        usings_called = [call.kwargs.get("using") or call.args[2] for call in mock_query_qdrant.call_args_list]
        assert "sparse" in usings_called
        assert "dense" not in usings_called

    def test_hybrid_mode_queries_both(self, mock_embeddings, monkeypatch):
        dense_point = MagicMock()
        dense_point.id = "p-1"
        dense_point.payload = {"workspace_id": 1, "text": "Hit 1"}

        sparse_point = MagicMock()
        sparse_point.id = "p-2"
        sparse_point.payload = {"workspace_id": 1, "text": "Hit 2"}

        mock_query_qdrant = MagicMock(
            side_effect=lambda client, vec, using, limit: [dense_point] if using == "dense" else [sparse_point]
        )
        monkeypatch.setattr("app.services.retrieval._query_qdrant", mock_query_qdrant)

        results = retrieve(workspace_id=1, query="revenue", mode="hybrid")
        usings_called = [call.kwargs.get("using") or call.args[2] for call in mock_query_qdrant.call_args_list]
        assert "dense" in usings_called
        assert "sparse" in usings_called
        assert len(results) == 2

    def test_workspace_isolation(self, mock_embeddings, monkeypatch):
        point_other_ws = MagicMock()
        point_other_ws.id = "other"
        point_other_ws.payload = {"workspace_id": 999, "text": "Secret"}

        mock_query_qdrant = MagicMock(return_value=[point_other_ws])
        monkeypatch.setattr("app.services.retrieval._query_qdrant", mock_query_qdrant)

        results = retrieve(workspace_id=1, query="test", mode="auto")
        assert len(results) == 0


class TestCitationSchema:
    def test_parse_chunk_metadata_page(self):
        chunk = "[Page 42]\nExecutive summary of results..."
        meta = parse_chunk_metadata(chunk)
        assert meta["page_number"] == 42
        assert meta["section"] is None

    def test_parse_chunk_metadata_section(self):
        chunk = "[Sheet: Sales Figures]\nProduct, Revenue\nWidgets, 100"
        meta = parse_chunk_metadata(chunk)
        assert meta["section"] == "Sales Figures"
        assert meta["page_number"] is None

    def test_build_context_formats_page_and_section(self):
        hits = [
            {
                "file_name": "report.pdf",
                "page_number": 5,
                "chunk_index": 2,
                "text": "Profit was up 10%.",
            },
            {
                "file_name": "data.xlsx",
                "section": "Q4",
                "chunk_index": 0,
                "text": "Costs down 5%.",
            },
        ]
        context, citations = build_context(hits)
        assert len(citations) == 2
        assert citations[0]["page_number"] == 5
        assert citations[1]["section"] == "Q4"
        assert "[1] report.pdf (page 5, chunk 2)" in context
        assert "[2] data.xlsx (section Q4, chunk 0)" in context
