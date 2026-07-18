"""Tests for Phase 1 fixes: P0 bugs + P1 loop-prevention."""

from unittest.mock import patch

import pytest

from adal.agents.verifier import Verifier


class TestDeepVerifyMerge:
    """Fix 1: Deep verification merge no longer drops new checks."""

    def test_new_deep_check_retained(self):
        verifier = Verifier()
        first = {
            "verdict": "PARTIAL",
            "confidence": 0.6,
            "checks_performed": [
                {"check_name": "stoichiometry", "result": "PASS"},
                {"check_name": "yield_estimate", "result": "WARNING"},
            ],
        }
        deep = {
            "checks_performed": [
                {"check_name": "yield_estimate", "result": "PASS"},
                {"check_name": "workup_feasibility", "result": "PASS"},
            ],
        }

        merged = verifier._merge_verification_results(first, deep)

        checks = merged.get("checks_performed", [])
        names = {c.get("check_name") for c in checks if isinstance(c, dict)}
        assert "workup_feasibility" in names, (
            "Deep verification's new PASS check (workup_feasibility) "
            "was dropped by merge logic"
        )
        assert "stoichiometry" in names
        assert "yield_estimate" in names

    def test_overwrite_existing_check_from_deep(self):
        verifier = Verifier()
        first = {
            "checks_performed": [
                {"check_name": "yield", "result": "WARNING"},
            ],
        }
        deep = {
            "checks_performed": [
                {"check_name": "yield", "result": "PASS"},
            ],
        }

        merged = verifier._merge_verification_results(first, deep)
        yield_check = next(
            (c for c in merged["checks_performed"] if c.get("check_name") == "yield"),
            None,
        )
        assert yield_check is not None
        assert yield_check["result"] == "PASS", (
            "Deep verification PASS should overwrite first-pass WARNING"
        )

    def test_deep_verdict_overrides_first_pass(self):
        verifier = Verifier()
        first = {"verdict": "PARTIAL", "confidence": 0.6}
        deep = {"verdict": "PASS", "confidence": 0.92}

        merged = verifier._merge_verification_results(first, deep)
        assert merged["verdict"] == "PASS"
        assert merged["confidence"] == 0.92

    def test_deep_flaws_appended(self):
        verifier = Verifier()
        first = {
            "fatal_flaws": ["flaw_a"],
        }
        deep = {
            "fatal_flaws": ["flaw_a", "flaw_b"],
        }

        merged = verifier._merge_verification_results(first, deep)
        assert "flaw_a" in merged["fatal_flaws"]
        assert "flaw_b" in merged["fatal_flaws"]
        assert len(merged["fatal_flaws"]) == 2

    def test_deep_suggestions_deduplicated(self):
        verifier = Verifier()
        first = {"suggestions": ["use colder conditions"]}
        deep = {"suggestions": ["use colder conditions", "add drying step"]}

        merged = verifier._merge_verification_results(first, deep)
        assert len(merged["suggestions"]) == 2
        assert "add drying step" in merged["suggestions"]

    def test_empty_deep_pass_no_checks_lost(self):
        verifier = Verifier()
        first = {
            "verdict": "PASS",
            "confidence": 0.9,
            "checks_performed": [
                {"check_name": "math", "result": "PASS"},
                {"check_name": "physics", "result": "PASS"},
            ],
        }
        deep = {}

        merged = verifier._merge_verification_results(first, deep)
        assert merged["verdict"] == "PASS"
        assert len(merged["checks_performed"]) == 2


class TestProposerSelfCritiqueApplied:
    """Fix 2: Self-critique results are applied to the hypothesis."""

    @pytest.mark.asyncio
    async def test_confidence_adjustment_applied(self):
        from adal.agents.proposer import Proposer

        proposer = Proposer()
        proposer._debug_callback = None
        proposer._search_cache = None

        fake_response = (
            '{"domain": "chemistry", '
            '"analysis_summary": "Synthesis of X via Y", '
            '"hypothesis": {"statement": "React A with B", "confidence": 0.7}, '
            '"python_script": ""}'
        )
        fake_critique = {
            "issues_found": ["yield is overstated"],
            "suggested_fix": "Recalculate with literature yield range",
            "confidence_adjustment": -0.15,
        }

        async def mock_think_smart(context, **kwargs):
            return fake_response

        async def mock_self_critique(result, prev, domain):
            return fake_critique

        with (
            patch.object(proposer, "_think_smart", side_effect=mock_think_smart),
            patch.object(proposer, "_self_critique", side_effect=mock_self_critique),
        ):
            result = await proposer.propose(
                directive="test directive",
                domain="chemistry",
                previous_attempts=[{"iteration": 0, "hypothesis_summary": "prev attempt", "fatal_flaws": ["bad yield"]}],
            )

        hyp = result.get("hypothesis", {})
        assert isinstance(hyp, dict)
        assert abs(hyp.get("confidence") - 0.55) < 0.001, (
            f"Expected confidence ~0.55, got {hyp.get('confidence')}"
        )

    @pytest.mark.asyncio
    async def test_suggested_fix_injected(self):
        from adal.agents.proposer import Proposer

        proposer = Proposer()
        proposer._debug_callback = None
        proposer._search_cache = None

        async def mock_think_smart(context, **kwargs):
            return (
                '{"domain": "chemistry", '
                '"analysis_summary": "Quick synthesis route", '
                '"hypothesis": {"statement": "React A+B", "confidence": 0.5}, '
                '"python_script": ""}'
            )

        async def mock_self_critique(result, prev, domain):
            return {
                "issues_found": ["missing workup"],
                "suggested_fix": "Add acid-base extraction workup",
                "confidence_adjustment": 0.0,
            }

        with (
            patch.object(proposer, "_think_smart", side_effect=mock_think_smart),
            patch.object(proposer, "_self_critique", side_effect=mock_self_critique),
        ):
            result = await proposer.propose(
                directive="test",
                domain="chemistry",
                previous_attempts=[{"iteration": 0, "hypothesis_summary": "prev"}],
            )

        summary = result.get("analysis_summary", "")
        assert "[Self-Critique Correction]" in summary
        assert "acid-base extraction workup" in summary

    @pytest.mark.asyncio
    async def test_issues_injected_into_hypothesis_notes(self):
        from adal.agents.proposer import Proposer

        proposer = Proposer()
        proposer._debug_callback = None
        proposer._search_cache = None

        async def mock_think_smart(context, **kwargs):
            return (
                '{"domain": "chemistry", '
                '"analysis_summary": "Test", '
                '"hypothesis": {"statement": "Test rxn", "confidence": 0.8}, '
                '"python_script": ""}'
            )

        async def mock_self_critique(result, prev, domain):
            return {
                "issues_found": ["bad stoichiometry", "unrealistic yield"],
                "suggested_fix": "",
                "confidence_adjustment": 0.0,
            }

        with (
            patch.object(proposer, "_think_smart", side_effect=mock_think_smart),
            patch.object(proposer, "_self_critique", side_effect=mock_self_critique),
        ):
            result = await proposer.propose(
                directive="test",
                domain="chemistry",
                previous_attempts=[{"iteration": 0, "hypothesis_summary": "prev"}],
            )

        notes = result.get("hypothesis", {}).get("notes", "")
        assert "[Self-Critique flagged]" in notes
        assert "bad stoichiometry" in notes
        assert "unrealistic yield" in notes

    @pytest.mark.asyncio
    async def test_confidence_clamped_to_range(self):
        from adal.agents.proposer import Proposer

        proposer = Proposer()
        proposer._debug_callback = None
        proposer._search_cache = None

        async def mock_think_smart(context, **kwargs):
            return (
                '{"domain": "chemistry", '
                '"analysis_summary": "Test", '
                '"hypothesis": {"statement": "Rxn", "confidence": 0.95}, '
                '"python_script": ""}'
            )

        async def mock_self_critique(result, prev, domain):
            return {
                "issues_found": ["terrible"],
                "suggested_fix": "",
                "confidence_adjustment": -0.5,
            }

        with (
            patch.object(proposer, "_think_smart", side_effect=mock_think_smart),
            patch.object(proposer, "_self_critique", side_effect=mock_self_critique),
        ):
            result = await proposer.propose(
                directive="test",
                domain="chemistry",
                previous_attempts=[{"iteration": 0, "hypothesis_summary": "prev"}],
            )

        conf = result.get("hypothesis", {}).get("confidence")
        assert abs(conf - 0.45) < 0.001, f"Expected clamped ~0.45, got {conf}"

    @pytest.mark.asyncio
    async def test_self_critique_failure_graceful(self):
        from adal.agents.proposer import Proposer

        proposer = Proposer()
        proposer._debug_callback = None
        proposer._search_cache = None

        async def mock_think_smart(context, **kwargs):
            return (
                '{"domain": "chemistry", '
                '"analysis_summary": "Safe route", '
                '"hypothesis": {"statement": "Rxn", "confidence": 0.7}, '
                '"python_script": ""}'
            )

        async def mock_self_critique_crash(result, prev, domain):
            raise RuntimeError("mock crash")

        with (
            patch.object(proposer, "_think_smart", side_effect=mock_think_smart),
            patch.object(
                proposer, "_self_critique", side_effect=mock_self_critique_crash
            ),
        ):
            result = await proposer.propose(
                directive="test",
                domain="chemistry",
                previous_attempts=[{"iteration": 0, "hypothesis_summary": "prev"}],
            )

        assert result.get("hypothesis", {}).get("confidence") == 0.7, (
            "Confidence should be unchanged when self-critique crashes"
        )
