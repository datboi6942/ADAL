import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog
from sqlalchemy import desc, select

from adal.agents.base import _empty_usage, _merge_usage
from adal.agents.planner import Planner
from adal.agents.proposer import Proposer
from adal.agents.verifier import Verifier
from adal.config import settings
from adal.db.models import (
    AgentInteraction,
    AgentRole,
    Domain,
    Hypothesis,
    HypothesisStatus,
    InteractionDirection,
    PlannerAction,
    PlannerDecision,
    Session,
    SessionStatus,
    ValidationResult,
)
from adal.db.session import get_sessionmaker
from adal.llm.client import _calculate_cost
from adal.memory.store import MemoryStore
from adal.tui.widgets.debug_panel import VERBOSITY_HIGH, VERBOSITY_LOW, VERBOSITY_MED

logger = structlog.get_logger(__name__)


def _normalize_answer(fa):
    if isinstance(fa, dict):
        parts = [f"## {k.replace('_', ' ').title()}\n{v}" for k, v in fa.items()]
        return "\n\n".join(parts)
    return str(fa) if fa else ""


def _safe_domain(raw: str) -> Domain:
    try:
        return Domain(raw)
    except ValueError:
        logger.warning("invalid_domain_classification", raw=raw)
        return Domain.UNKNOWN


@dataclass
class LoopState:
    session_id: str
    query: str
    domain: Domain
    iteration: int = 0
    status: SessionStatus = SessionStatus.ACTIVE
    hypotheses: list[dict] = field(default_factory=list)
    prior_failures: list[dict] = field(default_factory=list)
    validated_results: list[dict] = field(default_factory=list)
    data_context: str = ""
    final_answer: str | None = None
    total_usage: dict = field(default_factory=_empty_usage)
    reasoning_log: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)


class Orchestrator:
    def __init__(self, model: str | None = None, sub_model: str | None = None):
        self.proposer = Proposer(model=model, sub_model=sub_model)
        self.verifier = Verifier(model=model, sub_model=sub_model)
        self.planner = Planner(model=model, sub_model=sub_model)
        self.model = model or settings.deepseek_model or settings.llm_model
        self._display: Callable | None = None
        self._verbose_display: Callable | None = None
        self._debug: Callable | None = None
        self.memory_store = MemoryStore()
        self.proposer._debug_callback = self._dispatch_debug
        self.verifier._debug_callback = self._dispatch_debug
        self.planner._debug_callback = self._dispatch_debug
        self.memory_store._debug_callback = self._dispatch_debug

    def set_display_callback(self, callback: Callable):
        self._display = callback

    def set_verbose_display(self, callback: Callable):
        self._verbose_display = callback

    def set_debug_callback(self, callback: Callable):
        self._debug = callback

    async def _dispatch_debug(self, category: str, event: str, detail: str = "", verbosity: int = VERBOSITY_LOW):
        try:
            if self._debug:
                await self._debug(category, event, detail, verbosity=verbosity)
        except Exception:
            pass

    async def _run_with_heartbeat(self, agent_name: str, coro):
        async def _beat():
            start = time.time()
            while True:
                await asyncio.sleep(5)
                elapsed = int(time.time() - start)
                await self._dispatch_debug(agent_name, "heartbeat", f"Working... {elapsed}s")
        beat_task = asyncio.create_task(_beat())
        try:
            result = await coro
        finally:
            beat_task.cancel()
            try:
                await beat_task
            except asyncio.CancelledError:
                pass
        return result

    async def _display_step(self, name: str, status: str, detail: str = "", verbosity: int = VERBOSITY_LOW):
        try:
            if self._display:
                await self._display(name, status, detail, verbosity=verbosity)
        except Exception:
            logger.warning("display_callback_failed", name=name, status=status)

    async def _display_reasoning(self, name: str, reasoning: str | None, verbosity: int = VERBOSITY_LOW):
        if reasoning:
            if self._verbose_display:
                await self._verbose_display(name, reasoning, verbosity=verbosity)

    def _capture_usage(self, agent) -> dict:
        usage = agent.total_usage
        agent.reset_usage()
        return usage

    def _usage_summary(self, usage: dict) -> str:
        p = usage.get("prompt_tokens", 0)
        c = usage.get("completion_tokens", 0)
        cached = usage.get("cached_tokens", 0)
        cached_pct = (cached / p * 100) if p > 0 else 0
        cost = _calculate_cost(usage)["total_cost"]
        return f"In:{_fmt(p)} Out:{_fmt(c)} Cache:{cached_pct:.0f}% ${cost:.5f}"

    async def run(self, query: str, **display_kwargs) -> dict:
        session_id = str(uuid.uuid4())
        logger.info("orchestrator_start", session_id=session_id, query=query)
        await self._dispatch_debug("fsm", "start", f"Session {session_id[:8]} query: {query[:200]}")

        live_state = display_kwargs.get("_live_state")
        live_refresh = display_kwargs.get("_live_refresh")

        def _refresh():
            if live_refresh:
                live_refresh()

        global_lessons = await self.memory_store.query_global_lessons(query)
        if global_lessons:
            logger.info("global_lessons_found", count=len(global_lessons))

        if live_state:
            live_state.reasoning_agent = "PLANNER"
            live_state.reasoning_text = f"Classifying: {query[:500]}"
        await self._display_step("planner", "thinking", "Classifying domain...")

        state = LoopState(session_id=session_id, query=query, domain=Domain.UNKNOWN)
        await self._persist_session(state)

        await self._wire_memory(session_id)

        try:
            initial_plan = await self._run_with_heartbeat("planner", self.planner.initial_plan(query))
        except Exception as e:
            logger.error("initial_plan_failed", error=str(e))
            await self._display_step("planner", "error", f"Initial plan failed: {e}")
            state.status = SessionStatus.FAILED
            await self._update_session(state)
            await self._dispatch_debug("db", "session_update",
                f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
            return self._build_error_result(session_id, query, str(e))

        domain = _safe_domain(initial_plan.get("domain_classification", "unknown"))
        plan_usage = self._capture_usage(self.planner)
        if live_state:
            live_state.domain = domain.value.upper()
            if self.planner.last_reasoning:
                live_state.reasoning_agent = "PLANNER"
                live_state.reasoning_text = self.planner.last_reasoning
                _refresh()
        await self._display_reasoning("PLANNER", self.planner.last_reasoning, verbosity=VERBOSITY_MED)
        initial_reasoning = self.planner.last_reasoning
        reasoning_tag = _reasoning_tag(self.planner.last_reasoning)
        await self._display_step("planner", "done",
            f"Domain: {domain.value.upper()}  {self._usage_summary(plan_usage)}{reasoning_tag}")
        await self._dispatch_debug("fsm", "config",
            f"Provider={settings.llm_provider} model={self.model} sub_model={settings.deepseek_sub_model or 'none'} "
            f"max_iters={settings.max_iterations} tool_turns={settings.llm_max_tool_turns} "
            f"sandbox_timeout={settings.sandbox_timeout}s memory_enabled={settings.memory_enabled}", verbosity=VERBOSITY_HIGH)
        elapsed = time.time() - state.started_at
        cost = _calculate_cost(plan_usage)["total_cost"]
        await self._dispatch_debug("usage", "planner",
            f"PLANNER call: {plan_usage.get('total_tokens', 0)} tokens, ${cost:.5f}, {elapsed:.0f}s elapsed",
            verbosity=VERBOSITY_MED)
        if live_state:
            live_state.token_info = _token_bar(plan_usage)

        state = LoopState(
            session_id=session_id,
            query=query,
            domain=domain,
        )
        state.total_usage = _merge_usage(state.total_usage, plan_usage)
        if initial_reasoning:
            state.reasoning_log.append({"agent": "PLANNER", "iteration": 0, "text": initial_reasoning})

        current_directive = initial_plan.get(
            "directive_to_proposer",
            f"Analyze and propose a hypothesis for: {query}",
        )

        if global_lessons:
            current_directive += "\n\n## Cross-Session Lessons Learned\n" + "\n".join(
                f"- {g}" for g in global_lessons
            )

        logger.info(
            "planner_initial",
            domain=domain.value,
            directive=current_directive[:200],
            usage=plan_usage,
        )

        while state.iteration < settings.max_iterations:
            state.iteration += 1
            revision_attempted = False
            if live_state:
                live_state.iteration = state.iteration
                _refresh()
            logger.info("iteration_start", iteration=state.iteration, session_id=session_id)
            await self._dispatch_debug("fsm", "iteration", f"Iter {state.iteration}/{settings.max_iterations}  domain={state.domain.value}  failures={len(state.prior_failures)}  validated={len(state.validated_results)}")

            if live_state:
                live_state.reasoning_agent = "PROPOSER"
                live_state.reasoning_text = f"Directive: {current_directive[:500]}"
            await self._display_step("proposer", "thinking", "Generating hypothesis...")
            try:
                proposal = await self._run_with_heartbeat("proposer", self.proposer.propose(
                    directive=current_directive,
                    domain=state.domain.value,
                    previous_attempts=state.prior_failures,
                    data_context=state.data_context,
                ))
            except Exception as e:
                logger.error("proposer_failed", error=str(e))
                await self._display_step("proposer", "error", str(e)[:80])
                state.prior_failures.append({
                    "iteration": state.iteration,
                    "hypothesis_summary": f"Proposer crashed: {e}",
                    "reason": f"Proposer error: {e}",
                })
                current_directive = f"Previous proposer attempt failed with error: {e}. Try a different approach."
                await self._update_session(state)
                await self._dispatch_debug("db", "session_update",
                    f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
                continue

            prop_usage = self._capture_usage(self.proposer)
            if live_state and self.proposer.last_reasoning:
                live_state.reasoning_agent = "PROPOSER"
                live_state.reasoning_text = self.proposer.last_reasoning
                _refresh()
            await self._display_reasoning("PROPOSER", self.proposer.last_reasoning, verbosity=VERBOSITY_MED)
            if self.proposer.last_reasoning:
                state.reasoning_log.append({"agent": "PROPOSER", "iteration": state.iteration, "text": self.proposer.last_reasoning})
            state.total_usage = _merge_usage(state.total_usage, prop_usage)

            hyp = proposal.get("hypothesis", {})
            hypothesis_statement = hyp.get("statement", "") if isinstance(hyp, dict) else str(hyp)
            hypothesis_summary = hypothesis_statement[:150] or proposal.get("analysis_summary", "")[:150]
            display_detail = f"{hypothesis_summary}  {self._usage_summary(prop_usage)}"
            await self._display_step("proposer", "done", display_detail)
            elapsed = time.time() - state.started_at
            cost = _calculate_cost(prop_usage)["total_cost"]
            await self._dispatch_debug("usage", "proposer",
                f"PROPOSER call: {prop_usage.get('total_tokens', 0)} tokens, ${cost:.5f}, {elapsed:.0f}s elapsed",
                verbosity=VERBOSITY_MED)
            if live_state:
                live_state.token_info = _status_bar(state.total_usage, state.started_at)
                _refresh()

            script_ok = proposal.get("execution_result", {}).get("success", False)
            exe = proposal.get("execution_result", {})
            stdout = (exe.get("stdout", "") or "")[:300]
            sandbox_msg = f"ok={script_ok}" + (f" stdout: {stdout}" if stdout else "")
            await self._dispatch_debug("sandbox", "result", sandbox_msg)

            await self._dispatch_debug("proposer", "hypothesis",
                f"Proposal: {hypothesis_statement[:400]}")
            critique = proposal.get("_self_critique", {})
            if critique.get("issues_found"):
                await self._dispatch_debug("proposer", "self_critique",
                    f"Issues: {', '.join(critique['issues_found'][:4])}", verbosity=VERBOSITY_MED)
            if critique.get("confidence_adjustment", 0) != 0:
                await self._dispatch_debug("proposer", "confidence_adj",
                    f"Self-critique adjusted confidence by {critique['confidence_adjustment']}", verbosity=VERBOSITY_MED)
            if critique.get("issues_found"):
                for issue in critique["issues_found"][:8]:
                    await self._dispatch_debug("proposer", "critique_item",
                        f"Self-critique issue: {issue}", verbosity=VERBOSITY_MED)
            script_code = proposal.get("python_script", "")
            if script_code:
                await self._dispatch_debug("sandbox", "script",
                    f"Script length: {len(script_code)} chars — imports: { [line.strip() for line in script_code.split(chr(10)) if line.strip().startswith('import ') or line.strip().startswith('from ')][:5] }", verbosity=VERBOSITY_MED)

            logger.info(
                "proposer_done",
                iteration=state.iteration,
                confidence=hyp.get("confidence", 0),
                statement=hypothesis_statement[:200],
                script_ok=script_ok,
                usage_prompt=prop_usage["prompt_tokens"],
                usage_completion=prop_usage["completion_tokens"],
            )

            await self.memory_store.record_memory(
                text=f"Proposer iteration {state.iteration}: {hypothesis_statement}",
                session_id=session_id,
                agent_role="proposer",
                memory_type="episodic",
                iteration_turn=state.iteration,
            )
            await self._dispatch_debug("memory", "record", f"Proposer episodic iter {state.iteration}: {hypothesis_statement[:200]}", verbosity=VERBOSITY_MED)

            hypothesis_data = {
                "domain": proposal.get("domain", state.domain.value),
                "analysis_summary": proposal.get("analysis_summary", ""),
                "hypothesis": hyp,
                "features_detected": proposal.get("features_detected", []),
                "execution_result": proposal.get("execution_result", {}),
                "data_quality": proposal.get("data_quality", {}),
            }

            state.hypotheses.append(hypothesis_data)
            hypothesis_db = await self._persist_hypothesis(
                state, hypothesis_data, AgentRole.PROPOSER, HypothesisStatus.PROPOSED
            )
            await self._dispatch_debug("db", "hypothesis_persist",
                f"Hypothesis #{hypothesis_db.id[:8]} status={HypothesisStatus.PROPOSED.value}", verbosity=VERBOSITY_HIGH)
            proposal["_reasoning"] = self.proposer.last_reasoning
            await self._persist_interaction(
                state, proposal, AgentRole.PROPOSER,
                InteractionDirection.PROPOSER_TO_VERIFIER, hypothesis_db.id,
            )

            analysis_context = json.dumps({
                "summary": proposal.get("analysis_summary", ""),
                "features": proposal.get("features_detected", []),
                "execution": str(proposal.get("execution_result", {}))[:2000],
            })

            if live_state:
                live_state.reasoning_agent = "VERIFIER"
                live_state.reasoning_text = f"Validating: {hypothesis_statement[:500]}"
            await self._display_step("verifier", "thinking", "Validating hypothesis...")
            try:
                verdict = await self._run_with_heartbeat("verifier", self.verifier.verify(
                    hypothesis=hyp,
                    analysis_context=analysis_context,
                    domain=state.domain.value,
                    prior_failures=state.prior_failures,
                ))
            except Exception as e:
                logger.error("verifier_failed", error=str(e))
                await self._display_step("verifier", "error", str(e)[:80])
                verdict = {
                    "verdict": "FAIL",
                    "confidence": 0.0,
                    "fatal_flaws": [f"Verifier crashed: {e}"],
                    "checks_performed": [],
                    "mathematical_proof": "",
                    "corrected_values": {},
                    "suggestions": [],
                    "numerical_validation": {},
                }

            verif_usage = self._capture_usage(self.verifier)
            if live_state and self.verifier.last_reasoning:
                live_state.reasoning_agent = "VERIFIER"
                live_state.reasoning_text = self.verifier.last_reasoning
                _refresh()
            await self._display_reasoning("VERIFIER", self.verifier.last_reasoning, verbosity=VERBOSITY_MED)
            if self.verifier.last_reasoning:
                state.reasoning_log.append({"agent": "VERIFIER", "iteration": state.iteration, "text": self.verifier.last_reasoning})
            state.total_usage = _merge_usage(state.total_usage, verif_usage)

            verdict_data = {
                "verdict": verdict.get("verdict", "UNKNOWN"),
                "confidence": verdict.get("confidence", 0.0),
                "checks_performed": verdict.get("checks_performed", []),
                "mathematical_proof": verdict.get("mathematical_proof", ""),
                "corrected_values": verdict.get("corrected_values", {}),
                "fatal_flaws": verdict.get("fatal_flaws", []),
                "suggestions": verdict.get("suggestions", []),
                "numerical_validation": verdict.get("numerical_validation", {}),
            }

            checks_passed = sum(
                1 for c in verdict_data["checks_performed"]
                if isinstance(c, dict) and c.get("result") == "PASS"
            )
            total_checks = len(verdict_data["checks_performed"])
            proof_preview = verdict_data.get("mathematical_proof", "")[:120]
            verdict_display = (
                f"Verdict: {verdict_data['verdict']} ({verdict_data['confidence']:.0%})  "
                f"Checks: {checks_passed}/{total_checks}  {self._usage_summary(verif_usage)}"
            )
            if proof_preview and proof_preview != "None":
                verdict_display += f"\nProof: {proof_preview}"
            await self._display_step("verifier", "done", verdict_display)
            elapsed = time.time() - state.started_at
            cost = _calculate_cost(verif_usage)["total_cost"]
            await self._dispatch_debug("usage", "verifier",
                f"VERIFIER call: {verif_usage.get('total_tokens', 0)} tokens, ${cost:.5f}, {elapsed:.0f}s elapsed",
                verbosity=VERBOSITY_MED)
            if live_state:
                live_state.token_info = _status_bar(state.total_usage, state.started_at)
                _refresh()

            fatal_count = len(verdict_data.get("fatal_flaws", []))
            flaws_list = verdict_data.get("fatal_flaws", [])
            if flaws_list:
                await self._dispatch_debug("verifier", "fatal_flaws",
                    f"{fatal_count} fatal: {', '.join(str(f)[:100] for f in flaws_list[:5])}")
            checks = verdict_data.get("checks_performed", [])
            for c in checks[:6]:
                result = c.get("result", "?") if isinstance(c, dict) else "?"
                name = c.get("check", c.get("check_name", c.get("name", "unknown"))) if isinstance(c, dict) else str(c)
                note = (c.get("note", c.get("reasoning", c.get("message", ""))) if isinstance(c, dict) else "")
                note_str = str(note)[:150] if note else ""
                if result in ("FAIL", "WARNING", "PARTIAL"):
                    await self._dispatch_debug("verifier", "check",
                        f"{result}: {name}" + (f" — {note_str}" if note_str else ""), verbosity=VERBOSITY_MED)

            await self._dispatch_debug("verifier", "domain_validator",
                f"Domain '{state.domain.value}' validator loaded", verbosity=VERBOSITY_HIGH)
            numerical = verdict.get("numerical_validation", {})
            if numerical:
                for key, val in numerical.items():
                    if isinstance(val, dict):
                        status = "FAIL" if val.get("valid") is False else "PASS"
                        await self._dispatch_debug("verifier", "numerical_check",
                            f"{status}: {key} — {str(val.get('message', ''))[:200]}", verbosity=VERBOSITY_MED)
            if verdict.get("_deep_verified"):
                first_conf = verdict.get("_first_confidence", 0)
                new_conf = verdict.get("confidence", 0)
                await self._dispatch_debug("verifier", "deep_diff",
                    f"Deep pass: confidence {first_conf:.0%} → {new_conf:.0%}, verdict → {verdict.get('verdict')}", verbosity=VERBOSITY_HIGH)

            logger.info(
                "verifier_done",
                iteration=state.iteration,
                verdict=verdict_data["verdict"],
                confidence=verdict_data["confidence"],
                checks=f"{checks_passed}/{total_checks}",
                fatal_flaws=fatal_count,
                usage_prompt=verif_usage["prompt_tokens"],
                usage_completion=verif_usage["completion_tokens"],
            )

            verdict_passed = verdict_data["verdict"] == "PASS"
            await self._dispatch_debug("fsm", "verdict",
                f"Verdict={verdict_data['verdict']} conf={verdict_data['confidence']:.0%} "
                f"checks={checks_passed}/{total_checks} fatal={fatal_count}")

            await self._persist_validation(
                hypothesis_db.id,
                verdict_passed,
                verdict_data["confidence"],
                verdict_data,
            )
            verdict["_reasoning"] = self.verifier.last_reasoning
            await self._persist_interaction(
                state, verdict, AgentRole.VERIFIER,
                InteractionDirection.VERIFIER_TO_PLANNER, hypothesis_db.id,
            )

            await self._dispatch_debug("memory", "record",
                f"Verifier episodic iter {state.iteration}: {verdict_data.get('mathematical_proof', '')[:120]}", verbosity=VERBOSITY_MED)

            await self.memory_store.record_memory(
                text=f"Verifier iteration {state.iteration}: verdict={verdict_data['verdict']} confidence={verdict_data['confidence']:.0%} flaws={len(verdict_data.get('fatal_flaws', []))}",
                session_id=session_id,
                agent_role="verifier",
                memory_type="episodic",
                iteration_turn=state.iteration,
            )

            if verdict_data.get("fatal_flaws"):
                state.prior_failures.append({
                    "iteration": state.iteration,
                    "hypothesis_summary": proposal.get("analysis_summary", ""),
                    "fatal_flaws": verdict_data["fatal_flaws"],
                    "reason": "Fatal — violates physical/chemical laws",
                })
                hypothesis_db.status = HypothesisStatus.REJECTED
                logger.info("hypothesis_status", iteration=state.iteration, status="REJECTED", flaws=len(verdict_data["fatal_flaws"]))
                await self._dispatch_debug("fsm", "rejected",
                    f"Iter {state.iteration}: {len(verdict_data['fatal_flaws'])} fatal flaws — "
                     + ", ".join(str(f)[:80] for f in verdict_data["fatal_flaws"][:3]))

                await self._dispatch_debug("memory", "failure_record",
                    f"Recording failure iter {state.iteration}: {state.prior_failures[-1].get('hypothesis_summary', '')[:200]}", verbosity=VERBOSITY_MED)

                await self.memory_store.record_failure(
                    text=f"Rejected hypothesis {state.iteration}: {hypothesis_statement[:200]} | Flaws: {', '.join(verdict_data['fatal_flaws'][:3])}",
                    session_id=session_id,
                    agent_role="verifier",
                    iteration=state.iteration,
                )
            elif verdict_passed:
                state.validated_results.append({
                    "iteration": state.iteration,
                    "hypothesis": hypothesis_data,
                    "verdict": verdict_data,
                })
                hypothesis_db.status = HypothesisStatus.VERIFIED
                logger.info("hypothesis_status", iteration=state.iteration, status="VERIFIED", confidence=verdict_data["confidence"])
                await self._dispatch_debug("fsm", "verified",
                    f"Iter {state.iteration}: PASS conf={verdict_data['confidence']:.0%}  total_validated={len(state.validated_results)}")
            else:
                hypothesis_db.status = HypothesisStatus.VALIDATING
                logger.info("hypothesis_status", iteration=state.iteration, status="VALIDATING")

            state.data_context = json.dumps({
                "last_verdict": verdict_data.get("verdict"),
                "last_confidence": verdict_data.get("confidence"),
                "fatal_flaws": verdict_data.get("fatal_flaws", []),
                "suggestions": verdict_data.get("suggestions", []),
                "corrected_values": verdict_data.get("corrected_values", {}),
                "numerical_validation": verdict_data.get("numerical_validation", {}),
                "checks_summary": verdict_data.get("mathematical_proof", "")[:500],
            })

            if len(state.prior_failures) >= 3:
                last_three_flaws = [
                    set(pf.get("fatal_flaws", []))
                    for pf in state.prior_failures[-3:]
                ]
                common = last_three_flaws[0] & last_three_flaws[1] & last_three_flaws[2]
                if common:
                    logger.warning("consecutive_identical_flaws", common=list(common))
                    await self._dispatch_debug("fsm", "forced_pivot",
                        f"3+ consecutive failures share: {', '.join(common)[:200]}  — SKIPPING planner, forcing PIVOT")
                    state.data_context += f"\n\n[SYSTEM: 3+ consecutive failures share flaws: {', '.join(common)}. Force PIVOT.]"
                    if live_state:
                        live_state.reasoning_text = "⚠ 3+ consecutive identical failures detected — forcing diversification"
                    current_directive = f"PIVOT REQUIRED: The last 3 approaches failed with the same flaws: {', '.join(common)}. Propose a fundamentally different approach — do NOT refine the previous method."
                    continue
                else:
                    await self._dispatch_debug("fsm", "failure_diversity",
                        f"{len(state.prior_failures)} consecutive failures but flaws are different — continuing normally", verbosity=VERBOSITY_HIGH)

            if (not revision_attempted
                    and verdict_data.get("verdict") == "PARTIAL"
                    and verdict_data.get("suggestions")
                    and not verdict_data.get("fatal_flaws")):
                await self._dispatch_debug("fsm", "revision",
                    f"PARTIAL verdict — attempting revision ({len(verdict_data['suggestions'])} suggestions)", verbosity=VERBOSITY_MED)
                revision_attempted = True
                logger.info("revision_attempt", iteration=state.iteration)
                try:
                    await self._display_step("proposer", "thinking", "Revising based on Verifier feedback...")
                    revised = await self._run_with_heartbeat("proposer", self.proposer.revise(
                        proposal, verdict_data["suggestions"], state.domain.value
                    ))
                    await self._dispatch_debug("fsm", "revision_proposer",
                        f"Revision proposer returned — verifier suggestions: {len(verdict_data['suggestions'])} items", verbosity=VERBOSITY_HIGH)
                    rev_usage = self._capture_usage(self.proposer)
                    state.total_usage = _merge_usage(state.total_usage, rev_usage)

                    revised_verdict = await self._run_with_heartbeat("verifier", self.verifier.verify(
                        hypothesis=revised.get("hypothesis", {}),
                        analysis_context=analysis_context,
                        domain=state.domain.value,
                        prior_failures=state.prior_failures,
                    ))
                    await self._dispatch_debug("fsm", "revision_verifier",
                        f"Post-revision verdict: {revised_verdict.get('verdict')} conf={revised_verdict.get('confidence', 0):.0%}", verbosity=VERBOSITY_HIGH)
                    rev_verif_usage = self._capture_usage(self.verifier)
                    state.total_usage = _merge_usage(state.total_usage, rev_verif_usage)

                    if revised_verdict.get("verdict") == "PASS":
                        logger.info("revision_accepted", iteration=state.iteration)
                        proposal = revised
                        verdict = revised_verdict
                        hyp = proposal.get("hypothesis", {})
                        hypothesis_statement = hyp.get("statement", "") if isinstance(hyp, dict) else str(hyp)
                        hypothesis_data = {
                            "domain": proposal.get("domain", state.domain.value),
                            "analysis_summary": proposal.get("analysis_summary", ""),
                            "hypothesis": hyp,
                            "features_detected": proposal.get("features_detected", []),
                            "execution_result": proposal.get("execution_result", {}),
                            "data_quality": proposal.get("data_quality", {}),
                        }
                        verdict_data = {
                            "verdict": revised_verdict.get("verdict", "UNKNOWN"),
                            "confidence": revised_verdict.get("confidence", 0.0),
                            "checks_performed": revised_verdict.get("checks_performed", []),
                            "mathematical_proof": revised_verdict.get("mathematical_proof", ""),
                            "corrected_values": revised_verdict.get("corrected_values", {}),
                            "fatal_flaws": revised_verdict.get("fatal_flaws", []),
                            "suggestions": revised_verdict.get("suggestions", []),
                            "numerical_validation": revised_verdict.get("numerical_validation", {}),
                        }
                        verif_usage = _merge_usage(verif_usage, rev_verif_usage)
                        state.hypotheses[-1] = hypothesis_data
                        hypothesis_db.content = hypothesis_data
                        await self._display_step("proposer", "done", "Revision accepted — hypothesis now passes!")
                        if live_state:
                            live_state.token_info = _status_bar(state.total_usage, state.started_at)
                            _refresh()
                    else:
                        logger.info("revision_rejected", iteration=state.iteration)
                        await self._display_step("proposer", "done", "Revision did not resolve all issues")
                except Exception as e:
                    logger.info("revision_attempt_failed", error=str(e))
                    await self._display_step("proposer", "error", f"Revision crashed: {e}")

            if live_state:
                live_state.reasoning_agent = "PLANNER"
                live_state.reasoning_text = f"Deciding next action for: {verdict_data['verdict']} ({verdict_data['confidence']:.0%})"
            await self._display_step("decision", "thinking", "Evaluating next action...")
            try:
                planner_decision = await self._run_with_heartbeat("planner", self.planner.plan(
                    user_query=query,
                    state={
                        "session_id": state.session_id,
                        "iteration": state.iteration,
                        "domain": state.domain.value,
                        "status": state.status.value,
                        "proposer_summary": proposal.get("analysis_summary", "")[:500],
                        "sandbox_success": proposal.get("execution_result", {}).get("success", False),
                        "sandbox_stdout": (proposal.get("execution_result", {}).get("stdout", "") or "")[:1500],
                           "prior_failures_count": len(state.prior_failures),
                        "validated_count": len(state.validated_results),
                    },
                    verdict=verdict_data,
                    hypotheses_history=state.hypotheses[-3:],
                ))
            except Exception as e:
                logger.error("planner_decision_failed", error=str(e))
                await self._display_step("decision", "error", str(e)[:80])
                planner_decision = {
                    "action": "fail",
                    "directive_to_proposer": current_directive,
                    "reasoning": f"Planner crashed: {e}",
                }

            dec_usage = self._capture_usage(self.planner)
            if live_state and self.planner.last_reasoning:
                live_state.reasoning_agent = "PLANNER"
                live_state.reasoning_text = self.planner.last_reasoning
                _refresh()
            await self._display_reasoning("PLANNER", self.planner.last_reasoning, verbosity=VERBOSITY_MED)
            if self.planner.last_reasoning:
                state.reasoning_log.append({"agent": "PLANNER", "iteration": state.iteration, "text": self.planner.last_reasoning})
            state.total_usage = _merge_usage(state.total_usage, dec_usage)

            action_raw = planner_decision.get("action", "continue")
            try:
                action = PlannerAction(action_raw.lower())
            except ValueError:
                logger.warning("planner_invalid_action", raw=action_raw)
                action = PlannerAction.CONTINUE
            directive = planner_decision.get("directive_to_proposer", current_directive)
            reason = planner_decision.get("reasoning", "")

            await self._persist_planner_decision(hypothesis_db.id, action, directive, reason)
            await self._persist_interaction(
                state, planner_decision, AgentRole.PLANNER,
                InteractionDirection.PLANNER_TO_PROPOSER, hypothesis_db.id,
            )

            await self._update_hypothesis_db(hypothesis_db)

            await self._dispatch_debug("memory", "record",
                f"Planner episodic iter {state.iteration}: action={action.value} reason={reason[:150]}", verbosity=VERBOSITY_MED)

            await self.memory_store.record_memory(
                text=f"Planner iteration {state.iteration}: action={action.value} reason={reason[:200]}",
                session_id=session_id,
                agent_role="planner",
                memory_type="episodic",
                iteration_turn=state.iteration,
            )

            reasoning_tag = _reasoning_tag(self.planner.last_reasoning)
            action_display = f"-> {action.value.upper()}: {reason[:120]}  {self._usage_summary(dec_usage)}{reasoning_tag}"
            await self._display_step("decision", "done", action_display)
            await self._dispatch_debug("fsm", "action",
                f"Planner → {action.value.upper()}  reason: {reason[:200]}")
            await self._dispatch_debug("planner", "directive",
                f"Next directive: {directive[:400]}", verbosity=VERBOSITY_MED)
            await self._dispatch_debug("planner", "state",
                f"Iteration {state.iteration}: failures={len(state.prior_failures)} "
                f"validated={len(state.validated_results)} hypotheses={len(state.hypotheses)} "
                f"domain={state.domain.value}", verbosity=VERBOSITY_MED)
            await self._dispatch_debug("planner", "action_detail",
                f"Action={action.value} — {state.status.value}", verbosity=VERBOSITY_MED)
            elapsed = time.time() - state.started_at
            cost = _calculate_cost(dec_usage)["total_cost"]
            await self._dispatch_debug("usage", "planner",
                f"PLANNER call: {dec_usage.get('total_tokens', 0)} tokens, ${cost:.5f}, {elapsed:.0f}s elapsed",
                verbosity=VERBOSITY_MED)
            if live_state:
                live_state.token_info = _status_bar(state.total_usage, state.started_at)
                _refresh()

            cost_total = _calculate_cost(state.total_usage)["total_cost"]
            logger.info(
                "planner_decision",
                iteration=state.iteration,
                action=action.value,
                directive=directive[:200],
                reason=reason[:200],
                usage_prompt=dec_usage["prompt_tokens"],
                usage_completion=dec_usage["completion_tokens"],
            )

            logger.info(
                "iteration_complete",
                iteration=state.iteration,
                action=action.value,
                verdict=verdict_data["verdict"],
                confidence=verdict_data["confidence"],
                checks=f"{checks_passed}/{total_checks}",
                hypotheses_n=len(state.hypotheses),
                rejected_n=len(state.prior_failures),
                cost_total=f"${cost_total:.5f}",
                tokens_total_k=f"{state.total_usage['total_tokens']/1000:.1f}K",
            )

            if action == PlannerAction.CONVERGE:
                state.status = SessionStatus.CONVERGED
                state.final_answer = _normalize_answer(planner_decision.get("final_answer", str(state.validated_results)))
                await self._update_session(state)
                await self._dispatch_debug("db", "session_update",
                    f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
                return await self._finalize(state)

            elif action == PlannerAction.FAIL:
                state.status = SessionStatus.FAILED
                await self._update_session(state)
                await self._dispatch_debug("db", "session_update",
                    f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
                return await self._finalize(state)

            elif action == PlannerAction.PIVOT:
                current_directive = directive
                logger.info("pivoting", reason=reason)

            elif action == PlannerAction.CONTINUE:
                current_directive = directive

            await self._update_session(state)
            await self._dispatch_debug("db", "session_update",
                f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)

        state.status = SessionStatus.MAX_ITERATIONS
        await self._update_session(state)
        await self._dispatch_debug("db", "session_update",
            f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
        logger.warning("max_iterations_reached", max=settings.max_iterations)
        return await self._finalize(state)

    async def _post_mortem(self, state: LoopState):
        try:
            await self.memory_store.summarize_and_record_lesson(
                session_id=state.session_id,
                hypotheses_history=state.hypotheses[-3:],
                final_status=state.status.value,
            )
        except Exception as e:
            logger.error("post_mortem_failed", error=str(e))

    async def _finalize(self, state: LoopState) -> dict:
        await self._post_mortem(state)
        return self._build_result(state)

    def _build_result(self, state: LoopState) -> dict:
        cost = _calculate_cost(state.total_usage)
        return {
            "session_id": state.session_id,
            "query": state.query,
            "domain": state.domain.value,
            "status": state.status.value,
            "iterations": state.iteration,
            "hypotheses_tested": len(state.hypotheses),
            "validated_count": len(state.validated_results),
            "failed_count": len(state.prior_failures),
            "final_answer": state.final_answer,
            "validated_results": state.validated_results,
            "failed_attempts": state.prior_failures,
            "token_usage": {
                "prompt_tokens": state.total_usage["prompt_tokens"],
                "cached_tokens": state.total_usage["cached_tokens"],
                "completion_tokens": state.total_usage["completion_tokens"],
                "total_tokens": state.total_usage["total_tokens"],
            },
            "cost": cost,
            "elapsed_seconds": time.time() - state.started_at,
            "reasoning_log": state.reasoning_log,
        }

    def _build_error_result(self, session_id: str, query: str, error: str) -> dict:
        return {
            "session_id": session_id,
            "query": query,
            "domain": "unknown",
            "status": "failed",
            "iterations": 0,
            "hypotheses_tested": 0,
            "validated_count": 0,
            "failed_count": 1,
            "final_answer": f"Fatal error during initialization: {error}",
            "validated_results": [],
            "failed_attempts": [{"reason": error}],
            "token_usage": {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "cost": _calculate_cost(_empty_usage()),
        }

    async def run_restore(self, query: str | None = None, **display_kwargs) -> dict:
        session_id, state = await self._load_most_recent_session()
        if session_id is None:
            return self._build_error_result("", query or "", "No restorable sessions found")

        self._wire_live_state(display_kwargs)
        await self._wire_memory(session_id)

        logger.info("restore_start", session_id=session_id, iteration=state.iteration, domain=state.domain.value)
        if query:
            state.query = query

        while state.iteration < settings.max_iterations:
            state.iteration += 1
            live_state = display_kwargs.get("_live_state")
            if live_state:
                live_state.iteration = state.iteration
                live_state.domain = state.domain.value.upper()

            await self._display_step("planner", "thinking", "Evaluating restored state...")
            await self._display_step("planner", "done",
                f"Domain: {state.domain.value.upper()} — Resumed at iteration {state.iteration}")

            current_directive = state.data_context or f"Continue the investigation for: {state.query}"
            restore_verdict = state.validated_results[-1].get("verdict", {}) if state.validated_results else {}
            try:
                planner_decision = await self._run_with_heartbeat("planner", self.planner.plan(
                    user_query=state.query,
                    state={"session_id": session_id, "iteration": state.iteration,
                           "domain": state.domain.value, "status": state.status.value,
                           "proposer_summary": "", "sandbox_success": False,
                           "sandbox_stdout": "", "prior_failures_count": len(state.prior_failures),
                           "validated_count": len(state.validated_results)},
                    verdict=restore_verdict or None,
                    hypotheses_history=state.hypotheses[-3:],
                ))
            except Exception as e:
                logger.error("restore_planner_failed", error=str(e))
                return self._build_error_result(session_id, state.query, f"Planner failed on restore: {e}")

            action_raw = planner_decision.get("action", "continue")
            try:
                action = PlannerAction(action_raw.lower())
            except ValueError:
                logger.warning("planner_invalid_action", raw=action_raw)
                action = PlannerAction.CONTINUE
            if action == PlannerAction.CONVERGE:
                state.status = SessionStatus.CONVERGED
                state.final_answer = planner_decision.get("final_answer", "")
                await self._update_session(state)
                await self._dispatch_debug("db", "session_update",
                    f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
                return await self._finalize(state)
            elif action == PlannerAction.FAIL:
                state.status = SessionStatus.FAILED
                await self._update_session(state)
                await self._dispatch_debug("db", "session_update",
                    f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
                return await self._finalize(state)

            current_directive = planner_decision.get("directive_to_proposer", current_directive)
            break

        return await self._run_loop(session_id, state, current_directive, display_kwargs)

    async def _load_most_recent_session(self) -> tuple[str | None, LoopState | None]:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            result = await db.execute(
                select(Session)
                .where(Session.status.in_([SessionStatus.ACTIVE, SessionStatus.MAX_ITERATIONS]))
                .order_by(desc(Session.updated_at))
                .limit(1)
            )
            session = result.scalars().first()
            if not session:
                return None, None

            hyp_result = await db.execute(
                select(Hypothesis)
                .where(Hypothesis.session_id == session.id)
                .order_by(Hypothesis.iteration)
            )
            hypotheses = hyp_result.scalars().all()

        prior_failures = []
        validated_results = []
        all_hyps = []
        total_usage = _empty_usage()

        for h in hypotheses:
            all_hyps.append(h.content)
            if h.status == HypothesisStatus.REJECTED:
                prior_failures.append({"iteration": h.iteration, "hypothesis_summary": str(h.content)[:200], "reason": "Previously rejected"})
            elif h.status == HypothesisStatus.VERIFIED:
                validated_results.append({"iteration": h.iteration, "hypothesis": h.content, "verdict": {}})

        state = LoopState(
            session_id=session.id,
            query=session.query,
            domain=session.domain,
            iteration=session.iteration,
            hypotheses=all_hyps,
            prior_failures=prior_failures,
            validated_results=validated_results,
            total_usage=total_usage,
        )
        return session.id, state

    async def _run_loop(self, session_id: str, state: LoopState, current_directive: str, display_kwargs: dict) -> dict:
        self._wire_live_state(display_kwargs)
        await self._wire_memory(session_id)
        live_state = display_kwargs.get("_live_state")
        live_refresh = display_kwargs.get("_live_refresh")

        def _refresh():
            if live_refresh:
                live_refresh()

        while state.iteration < settings.max_iterations:
            state.iteration += 1
            if live_state:
                live_state.iteration = state.iteration
                live_state.domain = state.domain.value.upper()
                _refresh()

            logger.info("iteration_start", iteration=state.iteration, session_id=session_id)

            if live_state:
                live_state.reasoning_agent = "PROPOSER"
                live_state.reasoning_text = f"Directive: {current_directive[:500]}"
            await self._display_step("proposer", "thinking", "Generating hypothesis...")
            try:
                proposal = await self._run_with_heartbeat("proposer", self.proposer.propose(
                    directive=current_directive,
                    domain=state.domain.value,
                    previous_attempts=state.prior_failures,
                    data_context=state.data_context,
                ))
            except Exception as e:
                logger.error("proposer_failed", error=str(e))
                await self._display_step("proposer", "error", str(e)[:80])
                state.prior_failures.append({"iteration": state.iteration, "hypothesis_summary": f"Proposer crashed: {e}", "reason": f"Proposer error: {e}"})
                current_directive = f"Previous proposer attempt failed with error: {e}. Try a different approach."
                await self._update_session(state)
                await self._dispatch_debug("db", "session_update",
                    f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
                continue

            prop_usage = self._capture_usage(self.proposer)
            if live_state and self.proposer.last_reasoning:
                live_state.reasoning_agent = "PROPOSER"
                live_state.reasoning_text = self.proposer.last_reasoning
                _refresh()
            await self._display_reasoning("PROPOSER", self.proposer.last_reasoning, verbosity=VERBOSITY_MED)
            if self.proposer.last_reasoning:
                state.reasoning_log.append({"agent": "PROPOSER", "iteration": state.iteration, "text": self.proposer.last_reasoning})
            state.total_usage = _merge_usage(state.total_usage, prop_usage)

            hyp = proposal.get("hypothesis", {})
            hypothesis_statement = hyp.get("statement", "") if isinstance(hyp, dict) else str(hyp)
            hypothesis_summary = hypothesis_statement[:150] or proposal.get("analysis_summary", "")[:150]
            display_detail = f"{hypothesis_summary}  {self._usage_summary(prop_usage)}"
            await self._display_step("proposer", "done", display_detail)

            await self._dispatch_debug("memory", "record",
                f"Proposer episodic iter {state.iteration}: {hypothesis_statement[:200]}", verbosity=VERBOSITY_MED)

            await self.memory_store.record_memory(
                text=f"Proposer iteration {state.iteration}: {hypothesis_statement}",
                session_id=session_id,
                agent_role="proposer",
                memory_type="episodic",
                iteration_turn=state.iteration,
            )
            if live_state:
                live_state.token_info = _status_bar(state.total_usage, state.started_at)
                _refresh()

            # Short-circuit: rest goes through existing methods would be duplication.
            # Instead, persist and loop as normal.
            hypothesis_data = {
                "domain": proposal.get("domain", state.domain.value),
                "analysis_summary": proposal.get("analysis_summary", ""),
                "hypothesis": hyp,
                "features_detected": proposal.get("features_detected", []),
                "execution_result": proposal.get("execution_result", {}),
                "data_quality": proposal.get("data_quality", {}),
            }
            state.hypotheses.append(hypothesis_data)

            hypothesis_db = await self._persist_hypothesis(state, hypothesis_data, AgentRole.PROPOSER, HypothesisStatus.PROPOSED)
            proposal["_reasoning"] = self.proposer.last_reasoning
            await self._persist_interaction(state, proposal, AgentRole.PROPOSER, InteractionDirection.PROPOSER_TO_VERIFIER, hypothesis_db.id)

            analysis_context = json.dumps({"summary": proposal.get("analysis_summary", ""), "features": proposal.get("features_detected", []), "execution": str(proposal.get("execution_result", {}))[:2000]})

            if live_state:
                live_state.reasoning_agent = "VERIFIER"
                live_state.reasoning_text = f"Validating: {hypothesis_statement[:500]}"
            await self._display_step("verifier", "thinking", "Validating hypothesis...")
            try:
                verdict = await self._run_with_heartbeat("verifier", self.verifier.verify(hypothesis=hyp, analysis_context=analysis_context, domain=state.domain.value, prior_failures=state.prior_failures))
            except Exception as e:
                logger.error("verifier_failed", error=str(e))
                verdict = {"verdict": "FAIL", "confidence": 0.0, "fatal_flaws": [f"Verifier crashed: {e}"], "checks_performed": [], "suggestions": []}

            verif_usage = self._capture_usage(self.verifier)
            if live_state and self.verifier.last_reasoning:
                live_state.reasoning_agent = "VERIFIER"
                live_state.reasoning_text = self.verifier.last_reasoning
                _refresh()
            await self._display_reasoning("VERIFIER", self.verifier.last_reasoning, verbosity=VERBOSITY_MED)
            if self.verifier.last_reasoning:
                state.reasoning_log.append({"agent": "VERIFIER", "iteration": state.iteration, "text": self.verifier.last_reasoning})
            state.total_usage = _merge_usage(state.total_usage, verif_usage)

            verdict_data = {
                "verdict": verdict.get("verdict", "UNKNOWN"),
                "confidence": verdict.get("confidence", 0.0),
                "checks_performed": verdict.get("checks_performed", []),
                "mathematical_proof": verdict.get("mathematical_proof", ""),
                "corrected_values": verdict.get("corrected_values", {}),
                "fatal_flaws": verdict.get("fatal_flaws", []),
                "suggestions": verdict.get("suggestions", []),
                "numerical_validation": verdict.get("numerical_validation", {}),
            }

            checks_passed = sum(1 for c in verdict_data["checks_performed"] if isinstance(c, dict) and c.get("result") == "PASS")
            total_checks = len(verdict_data["checks_performed"])
            verdict_display = f"Verdict: {verdict_data['verdict']} ({verdict_data['confidence']:.0%})  Checks: {checks_passed}/{total_checks}  {self._usage_summary(verif_usage)}"
            await self._display_step("verifier", "done", verdict_display)
            elapsed = time.time() - state.started_at
            cost = _calculate_cost(verif_usage)["total_cost"]
            await self._dispatch_debug("usage", "verifier",
                f"VERIFIER call: {verif_usage.get('total_tokens', 0)} tokens, ${cost:.5f}, {elapsed:.0f}s elapsed",
                verbosity=VERBOSITY_MED)
            if live_state:
                live_state.token_info = _status_bar(state.total_usage, state.started_at)
                _refresh()

            await self._persist_validation(hypothesis_db.id, verdict_data["verdict"] == "PASS", verdict_data["confidence"], verdict_data)
            verdict["_reasoning"] = self.verifier.last_reasoning
            await self._persist_interaction(state, verdict, AgentRole.VERIFIER, InteractionDirection.VERIFIER_TO_PLANNER, hypothesis_db.id)

            await self._dispatch_debug("memory", "record",
                f"Verifier episodic iter {state.iteration}: {verdict_data.get('mathematical_proof', '')[:120]}", verbosity=VERBOSITY_MED)

            await self.memory_store.record_memory(
                text=f"Verifier iteration {state.iteration}: verdict={verdict_data['verdict']} confidence={verdict_data['confidence']:.0%} flaws={len(verdict_data.get('fatal_flaws', []))}",
                session_id=session_id,
                agent_role="verifier",
                memory_type="episodic",
                iteration_turn=state.iteration,
            )

            if verdict_data.get("fatal_flaws"):
                state.prior_failures.append({"iteration": state.iteration, "hypothesis_summary": hypothesis_summary, "fatal_flaws": verdict_data["fatal_flaws"], "reason": "Fatal"})
                hypothesis_db.status = HypothesisStatus.REJECTED

                await self._dispatch_debug("memory", "failure_record",
                    f"Recording failure iter {state.iteration}: {state.prior_failures[-1].get('hypothesis_summary', '')[:200]}", verbosity=VERBOSITY_MED)

                await self.memory_store.record_failure(
                    text=f"Rejected hypothesis {state.iteration}: {hypothesis_summary[:200]} | Flaws: {', '.join(verdict_data['fatal_flaws'][:3])}",
                    session_id=session_id,
                    agent_role="verifier",
                    iteration=state.iteration,
                )
            elif verdict_data["verdict"] == "PASS":
                state.validated_results.append({"iteration": state.iteration, "hypothesis": hypothesis_data, "verdict": verdict_data})
                hypothesis_db.status = HypothesisStatus.VERIFIED
            else:
                hypothesis_db.status = HypothesisStatus.VALIDATING

            state.data_context = json.dumps({
                "last_verdict": verdict_data.get("verdict"),
                "last_confidence": verdict_data.get("confidence"),
                "fatal_flaws": verdict_data.get("fatal_flaws", []),
                "suggestions": verdict_data.get("suggestions", []),
                "corrected_values": verdict_data.get("corrected_values", {}),
            })

            await self._update_hypothesis_db(hypothesis_db)

            if live_state:
                live_state.reasoning_agent = "PLANNER"
                live_state.reasoning_text = f"Deciding next action for: {verdict_data['verdict']} ({verdict_data['confidence']:.0%})"
            await self._display_step("decision", "thinking", "Evaluating next action...")
            try:
                planner_decision = await self._run_with_heartbeat("planner", self.planner.plan(user_query=state.query, state={"session_id": session_id, "iteration": state.iteration, "domain": state.domain.value, "status": state.status.value, "proposer_summary": proposal.get("analysis_summary", "")[:500], "sandbox_success": proposal.get("execution_result", {}).get("success", False), "sandbox_stdout": (proposal.get("execution_result", {}).get("stdout", "") or "")[:1500], "prior_failures_count": len(state.prior_failures), "validated_count": len(state.validated_results)}, verdict=verdict_data, hypotheses_history=state.hypotheses[-3:]))
            except Exception as e:
                logger.error("planner_decision_failed", error=str(e))
                planner_decision = {"action": "fail", "directive_to_proposer": current_directive, "reasoning": f"Planner crashed: {e}"}

            dec_usage = self._capture_usage(self.planner)
            if live_state and self.planner.last_reasoning:
                live_state.reasoning_agent = "PLANNER"
                live_state.reasoning_text = self.planner.last_reasoning
                _refresh()
            await self._display_reasoning("PLANNER", self.planner.last_reasoning, verbosity=VERBOSITY_MED)
            if self.planner.last_reasoning:
                state.reasoning_log.append({"agent": "PLANNER", "iteration": state.iteration, "text": self.planner.last_reasoning})
            state.total_usage = _merge_usage(state.total_usage, dec_usage)

            action_raw = planner_decision.get("action", "continue")
            try:
                action = PlannerAction(action_raw.lower())
            except ValueError:
                logger.warning("planner_invalid_action", raw=action_raw)
                action = PlannerAction.CONTINUE
            directive = planner_decision.get("directive_to_proposer", current_directive)
            reason = planner_decision.get("reasoning", "")

            await self._persist_planner_decision(hypothesis_db.id, action, directive, reason)
            planner_decision["_reasoning"] = self.planner.last_reasoning
            await self._persist_interaction(state, planner_decision, AgentRole.PLANNER, InteractionDirection.PLANNER_TO_PROPOSER, hypothesis_db.id)

            await self._update_hypothesis_db(hypothesis_db)

            await self._dispatch_debug("memory", "record",
                f"Planner episodic iter {state.iteration}: action={action.value} reason={reason[:150]}", verbosity=VERBOSITY_MED)

            await self.memory_store.record_memory(
                text=f"Planner iteration {state.iteration}: action={action.value} reason={reason[:200]}",
                session_id=session_id,
                agent_role="planner",
                memory_type="episodic",
                iteration_turn=state.iteration,
            )

            reasoning_tag = _reasoning_tag(self.planner.last_reasoning)
            action_display = f"-> {action.value.upper()}: {reason[:120]}  {self._usage_summary(dec_usage)}{reasoning_tag}"
            await self._display_step("decision", "done", action_display)
            await self._dispatch_debug("fsm", "action",
                f"Planner → {action.value.upper()}  reason: {reason[:200]}")
            await self._dispatch_debug("planner", "directive",
                f"Next directive: {directive[:400]}", verbosity=VERBOSITY_MED)
            if live_state:
                live_state.token_info = _status_bar(state.total_usage, state.started_at)
                _refresh()

            cost_total = _calculate_cost(state.total_usage)["total_cost"]
            logger.info("planner_decision", iteration=state.iteration, action=action.value, directive=directive[:200], reason=reason[:200], usage_prompt=dec_usage["prompt_tokens"], usage_completion=dec_usage["completion_tokens"])
            logger.info("iteration_complete", iteration=state.iteration, action=action.value, verdict=verdict_data["verdict"], confidence=verdict_data["confidence"], checks=f"{checks_passed}/{total_checks}", hypotheses_n=len(state.hypotheses), rejected_n=len(state.prior_failures), cost_total=f"${cost_total:.5f}", tokens_total_k=f"{state.total_usage['total_tokens']/1000:.1f}K")

            if action == PlannerAction.CONVERGE:
                state.status = SessionStatus.CONVERGED
                state.final_answer = _normalize_answer(planner_decision.get("final_answer", ""))
                await self._update_session(state)
                await self._dispatch_debug("db", "session_update",
                    f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
                return await self._finalize(state)
            elif action == PlannerAction.FAIL:
                state.status = SessionStatus.FAILED
                await self._update_session(state)
                await self._dispatch_debug("db", "session_update",
                    f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
                return await self._finalize(state)
            elif action == PlannerAction.PIVOT:
                current_directive = directive
            elif action == PlannerAction.CONTINUE:
                current_directive = directive

            await self._update_session(state)
            await self._dispatch_debug("db", "session_update",
                f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)

        state.status = SessionStatus.MAX_ITERATIONS
        await self._update_session(state)
        await self._dispatch_debug("db", "session_update",
            f"Session {state.session_id[:8]}: iter={state.iteration} status={state.status.value}", verbosity=VERBOSITY_HIGH)
        return await self._finalize(state)

    async def _wire_memory(self, session_id: str):
        await self.memory_store.reset_for_session(session_id)
        shared_cache: dict[str, str] = {}
        for agent in (self.planner, self.proposer, self.verifier):
            agent.memory_store = self.memory_store
            agent.current_session_id = session_id
            agent._search_cache = shared_cache

    def _wire_live_state(self, display_kwargs: dict):
        live_state = display_kwargs.get("_live_state")
        if live_state:
            live_state.domain = "loading..."
            live_state.iteration = 0

    async def _persist_session(self, state: LoopState):
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            session = Session(
                id=state.session_id,
                query=state.query,
                domain=state.domain,
                status=state.status,
                iteration=state.iteration,
            )
            db.add(session)
            await db.commit()
            logger.debug("db_persist", table="sessions", id=session.id[:8])

    async def _update_session(self, state: LoopState):
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            session = await db.get(Session, state.session_id)
            if session:
                session.status = state.status
                session.iteration = state.iteration
                await db.commit()

    async def _persist_hypothesis(
        self, state: LoopState, data: dict, role: AgentRole, status: HypothesisStatus
    ) -> Hypothesis:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            hyp = Hypothesis(
                session_id=state.session_id,
                iteration=state.iteration,
                agent_role=role,
                content=data,
                status=status,
            )
            db.add(hyp)
            await db.commit()
            await db.refresh(hyp)
            logger.debug("db_persist", table="hypotheses", id=hyp.id[:8])
            return hyp

    async def _update_hypothesis_db(self, hyp: Hypothesis):
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            existing = await db.get(Hypothesis, hyp.id)
            if existing:
                existing.status = hyp.status
                existing.content = hyp.content
                await db.commit()

    async def _persist_interaction(
        self, state: LoopState, data: dict, role: AgentRole, direction: InteractionDirection, hypothesis_id: str
    ):
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            interaction = AgentInteraction(
                session_id=state.session_id,
                hypothesis_id=hypothesis_id,
                agent_role=role,
                direction=direction,
                content=data,
            )
            db.add(interaction)
            await db.commit()
            logger.debug("db_persist", table="agent_interactions", id=interaction.id[:8])

    async def _persist_validation(
        self, hypothesis_id: str, passed: bool, confidence: float, proof: dict
    ):
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            result = ValidationResult(
                hypothesis_id=hypothesis_id,
                passed=passed,
                confidence=confidence,
                proof=proof,
                constraints_applied=proof.get("checks_performed", []),
            )
            db.add(result)
            await db.commit()
            logger.debug("db_persist", table="validation_results", id=result.id[:8])

    async def _persist_planner_decision(
        self, hypothesis_id: str, action: PlannerAction, directive: str, reason: str
    ):
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            decision = PlannerDecision(
                hypothesis_id=hypothesis_id,
                action=action,
                directive=directive,
                reason=reason,
            )
            db.add(decision)
            await db.commit()
            logger.debug("db_persist", table="planner_decisions", id=decision.id[:8])


def _reasoning_tag(reasoning: str | None) -> str:
    if not reasoning:
        return ""
    preview = reasoning[:120].replace("\n", " ").strip()
    return f"\n[dim]↳ {preview}…[/dim]"


def _token_bar(usage: dict) -> str:
    p = usage.get("prompt_tokens", 0)
    c = usage.get("completion_tokens", 0)
    cached = usage.get("cached_tokens", 0)
    pct = (cached / p * 100) if p > 0 else 0
    cost = _calculate_cost(usage)["total_cost"]
    return f"💰 In:{_fmt(p)} Out:{_fmt(c)} Cache:{pct:.0f}% ${cost:.5f}"


def _status_bar(usage: dict, started_at: float | None = None) -> str:
    base = _token_bar(usage)
    if started_at:
        elapsed = time.time() - started_at
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        base = f"⏱ {mins}m{secs:02d}s | {base}"
    return base


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)
