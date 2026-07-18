"""Tests for Phase 2 fixes: speed & efficiency improvements."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adal.tools.web_search import _fetch_cache as module_fetch_cache
from adal.tools.web_search import async_fetch_url, async_search_web


class TestEmptyResultsCacheGuard:
    """Fix 2c: Empty DDG results are not cached, allowing Wikipedia fallback."""

    @pytest.mark.asyncio
    async def test_empty_results_not_cached(self):
        with patch("adal.tools.web_search._query_cache", new_callable=dict) as query_cache:
            mock_lock = AsyncMock()
            mock_lock.__aenter__ = AsyncMock(return_value=None)
            mock_lock.__aexit__ = AsyncMock(return_value=None)

            mock_settings = MagicMock()
            mock_settings.search_max_results = 5
            mock_settings.search_throttle_delay = 0.0
            mock_settings.search_max_retries = 1

            mock_client_cls = MagicMock()
            mock_client = AsyncMock()
            mock_client.get = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = (
                '<html><body>'
                '<a class="not-a-result" href="https://example.com">Test</a>'
                '</body></html>'
            )
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("adal.tools.web_search.httpx.AsyncClient", return_value=mock_client_cls.return_value),
                patch("adal.tools.web_search._search_lock", mock_lock),
                patch("adal.tools.web_search._time.time", return_value=1.0),
                patch("adal.tools.web_search.settings", mock_settings),
            ):
                await async_search_web("test empty query")

            cache_key = "test empty query|5"
            assert cache_key not in query_cache, (
                "Empty DDG results must not be cached to allow Wikipedia fallback"
            )


class TestWikipediaCache:
    """Fix 2d: Wikipedia fallback results are cached."""

    @pytest.mark.asyncio
    async def test_wikipedia_results_cached(self):
        wiki_response = json.dumps(
            {"query": "test query", "results": [
                {"title": "Test Article", "url": "https://en.wikipedia.org/wiki/Test", "snippet": "Wikipedia article: Test Article"}
            ], "source": "fallback:wikipedia"},
            ensure_ascii=False,
        )

        cache: dict[str, str] = {}
        cache_key = "test wiki query|5"

        mock_lock = AsyncMock()
        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=None)

        mock_settings = MagicMock()
        mock_settings.search_max_results = 5
        mock_settings.search_throttle_delay = 0.0
        mock_settings.search_max_retries = 1

        mock_client_cls = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        async def mock_wiki(query, max_results=None, _cache=None, cache_key=None):
            if _cache is not None and cache_key:
                _cache[cache_key] = wiki_response
            return wiki_response

        with (
            patch("adal.tools.web_search._wikipedia_search", side_effect=mock_wiki),
            patch("adal.tools.web_search.httpx.AsyncClient", return_value=mock_client_cls.return_value),
            patch("adal.tools.web_search._search_lock", mock_lock),
            patch("adal.tools.web_search._time.time", return_value=1.0),
            patch("adal.tools.web_search.settings", mock_settings),
        ):
            result = await async_search_web("test wiki query", _cache=cache)

        parsed = json.loads(result)
        assert parsed.get("source") == "fallback:wikipedia"
        assert cache_key in cache, (
            "Wikipedia result should be cached at the same cache key DDG would use"
        )


class TestFetchUrlModuleCache:
    """Fix 2e: fetch_url has a module-level fallback cache."""

    @pytest.mark.asyncio
    async def test_module_level_cache_used(self):
        module_fetch_cache.clear()
        module_fetch_cache["https://cached.test"] = json.dumps(
            {"url": "https://cached.test", "content": "cached content", "length": 14}
        )

        try:
            result = await async_fetch_url("https://cached.test")
            parsed = json.loads(result)
            assert parsed.get("content") == "cached content"
        finally:
            module_fetch_cache.clear()

    @pytest.mark.asyncio
    async def test_result_written_to_module_cache(self):
        mock_settings = MagicMock()
        mock_settings.fetch_max_chars = 10000
        mock_settings.fetch_max_retries = 1

        mock_client_cls = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html><body>test content</body></html>"
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        module_fetch_cache.clear()

        with (
            patch("adal.tools.web_search.httpx.AsyncClient", return_value=mock_client_cls.return_value),
            patch("adal.tools.web_search._get_blocked_hosts", return_value=set()),
            patch("adal.tools.web_search._clean_ddg_url", side_effect=lambda u: u),
            patch("adal.tools.web_search.settings", mock_settings),
        ):
            try:
                result = await async_fetch_url("https://new-url.test")
                parsed = json.loads(result)
                assert "test content" in parsed.get("content", "")
                assert "https://new-url.test" in module_fetch_cache, (
                    "Successful fetch result should be written to module-level cache"
                )
            finally:
                module_fetch_cache.clear()


class TestFetchErrorCached:
    """Fix 2f: HTTP error responses are cached."""

    @pytest.mark.asyncio
    async def test_404_error_cached(self):
        cache: dict[str, str] = {}
        mock_settings = MagicMock()
        mock_settings.fetch_max_retries = 1

        mock_client_cls = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("adal.tools.web_search.httpx.AsyncClient", return_value=mock_client_cls.return_value),
            patch("adal.tools.web_search._get_blocked_hosts", return_value=set()),
            patch("adal.tools.web_search._clean_ddg_url", side_effect=lambda u: u),
            patch("adal.tools.web_search.settings", mock_settings),
        ):
            await async_fetch_url("https://dead-url.test/404", _cache=cache)
            assert "https://dead-url.test/404" in cache, (
                "404 error response should be cached to prevent repeated fetches"
            )
            cached = json.loads(cache["https://dead-url.test/404"])
            assert "Fetch failed" in cached.get("error", "")

    @pytest.mark.asyncio
    async def test_cached_error_returned_without_http_call(self):
        cache: dict[str, str] = {}
        cache["https://dead-url.test/403"] = json.dumps(
            {"error": "Fetch failed: HTTP 403", "url": "https://dead-url.test/403"}
        )

        with (
            patch("adal.tools.web_search._get_blocked_hosts", return_value=set()),
            patch("adal.tools.web_search._clean_ddg_url", side_effect=lambda u: u),
            patch("adal.tools.web_search.settings"),
        ):
            result = await async_fetch_url("https://dead-url.test/403", _cache=cache)
            parsed = json.loads(result)
            assert "HTTP 403" in parsed.get("error", "")


class TestMemoryEnrichContextCap:
    """Fix 2g: memory_enrich_context_cap is wired to config."""

    @pytest.mark.asyncio
    async def test_uses_config_cap(self):
        from adal.agents.base import BaseAgent

        class DummyAgent(BaseAgent):
            role = "test"
            system_prompt = "test"

            def build_prompt(self, context):
                return ""

        agent = DummyAgent()
        agent.current_session_id = "test-session"

        mock_store = MagicMock()
        mock_store.query_session_memory = AsyncMock(return_value=[])
        agent._memory = mock_store

        with patch("adal.agents.base.settings") as mock_settings:
            mock_settings.memory_max_episodic = 5
            mock_settings.memory_enrich_context_cap = 7

            await agent._enrich_context({"directive": "test query"})

        call_kwargs = mock_store.query_session_memory.call_args[1]
        limit_arg = call_kwargs.get("limit")
        assert limit_arg == 5, (
            f"Expected limit=min(5, 7)=5, got {limit_arg}"
        )


class TestOversampleFactor:
    """Fix 2h: memory_query_oversample_factor is wired to config."""

    @pytest.mark.asyncio
    async def test_uses_config_factor(self):
        from adal.memory.store import MemoryStore

        store = MemoryStore()
        store._connected = True
        store._embedder = MagicMock()
        store._embedder.get_embedding = AsyncMock(return_value=[0.1] * 1536)
        store._failure_vectors = []
        store._failure_vectors_loaded = True

        mock_table = MagicMock()
        mock_table.search.return_value = mock_table
        mock_table.where.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.to_arrow.return_value = MagicMock(num_rows=0)
        store._table = mock_table

        with patch("adal.memory.store.settings") as mock_settings:
            mock_settings.memory_query_oversample_factor = 7
            mock_settings.memory_max_episodic = 3
            mock_settings.memory_prune_threshold = 0.85

            await store.query_session_memory("test query", "test-session")

        limit_call = mock_table.limit.call_args[0][0]
        assert limit_call == 21, (
            f"Expected fetch_n = max(10, 3 * 7) = 21, got {limit_call}"
        )
