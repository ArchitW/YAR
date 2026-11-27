"""Tests for SearXNG metasearch tool and Agentic Orchestrator (TKT-020)."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.agent.orchestrator import AgenticOrchestrator
from app.services.chat import answer_query, stream_answer_query
from app.services.providers import LLMProvider
from app.services.tools.searxng import DuckDuckGoSearchTool, SearXNGSearchTool


class FakeProvider(LLMProvider):
    name = "fake-llm"
    model = "test-agent"

    def __init__(self, answer: str = "Synthesized response [1]."):
        self.answer = answer

    def complete(self, system: str, user: str) -> str:
        return self.answer

    def stream_complete(self, system: str, user: str):
        yield self.answer


# ---------------------------------------------------------------------------
# 1. Tests for SearXNG & DuckDuckGo Search Tools
# ---------------------------------------------------------------------------

class TestSearchTools:
    def test_searxng_search_success(self):
        tool = SearXNGSearchTool(base_url="http://fake-searxng:8080")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "title": "SearXNG Project",
                    "url": "https://searx.github.io/searxng/",
                    "content": "A privacy-respecting metasearch engine.",
                }
            ]
        }

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            results = tool.search("searxng privacy")
            assert len(results) == 1
            assert results[0]["title"] == "SearXNG Project"
            assert results[0]["url"] == "https://searx.github.io/searxng/"
            assert results[0]["snippet"] == "A privacy-respecting metasearch engine."
            assert results[0]["source"] == "searxng"

    @patch.object(DuckDuckGoSearchTool, "search")
    def test_searxng_fallback_to_duckduckgo_when_offline(self, mock_ddg):
        mock_ddg.return_value = [
            {"title": "DDG Result", "url": "https://ddg.com", "snippet": "DDG snippet", "source": "duckduckgo"}
        ]
        tool = SearXNGSearchTool(base_url="http://offline-searxng:8080")

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.side_effect = Exception("Connection refused")

        with patch("httpx.Client", return_value=mock_client):
            results = tool.search("query")
            assert len(results) == 1
            assert results[0]["source"] == "duckduckgo"
            assert mock_ddg.called

    def test_duckduckgo_html_parser(self):
        mock_html = """
        <div class="result__body">
            <h2 class="result__title"><a href="https://duckduckgo.com">DuckDuckGo Search</a></h2>
            <a class="result__snippet" href="#">Privacy simplified.</a>
            <a class="result__url" href="https://duckduckgo.com">duckduckgo.com</a>
        </div>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            results = DuckDuckGoSearchTool.search("privacy search")
            assert len(results) == 1
            assert "Privacy simplified" in results[0]["snippet"]
            assert results[0]["url"] == "https://duckduckgo.com"


# ---------------------------------------------------------------------------
# 2. Tests for AgenticOrchestrator
# ---------------------------------------------------------------------------

class TestAgenticOrchestrator:
    def test_explicit_web_query_detection(self):
        assert AgenticOrchestrator.is_explicit_web_query("search the web for Python 3.13") is True
        assert AgenticOrchestrator.is_explicit_web_query("latest news on quantum computing") is True
        assert AgenticOrchestrator.is_explicit_web_query("current weather in Tokyo") is True
        assert AgenticOrchestrator.is_explicit_web_query("What is late chunking?") is False

    @patch("app.services.agent.orchestrator.searxng_settings", return_value={"enabled": True, "confidence_threshold": 0.25})
    def test_should_search_web_decision(self, _mock_settings):
        # 1. Explicit query triggers search regardless of document hits
        assert AgenticOrchestrator.should_search_web("search online for X", hits=[{"score": 0.9}]) is True

        # 2. Empty hits triggers search
        assert AgenticOrchestrator.should_search_web("What is X?", hits=[]) is True

        # 3. Low confidence hits (< 0.25) triggers search
        assert AgenticOrchestrator.should_search_web("What is X?", hits=[{"score": 0.15}]) is True

        # 4. High confidence hits (>= 0.25) bypasses search
        assert AgenticOrchestrator.should_search_web("What is X?", hits=[{"score": 0.85}]) is False

        # 5. Disabled setting bypasses search
        with patch("app.services.agent.orchestrator.searxng_settings", return_value={"enabled": False}):
            assert AgenticOrchestrator.should_search_web("search the web for X", hits=[]) is False

    @patch("app.services.agent.orchestrator.searxng_settings", return_value={"enabled": True, "confidence_threshold": 0.25})
    def test_execute_web_fallback_formats_citations(self, _mock_settings):
        mock_tool = MagicMock()
        mock_tool.search.return_value = [
            {"title": "Docs", "url": "https://example.com/docs", "snippet": "Useful doc", "source": "searxng"}
        ]

        existing = [{"index": 1, "file_name": "local.txt"}]
        context, web_cits = AgenticOrchestrator.execute_web_fallback(
            query="test",
            existing_citations=existing,
            search_tool=mock_tool,
        )

        assert len(web_cits) == 1
        assert web_cits[0]["index"] == 2
        assert web_cits[0]["is_web"] is True
        assert web_cits[0]["url"] == "https://example.com/docs"
        assert "[2] [Web Source: Docs]" in context


# ---------------------------------------------------------------------------
# 3. Chat Integration with Agentic Web Tool Fallback
# ---------------------------------------------------------------------------

class TestChatAgenticWebIntegration:
    @patch("app.services.chat.retrieve", return_value=[])
    @patch.object(AgenticOrchestrator, "execute_web_fallback")
    @patch("app.services.agent.orchestrator.searxng_settings", return_value={"enabled": True, "confidence_threshold": 0.25})
    def test_answer_query_uses_web_fallback_when_no_docs(self, mock_settings, mock_fallback, mock_ret):
        mock_fallback.return_value = (
            "[1] [Web Source: PyTorch] (https://pytorch.org)\nPyTorch 2.5 released.",
            [{"index": 1, "is_web": True, "file_name": "PyTorch", "url": "https://pytorch.org", "text": "Released."}],
        )
        provider = FakeProvider(answer="PyTorch 2.5 is out [1].")

        ans = answer_query(workspace_id=1, message="What is latest PyTorch?", provider=provider)

        assert ans["answer"] == "PyTorch 2.5 is out [1]."
        assert len(ans["citations"]) == 1
        assert ans["citations"][0]["is_web"] is True
        assert ans["citations"][0]["url"] == "https://pytorch.org"

    @patch("app.services.chat.retrieve", return_value=[])
    @patch.object(AgenticOrchestrator, "execute_web_fallback")
    @patch("app.services.agent.orchestrator.searxng_settings", return_value={"enabled": True, "confidence_threshold": 0.25})
    def test_stream_answer_query_emits_web_citations(self, mock_settings, mock_fallback, mock_ret):
        mock_fallback.return_value = (
            "[1] [Web Source: LangChain] (https://langchain.com)\nLangChain framework.",
            [{"index": 1, "is_web": True, "file_name": "LangChain", "url": "https://langchain.com", "text": "LangChain."}],
        )
        provider = FakeProvider(answer="LangChain info [1].")

        events = list(stream_answer_query(workspace_id=1, message="What is LangChain?", provider=provider))

        init = next(e for e in events if e["type"] == "init")
        assert init["type"] == "init"
        done = events[-1]
        assert len(done["citations"]) == 1
        assert done["citations"][0]["is_web"] is True
        assert done["answer"] == "LangChain info [1]."
