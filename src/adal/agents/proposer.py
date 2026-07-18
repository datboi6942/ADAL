import json
from typing import Any

import structlog

from adal.agents.base import BaseAgent
from adal.config import settings
from adal.constants import VERBOSITY_HIGH, VERBOSITY_LOW, VERBOSITY_MED  # noqa: F401
from adal.execution.sandbox import run_script
from adal.prompts.proposer import (
    PROPOSER_SYSTEM_PROMPT,
    PROPOSER_USER_TEMPLATE,
    REVISE_SYSTEM_PROMPT,
    SELF_CRITIQUE_SYSTEM_PROMPT,
)
from adal.tools.web_search import TOOL_DEFINITIONS as WEB_TOOLS
from adal.tools.web_search import TOOL_EXECUTORS

logger = structlog.get_logger(__name__)


class Proposer(BaseAgent):
    role = "proposer"
    system_prompt = PROPOSER_SYSTEM_PROMPT

    def __init__(self, model: str | None = None, sub_model: str | None = None):
        super().__init__(model=model, sub_model=sub_model)
        self.tools = WEB_TOOLS
        self.tool_executors = dict(TOOL_EXECUTORS)
        self.gen_params = {
            "temperature": settings.proposer_temperature,
            "top_p": settings.proposer_top_p,
            "frequency_penalty": settings.proposer_frequency_penalty,
            "presence_penalty": settings.proposer_presence_penalty,
        }
        if settings.proposer_top_k > 0:
            self.gen_params["top_k"] = settings.proposer_top_k
        if settings.proposer_seed is not None:
            self.gen_params["seed"] = settings.proposer_seed

    async def _think_smart(self, context: dict, thinking_enabled: bool = True, model: str | None = None, max_tool_turns: int | None = None, timeout_seconds: float | None = None, json_mode: bool = False) -> str:
        if self.tools:
            return await self.think_with_tools(context, thinking_enabled=thinking_enabled, model=model, max_tool_turns=max_tool_turns or settings.proposer_max_tool_turns, timeout_seconds=timeout_seconds or settings.proposer_timeout, json_mode=json_mode)
        return await self.think_with_retry(context, json_mode=json_mode)

    async def propose(
        self,
        directive: str,
        domain: str,
        previous_attempts: list[dict],
        data_context: str = "",
    ) -> dict[str, Any]:
        context = {
            "directive": directive,
            "domain": domain,
            "previous_attempts": json.dumps(previous_attempts, indent=2)
            if previous_attempts else "None (first attempt)",
            "data_context": data_context or "No data provided. Generate or fetch appropriate data.",
        }

        self.log.info("proposer_starting", domain=domain)

        response = await self._think_smart(context, json_mode=True)
        result = self.parse_json_block(response)

        if "error" in result:
            self.log.error("proposer_parse_failed", error=result["error"])
            retry_context = {**context}
            retry_context["_retry_note"] = (
                "\n\n[SYSTEM NOTE: Your response was not valid JSON or was empty. "
                "You MUST output the complete JSON response exactly as specified. "
                "Include ALL required fields: domain, analysis_summary, hypothesis, python_script.]"
            )
            response = await self._think_smart(retry_context, json_mode=True)
            result = self.parse_json_block(response)

        if result.get("error"):
            self.log.error("proposer_fatal_parse_failure", error=result["error"])
            return {
                "domain": domain,
                "analysis_summary": "Failed to produce valid response",
                "hypothesis": {"statement": "No valid hypothesis — LLM response could not be parsed", "confidence": 0.0},
                "features_detected": [],
                "data_quality": {"notes": "LLM output unparseable"},
                "execution_result": {},
            }

        try:
            if previous_attempts:
                if self._debug_callback:
                    await self._debug_callback("proposer", "self_critique_start",
                        "Running self-critique checklist (stoichiometry, yield, thermo, workup, equipment, precursors, math, sensitivity)")
                critique = await self._self_critique(result, previous_attempts, domain)
                if critique:
                    result["_self_critique"] = critique
                    hyp = result.get("hypothesis", {})
                    if isinstance(hyp, dict):
                        adj = critique.get("confidence_adjustment", 0)
                        current_conf = hyp.get("confidence", 0)
                        if isinstance(current_conf, (int, float)):
                            hyp["confidence"] = max(0.0, min(1.0, current_conf + adj))
                    suggested_fix = critique.get("suggested_fix", "")
                    if suggested_fix:
                        existing_summary = result.get("analysis_summary", "")
                        result["analysis_summary"] = f"{existing_summary}\n\n[Self-Critique Correction]: {suggested_fix}"
                    issues = critique.get("issues_found", [])
                    if issues and isinstance(result.get("hypothesis"), dict):
                        hyp_notes = result["hypothesis"].get("notes", "")
                        result["hypothesis"]["notes"] = f"{hyp_notes}\n[Self-Critique flagged]: {'; '.join(issues[:5])}" if hyp_notes else f"[Self-Critique flagged]: {'; '.join(issues[:5])}"
                    if self._debug_callback:
                        for issue in issues[:8]:
                            await self._debug_callback("proposer", "critique_item",
                                f"Self-critique found: {issue}", verbosity=VERBOSITY_MED)
                        if not issues:
                            await self._debug_callback("proposer", "critique_clean",
                                "Self-critique: no issues found", verbosity=VERBOSITY_MED)
                        await self._debug_callback("proposer", "self_critique_done",
                            f"Found {len(issues)} issues, confidence adjustment {critique.get('confidence_adjustment', 0):+}, applied")
        except Exception as e:
            self.log.info("self_critique_skipped", error=str(e))

        if "python_script" in result and result["python_script"]:
            code = result["python_script"]
            if code.startswith("```python"):
                code = self.extract_code_block(code)

            try:
                execution = await run_script(code)
                result["execution_result"] = execution
                self.log.info(
                    "script_executed",
                    success=execution["success"],
                    returncode=execution["returncode"],
                )
                if self._debug_callback and result.get("python_script"):
                    debug_code = result["python_script"]
                    imports = [line.strip() for line in debug_code.split("\n") if line.strip().startswith("import ") or line.strip().startswith("from ")][:5]
                    debug_exec = result.get("execution_result", {})
                    await self._debug_callback("proposer", "script",
                        f"Script: {len(debug_code)} chars, imports={imports}, "
                        f"success={debug_exec.get('success', False)}, returncode={debug_exec.get('returncode', '?')}",
                        verbosity=VERBOSITY_MED)
                if self._debug_callback and not result.get("execution_result", {}).get("success", True):
                    error = result.get("execution_result", {}).get("error", result.get("execution_result", {}).get("stderr", ""))
                    await self._debug_callback("proposer", "script_error",
                        f"Script failed: {str(error)[:300]}", verbosity=VERBOSITY_MED)
            except Exception as e:
                result["execution_result"] = {"success": False, "error": str(e)}
                self.log.error("script_execution_failed", error=str(e))

        return result

    def build_prompt(self, context: dict) -> str:
        base = PROPOSER_USER_TEMPLATE.format(
            _session_memory=context.get("_session_memory", ""),
            directive=context["directive"],
            domain=context["domain"],
            previous_attempts=context["previous_attempts"],
            data_context=context["data_context"],
        )
        retry = context.get("_retry_note", "")
        return base + retry if retry else base

    async def _self_critique(self, hypothesis: dict, previous_attempts: list[dict], domain: str) -> dict | None:
        prior_failures = []
        for pa in previous_attempts[-3:]:
            flaws = pa.get("fatal_flaws", [])
            if flaws:
                prior_failures.append({
                    "statement": pa.get("hypothesis_summary", ""),
                    "fatal_flaws": flaws,
                    "suggestions": pa.get("suggestions", []),
                })

        hyp = hypothesis.get("hypothesis", hypothesis)
        hype_json = json.dumps(hyp, indent=2, default=str)
        failures_context = json.dumps(prior_failures, indent=2) if prior_failures else "None (first attempt)"

        critique_prompt = (
            "Review the hypothesis below against the checklist in your system prompt. "
            "Use tools to verify claims against real published data.\n\n"
            f"Domain: {domain}\n\n"
            "## Prior Failures to Avoid\n"
            f"{failures_context}\n\n"
            "## Hypothesis to Review\n"
            f"{hype_json}\n\n"
            "Return ONLY a JSON object:\n"
            '{"issues_found": ["issue 1", ...], "suggested_fix": "brief fix note", "confidence_adjustment": -0.1}\n'
            'If no issues found, return {"issues_found": [], "confidence_adjustment": 0}'
        )

        context = {
            "directive": critique_prompt,
            "domain": domain,
            "previous_attempts": "[]",
            "data_context": "",
        }
        old_system_prompt = self.system_prompt
        self.system_prompt = SELF_CRITIQUE_SYSTEM_PROMPT
        try:
            response = await self._think_smart(context, thinking_enabled=False, model=self.sub_model, max_tool_turns=settings.self_critique_max_tool_turns, timeout_seconds=settings.self_critique_timeout, json_mode=True)
        finally:
            self.system_prompt = old_system_prompt
        return self.parse_json_block(response)

    async def revise(
        self,
        original_result: dict,
        verifier_suggestions: list[str],
        domain: str,
    ) -> dict:
        hyp = original_result.get("hypothesis", original_result)
        hyp_json = json.dumps(hyp, indent=2, default=str)
        suggestions_json = json.dumps(verifier_suggestions, indent=2)

        revision_prompt = (
            "Fix ONLY the specific issues listed below. Keep everything else "
            "the same — do not rewrite unrelated parts of the hypothesis.\n\n"
            f"## Original Hypothesis\n{hyp_json}\n\n"
            f"## Verifier Feedback — Fix These Exact Issues\n{suggestions_json}\n\n"
            "Return the COMPLETE revised hypothesis in the original JSON format "
            "(including domain, analysis_summary, hypothesis, python_script, "
            "features_detected, data_quality fields). Update ONLY the parts "
            "affected by the Verifier's feedback."
        )

        context = {
            "directive": revision_prompt,
            "domain": domain,
            "previous_attempts": json.dumps([
                {"suggestions": verifier_suggestions}
            ]),
            "data_context": "",
        }

        self.log.info("proposer_revising", suggestions_count=len(verifier_suggestions))
        old_system_prompt = self.system_prompt
        self.system_prompt = REVISE_SYSTEM_PROMPT
        try:
            response = await self._think_smart(context, thinking_enabled=False, model=self.sub_model, max_tool_turns=settings.revise_max_tool_turns, timeout_seconds=settings.revise_timeout, json_mode=True)
        finally:
            self.system_prompt = old_system_prompt
        result = self.parse_json_block(response)

        if result.get("error"):
            self.log.info("revision_parse_failed", error=result["error"])
            if self._debug_callback:
                await self._debug_callback("proposer", "revise_fail",
                    f"Revision parse failed: {result['error']}", verbosity=VERBOSITY_MED)
            return original_result

        if self._debug_callback and "error" not in (result or {}):
            await self._debug_callback("proposer", "revise_success",
                "Revision accepted — returning corrected hypothesis", verbosity=VERBOSITY_MED)

        if "python_script" in result and result["python_script"]:
            code = result["python_script"]
            if code.startswith("```python"):
                code = self.extract_code_block(code)
            try:
                result["execution_result"] = await run_script(code)
                self.log.info(
                    "revision_script_executed",
                    success=result["execution_result"]["success"],
                )
            except Exception as e:
                result["execution_result"] = {"success": False, "error": str(e)}

        return result
