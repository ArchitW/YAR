"""SearXNG metasearch tool with DuckDuckGo privacy fallback (TKT-020)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import unquote

import httpx

from ...core.config import searxng_settings

logger = logging.getLogger(__name__)


class DuckDuckGoSearchTool:
    """Fallback search tool using DuckDuckGo HTML interface."""

    @staticmethod
    def search(query: str, num_results: int = 5) -> list[dict[str, Any]]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        try:
            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                resp = client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": query},
                    headers=headers,
                )
                if resp.status_code != 200:
                    return []
                html = resp.text

            # Parse results from HTML: <a class="result__url" href="...">, <a class="result__snippet">
            results: list[dict[str, Any]] = []
            blocks = re.findall(
                r'<div class="result__body">.*?<a class="result__snippet[^>]*>(.*?)</a>',
                html,
                re.DOTALL,
            )
            urls = re.findall(
                r'<a[^>]*class="result__url"[^>]*href="([^"]+)"',
                html,
            )
            titles = re.findall(
                r'<h2 class="result__title">.*?<a[^>]*>(.*?)</a>',
                html,
                re.DOTALL,
            )

            for i in range(min(len(blocks), len(urls), num_results)):
                snippet = re.sub(r"<[^>]+>", "", blocks[i]).strip()
                raw_url = urls[i].strip()
                if "uddg=" in raw_url:
                    match = re.search(r"uddg=([^&]+)", raw_url)
                    if match:
                        raw_url = unquote(match.group(1))
                title = re.sub(r"<[^>]+>", "", titles[i]).strip() if i < len(titles) else "Web Result"

                if snippet and raw_url:
                    results.append({
                        "title": title or "Web Source",
                        "url": raw_url,
                        "snippet": snippet,
                        "source": "duckduckgo",
                    })

            return results
        except Exception as exc:
            logger.warning("DuckDuckGo search fallback failed: %s", exc)
            return []


class SearXNGSearchTool:
    """Client for local or remote SearXNG metasearch instance."""

    def __init__(self, base_url: str | None = None, timeout: float = 8.0) -> None:
        self.base_url = (base_url or searxng_settings().get("base_url", "")).rstrip("/")
        self.timeout = timeout

    def search(
        self,
        query: str,
        num_results: int = 5,
        categories: str = "general",
    ) -> list[dict[str, Any]]:
        """Search SearXNG JSON endpoint with automatic fallback to DuckDuckGo."""
        if not query.strip():
            return []

        if self.base_url:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(
                        f"{self.base_url}/search",
                        params={
                            "q": query,
                            "format": "json",
                            "categories": categories,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_results = data.get("results", [])
                        results = []
                        for r in raw_results[:num_results]:
                            results.append({
                                "title": r.get("title") or "Web Source",
                                "url": r.get("url") or "",
                                "snippet": r.get("content") or r.get("snippet") or "",
                                "source": "searxng",
                            })
                        if results:
                            return results
            except Exception as exc:
                logger.info(
                    "SearXNG search failed or offline (%s); falling back to DuckDuckGo",
                    exc,
                )

        # Fallback to DuckDuckGo
        return DuckDuckGoSearchTool.search(query, num_results=num_results)
