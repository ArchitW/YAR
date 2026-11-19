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

        mock_query_qdrant = MagicMock(
            side_effect=lambda client, vec, using, *args, **kwargs: [dense_point] if using == "dense" else []
        )
        monkeypatch.setattr("app.services.retrieval._query_qdrant", mock_query_qdrant)

        results = retrieve(workspace_id=1, query="revenue", mode="semantic")
        assert len(results) == 1
        assert results[0]["id"] == "p-dense"
        assert results[0]["page_number"] == 3

        # Verify only 'dense' was queried, never 'sparse'
        usings_called = [call.kwargs.get("using") or call.args[2] for call in mock_query_qdrant.call_args_list]
        assert "dense" in usings_called
        assert "sparse" not in usings_called

        # Verify query_filter was passed
        assert mock_query_qdrant.call_args.kwargs.get("query_filter") is not None

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

        mock_query_qdrant = MagicMock(
            side_effect=lambda client, vec, using, *args, **kwargs: [sparse_point] if using == "sparse" else []
        )
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
            side_effect=lambda client, vec, using, *args, **kwargs: [dense_point] if using == "dense" else [sparse_point]
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


class TestSparseEncoding:
    def test_sparse_encoding_unique_and_sorted_indices(self):
        from app.services.embeddings import embed_sparse

        text = "The quick brown fox jumps over the lazy dog and the quick brown fox."
        sp = embed_sparse(text)

        # Qdrant invariant 1: indices must be strictly unique
        assert len(sp["indices"]) == len(set(sp["indices"]))

        # Qdrant invariant 2: indices must be sorted ascending
        assert sp["indices"] == sorted(sp["indices"])

        # Qdrant invariant 3: parallel arrays
        assert len(sp["indices"]) == len(sp["values"])

    def test_sparse_encoding_filters_stopwords(self):
        from app.services.embeddings import embed_sparse

        # "The", "and", "of", "is" are stopwords; only "revenue" and "growth" should be indexed
        sp1 = embed_sparse("revenue growth")
        sp2 = embed_sparse("the revenue and the growth of is")
        assert sp1["indices"] == sp2["indices"]

    def test_sparse_encoding_sublinear_tf(self):
        from app.services.embeddings import embed_sparse

        sp = embed_sparse("revenue revenue revenue")
        assert len(sp["values"]) == 1
        # count is 3, 1 + ln(3) ~ 2.0986
        assert 2.0 < sp["values"][0] < 2.2

    def test_sparse_encoding_empty(self):
        from app.services.embeddings import embed_sparse

        assert embed_sparse("") == {"indices": [], "values": []}


class TestRerankerResilience:
    def test_rerank_fallback_on_model_error(self, monkeypatch):
        from app.services.reranker import rerank

        mock_cross = MagicMock()
        mock_cross.predict.side_effect = RuntimeError("CUDA out of memory")
        monkeypatch.setattr("app.services.reranker.get_reranker", lambda: mock_cross)

        cands = [
            {"id": "a", "text": "doc a", "score": 0.8},
            {"id": "b", "text": "doc b", "score": 0.5},
        ]
        # Should not raise exception
        result = rerank("test query", cands)
        assert len(result) == 2
        assert result[0]["id"] == "a"
        assert result[0]["rerank_score"] == 0.8

