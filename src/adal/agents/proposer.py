import json
from typing import Any

import structlog

from adal.agents.base import BaseAgent
from adal.config import settings
from adal.execution.sandbox import run_script
from adal.prompts.proposer import PROPOSER_SYSTEM_PROMPT, PROPOSER_USER_TEMPLATE
from adal.tools.web_search import TOOL_DEFINITIONS as WEB_TOOLS
from adal.tools.web_search import TOOL_EXECUTORS

logger = structlog.get_logger(__name__)


class Proposer(BaseAgent):
    role = "proposer"
    system_prompt = PROPOSER_SYSTEM_PROMPT

    def __init__(self, model: str | None = None):
        super().__init__(model=model)
        self.tools = WEB_TOOLS
        self.tool_executors = TOOL_EXECUTORS
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

    async def _think_smart(self, context: dict) -> str:
        if self.tools:
            return await self.think_with_tools(context)
        return await self.think_with_retry(context)

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

        response = await self._think_smart(context)
        result = self.parse_json_block(response)

        if "error" in result:
            self.log.error("proposer_parse_failed", error=result["error"])
            retry_context = {**context}
            retry_context["_retry_note"] = (
                "\n\n[SYSTEM NOTE: Your response was not valid JSON or was empty. "
                "You MUST output the complete JSON response exactly as specified. "
                "Include ALL required fields: domain, analysis_summary, hypothesis, python_script.]"
            )
            response = await self._think_smart(retry_context)
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

        if previous_attempts:
            try:
                critique = await self._self_critique(result, previous_attempts, domain)
                if critique:
                    result["_self_critique"] = critique
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

        if not prior_failures:
            return None

        hyp = hypothesis.get("hypothesis", hypothesis)
        hype_json = json.dumps(hyp, indent=2, default=str)

        critique_prompt = (
            "You are an internal quality-control critic. Review this hypothesis "
            "for basic errors BEFORE it is submitted to the Verifier.\n\n"
            f"Domain: {domain}\n\n"
            "## Prior Failures to Avoid\n"
            f"{json.dumps(prior_failures, indent=2)}\n\n"
            "## Your Hypothesis to Review\n"
            f"{hype_json}\n\n"
            "## Review Checklist\n"
            "1. Stoichiometry: do reagent moles/ratios and quantities balance?\n"
            "2. Yield: is claimed yield in a realistic range for this reaction class?\n"
            "3. Thermodynamics/feasibility: is the reaction energetically plausible?\n"
            "4. Workup: can the product be isolated with basic mid-1900s equipment?\n"
            "5. Equipment: does the procedure avoid modern equipment (rotovap, HPLC, etc)?\n"
            "6. Math: are ALL calculations arithmetically correct?\n\n"
            "Return ONLY a JSON object:\n"
            '{"issues_found": ["issue 1", ...], "suggested_fix": "brief fix note", "confidence_adjustment": -0.1}\n'
            'If no issues found, return {"issues_found": [], "confidence_adjustment": 0}'
        )

        old_tools = self.tools
        old_executors = self.tool_executors
        try:
            self.tools = []
            self.tool_executors = {}
            context = {"directive": critique_prompt, "domain": domain,
                       "previous_attempts": "[]", "data_context": ""}
            response = await self.think(context, max_tokens=1024)
            return self.parse_json_block(response)
        except Exception:
            return None
        finally:
            self.tools = old_tools
            self.tool_executors = old_executors
