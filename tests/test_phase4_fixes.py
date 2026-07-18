"""Tests for Phase 4: Greptile-identified streak counter + crash handler fixes."""

from unittest.mock import patch

import pytest


class TestCrashStreakAccumulates:
    """Fix A: proposer_crash_streak persists across iterations."""

    @pytest.mark.asyncio
    async def test_streak_not_reset_by_iteration_boundary(self):
        """Counter init is before the while loop, not inside it."""
        with open("src/adal/loop/orchestrator.py") as f:
            content = f.read()

        # Find the while loop in run() and verify counters are before it
        run_start = content.find("async def run(self, query: str,")
        run_section = content[run_start:]

        while_idx = run_section.find("while state.iteration < settings.max_iterations:")
        assert while_idx > 0, "Could not find while loop in run()"

        pre_while = run_section[while_idx - 200:while_idx]
        assert "proposer_crash_streak = 0" in pre_while, (
            "proposer_crash_streak must be initialized BEFORE the while loop, not inside it"
        )
        assert "invalid_action_streak = 0" in pre_while, (
            "invalid_action_streak must be initialized BEFORE the while loop, not inside it"
        )

    @pytest.mark.asyncio
    async def test_run_loop_has_counter_inits(self):
        """_run_loop has counter inits before its while loop."""
        with open("src/adal/loop/orchestrator.py") as f:
            content = f.read()

        run_loop_start = content.find("async def _run_loop(self, session_id:")
        run_loop_section = content[run_loop_start:]

        while_idx = run_loop_section.find("while state.iteration < settings.max_iterations:")
        pre_while = run_loop_section[while_idx - 200:while_idx]
        assert "proposer_crash_streak = 0" in pre_while, (
            "_run_loop must initialize proposer_crash_streak before the while loop"
        )
        assert "invalid_action_streak = 0" in pre_while, (
            "_run_loop must initialize invalid_action_streak before the while loop"
        )


class TestRunLoopCrashHandler:
    """Fix B: _run_loop crash handler has fatal_flaws and streak tracking."""

    def test_crash_handler_has_fatal_flaws_key(self):
        """_run_loop crash entries include 'fatal_flaws' for PIVOT detection."""
        with open("src/adal/loop/orchestrator.py") as f:
            content = f.read()

        # The _run_loop crash handler should contain fatal_flaws
        run_loop_start = content.find("async def _run_loop(self, session_id:")
        run_loop_section = content[run_loop_start:]

        # Find the second proposer crash handler (in _run_loop)
        first_crash = run_loop_section.find("state.prior_failures.append")
        second_crash = run_loop_section.find("state.prior_failures.append", first_crash + 1)

        assert second_crash > 0, "Could not find _run_loop crash handler"
        crash_block = run_loop_section[second_crash:second_crash + 500]
        assert '"fatal_flaws"' in crash_block, (
            "_run_loop crash handler missing 'fatal_flaws' key — PIVOT detection won't work"
        )

    def test_crash_handler_has_streak_tracking(self):
        """_run_loop crash handler tracks proposer_crash_streak."""
        with open("src/adal/loop/orchestrator.py") as f:
            content = f.read()

        run_loop_start = content.find("async def _run_loop(self, session_id:")
        run_loop_section = content[run_loop_start:]

        assert "proposer_crash_streak_limit_restore" in run_loop_section, (
            "_run_loop missing proposer crash streak bailout"
        )

    def test_crash_handler_has_streak_reset_after_success(self):
        """_run_loop resets crash streak after successful propose."""
        with open("src/adal/loop/orchestrator.py") as f:
            content = f.read()

        run_loop_start = content.find("async def _run_loop(self, session_id:")
        run_loop_section = content[run_loop_start:]

        # Should have proposer_crash_streak = 0 after continue
        assert "proposer_crash_streak = 0" in run_loop_section, (
            "_run_loop must reset crash streak after successful propose"
        )


class TestRunRestoreInvalidAction:
    """Fix B: run_restore tracks invalid_action_streak."""

    def test_restore_has_streak_init(self):
        """run_restore initializes invalid_action_streak before its loop."""
        with open("src/adal/loop/orchestrator.py") as f:
            content = f.read()

        restore_start = content.find("async def run_restore(self, query:")
        restore_section = content[restore_start:]

        while_idx = restore_section.find("while state.iteration < settings.max_iterations:")
        pre_while = restore_section[while_idx - 300:while_idx]
        assert "invalid_action_streak = 0" in pre_while, (
            "run_restore must initialize invalid_action_streak before the while loop"
        )

    def test_restore_action_parse_has_streak(self):
        """run_restore action parsing tracks invalid actions."""
        with open("src/adal/loop/orchestrator.py") as f:
            content = f.read()

        restore_start = content.find("async def run_restore(self, query:")
        restore_section = content[restore_start:]

        assert "invalid_action_streak += 1" in restore_section, (
            "run_restore must increment invalid_action_streak on bad action"
        )


class TestSelfCritiqueRunsFirstIteration:
    """Fix C: Self-critique runs even with empty previous_attempts."""

    @pytest.mark.asyncio
    async def test_critique_called_on_empty_prior(self):
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

        call_count = 0

        async def mock_self_critique(result, prev, domain):
            nonlocal call_count
            call_count += 1
            return {"issues_found": [], "suggested_fix": "", "confidence_adjustment": 0.0}

        with (
            patch.object(proposer, "_think_smart", side_effect=mock_think_smart),
            patch.object(proposer, "_self_critique", side_effect=mock_self_critique),
        ):
            await proposer.propose(
                directive="test",
                domain="chemistry",
                previous_attempts=[],
            )

        assert call_count == 1, (
            f"Self-critique should be called on first iteration, got {call_count} calls"
        )
