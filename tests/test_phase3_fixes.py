"""Tests for Phase 3 fixes: structural improvements."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMemoryEnrichmentCache:
    """Fix 3a-A: _enrich_context caches results to avoid redundant queries."""

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_lancedb_query(self):
        """Second call with same directive hits cache, skips LanceDB."""
        from adal.agents.base import BaseAgent

        class DummyAgent(BaseAgent):
            role = "test"
            system_prompt = "test"

            def build_prompt(self, context):
                return ""

        agent = DummyAgent()
        agent.current_session_id = "test-session"

        mock_store = MagicMock()
        mock_store.query_session_memory = AsyncMock(return_value=["memory1", "memory2"])
        agent._memory = mock_store

        with patch("adal.agents.base.settings") as mock_settings:
            mock_settings.memory_max_episodic = 5
            mock_settings.memory_enrich_context_cap = 3

            ctx1 = {"directive": "test directive"}
            await agent._enrich_context(ctx1)
            assert "_session_memory" in ctx1
            assert mock_store.query_session_memory.call_count == 1

            ctx2 = {"directive": "test directive"}
            await agent._enrich_context(ctx2)
            assert "_session_memory" in ctx2
            assert mock_store.query_session_memory.call_count == 1, (
                "Second enrichment with same directive should use cache, not re-query LanceDB"
            )

    @pytest.mark.asyncio
    async def test_different_directive_triggers_new_query(self):
        """Different directive triggers a fresh LanceDB query."""
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
            mock_settings.memory_enrich_context_cap = 3

            await agent._enrich_context({"directive": "directive A"})
            await agent._enrich_context({"directive": "directive B"})

            assert mock_store.query_session_memory.call_count == 2, (
                "Different directives should each trigger a fresh LanceDB query"
            )

    @pytest.mark.asyncio
    async def test_different_session_isolated_cache(self):
        """Different sessions don't share enrichment cache."""
        from adal.agents.base import BaseAgent

        class DummyAgent(BaseAgent):
            role = "test"
            system_prompt = "test"

            def build_prompt(self, context):
                return ""

        agent = DummyAgent()
        agent.current_session_id = "session-A"

        mock_store = MagicMock()
        mock_store.query_session_memory = AsyncMock(return_value=["mem"])
        agent._memory = mock_store

        with patch("adal.agents.base.settings") as mock_settings:
            mock_settings.memory_max_episodic = 5
            mock_settings.memory_enrich_context_cap = 3

            await agent._enrich_context({"directive": "shared directive"})
            agent.current_session_id = "session-B"
            await agent._enrich_context({"directive": "shared directive"})

            assert mock_store.query_session_memory.call_count == 2, (
                "Different sessions should not share enrichment cache"
            )


class TestSelfCritiqueSkip:
    """Fix 3a-B: Self-critique skipped on first iteration."""

    @pytest.mark.asyncio
    async def test_skipped_on_first_iteration(self):
        from adal.agents.proposer import Proposer

        proposer = Proposer()
        proposer._debug_callback = None
        proposer._search_cache = None

        async def mock_think_smart(context, **kwargs):
            return (
                '{"domain": "chemistry", '
                '"analysis_summary": "Test", '
                '"hypothesis": {"statement": "Rxn", "confidence": 0.8}, '
                '"python_script": ""}'
            )

        mock_critique = AsyncMock()

        with (
            patch.object(proposer, "_think_smart", side_effect=mock_think_smart),
            patch.object(proposer, "_self_critique", mock_critique),
        ):
            await proposer.propose(
                directive="test",
                domain="chemistry",
                previous_attempts=[],
            )

        mock_critique.assert_not_called()


class TestCacheLRUBounds:
    """Fix 3a-E: Module-level caches have LRU eviction."""

    def test_cache_put_evicts_when_full(self):
        from collections import OrderedDict

        from adal.tools.web_search import _CACHE_MAX_SIZE, _cache_put

        cache: OrderedDict[str, str] = OrderedDict()
        max_size = _CACHE_MAX_SIZE

        for i in range(max_size + 1):
            _cache_put(cache, f"key-{i}", f"value-{i}")

        assert len(cache) == max_size
        assert "key-0" not in cache, "Oldest entry should be evicted"
        assert f"key-{max_size}" in cache

    def test_cache_put_updates_existing_key(self):
        from collections import OrderedDict

        from adal.tools.web_search import _cache_put

        cache: OrderedDict[str, str] = OrderedDict()
        _cache_put(cache, "key-a", "value-1")
        _cache_put(cache, "key-b", "value-2")
        _cache_put(cache, "key-a", "value-updated")

        assert len(cache) == 2
        assert cache["key-a"] == "value-updated"

    def test_cache_put_plain_dict_unbounded(self):
        from adal.tools.web_search import _cache_put

        cache: dict[str, str] = {}
        for i in range(1000):
            _cache_put(cache, f"key-{i}", f"value-{i}")

        assert len(cache) == 1000, "Plain dict should not be bounded"
