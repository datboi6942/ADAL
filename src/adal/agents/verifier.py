import importlib
import json
from typing import Any

import structlog

from adal.agents.base import BaseAgent
from adal.config import settings
from adal.constants import VERBOSITY_HIGH, VERBOSITY_LOW, VERBOSITY_MED  # noqa: F401
from adal.prompts.verifier import (
    DEEP_VERIFICATION_SYSTEM_PROMPT,
    DEEP_VERIFICATION_TEMPLATE,
    VERIFIER_SYSTEM_PROMPT,
    VERIFIER_USER_TEMPLATE,
)
from adal.tools.web_search import TOOL_DEFINITIONS as WEB_TOOLS
from adal.tools.web_search import TOOL_EXECUTORS

logger = structlog.get_logger(__name__)

DOMAIN_VALIDATORS = {
    "astrophysics": "adal.domains.astrophysics.validators",
    "chemistry": "adal.domains.chemistry.validators",
    "physics": "adal.domains.physics.validators",
    "particle_nuclear": "adal.domains.particle_nuclear.validators",
}


class Verifier(BaseAgent):
    role = "verifier"
    system_prompt = VERIFIER_SYSTEM_PROMPT

    def __init__(self, model: str | None = None, sub_model: str | None = None):
        super().__init__(model=model, sub_model=sub_model)
        self.tools = WEB_TOOLS
        self.tool_executors = dict(TOOL_EXECUTORS)
        self.gen_params = {
            "temperature": settings.verifier_temperature,
            "top_p": settings.verifier_top_p,
            "frequency_penalty": settings.verifier_frequency_penalty,
            "presence_penalty": settings.verifier_presence_penalty,
        }
        if settings.verifier_top_k > 0:
            self.gen_params["top_k"] = settings.verifier_top_k
        if settings.verifier_seed is not None:
            self.gen_params["seed"] = settings.verifier_seed

    async def _think_smart(self, context: dict, thinking_enabled: bool = True, model: str | None = None, max_tool_turns: int | None = None, timeout_seconds: float | None = None, json_mode: bool = False) -> str:
        if self.tools:
            return await self.think_with_tools(context, max_tokens=49152, thinking_enabled=thinking_enabled, model=model, max_tool_turns=max_tool_turns or settings.verifier_max_tool_turns, timeout_seconds=timeout_seconds or settings.verifier_timeout, json_mode=json_mode)
        return await self.think_with_retry(context, max_tokens=49152, json_mode=json_mode)

    async def verify(
        self,
        hypothesis: dict,
        analysis_context: str,
        domain: str,
        prior_failures: list[dict],
    ) -> dict[str, Any]:
        domain_constraints = await self._load_domain_constraints(domain)

        numerical_results = await self._run_numerical_validation(hypothesis, domain)
        if domain == "chemistry":
            real_world = await self._validate_chemistry_real_world(hypothesis)
            if numerical_results:
                numerical_results.update(real_world)
            else:
                numerical_results = real_world

        if self._debug_callback:
            await self._debug_callback("verifier", "pre_checks",
                f"Running pre-LLM deterministic checks ({len(numerical_results or {})} validators)")

        pre_flaws = []
        if numerical_results:
            for key, check in numerical_results.items():
                if isinstance(check, dict) and check.get("valid") is False:
                    pre_flaws.append(f"{key}: {check.get('message', 'failed')}")
            if pre_flaws:
                self.log.info("pre_llm_fatal_flaws_found", flaws=pre_flaws)
                if self._debug_callback:
                    await self._debug_callback("verifier", "pre_checks_failed",
                        f"{len(pre_flaws)} fatal: {'; '.join(pre_flaws[:4])}")
                return {
                    "verdict": "FAIL",
                    "confidence": 0.95,
                    "checks_performed": [{"check_name": k, "result": "FAIL", "reasoning": v.get("message", "")} for k, v in (numerical_results or {}).items() if isinstance(v, dict)],
                    "mathematical_proof": f"Pre-LLM deterministic checks found fatal flaws: {'; '.join(pre_flaws)}",
                    "corrected_values": {},
                    "fatal_flaws": pre_flaws,
                    "suggestions": [f"Fix {f.split(':')[0]}" for f in pre_flaws],
                    "numerical_validation": numerical_results,
                }

        if self._debug_callback:
            await self._debug_callback("verifier", "pre_checks_passed",
                f"All {len(numerical_results or {})} pre-LLM checks passed — invoking LLM verification")

        context = {
            "hypothesis_json": json.dumps(hypothesis, indent=2),
            "analysis_context": analysis_context,
            "domain_constraints": domain_constraints,
            "prior_failures": json.dumps(prior_failures, indent=2) if prior_failures else "None",
        }

        self.log.info("verifier_starting", domain=domain)
        response = await self._think_smart(context, json_mode=True)
        result = self.parse_json_block(response)

        if "error" in result:
            self.log.error("verifier_parse_failed", error=result["error"])
            retry_context = {**context}
            retry_context["_retry_note"] = (
                "\n\n[SYSTEM NOTE: Your previous response was not valid JSON or was empty. "
                "You MUST output the complete JSON response with ALL required fields: "
                "verdict, confidence, checks_performed, mathematical_proof, fatal_flaws, suggestions.]"
            )
            response = await self._think_smart(retry_context, json_mode=True)
            result = self.parse_json_block(response)

        if result.get("error"):
            self.log.error("verifier_fatal_parse_failure", error=result["error"])
            return {
                "verdict": "INCONCLUSIVE",
                "confidence": 0.0,
                "checks_performed": [],
                "mathematical_proof": f"LLM failed to produce valid verdict: {result['error']}",
                "corrected_values": {},
                "fatal_flaws": [],
                "suggestions": ["LLM output unparseable — retry with different hypothesis"],
                "should_retry": True,
            }

        if numerical_results:
            result["numerical_validation"] = numerical_results

        if self._should_deep_verify(result):
            borderline_count = sum(
                1 for c in result.get("checks_performed", [])
                if isinstance(c, dict) and c.get("result") in ("WARNING", "PARTIAL")
            )
            if self._debug_callback:
                await self._debug_callback("verifier", "deep_start",
                    f"Deep verification triggered — {borderline_count} borderline checks, confidence={result.get('confidence', 0):.0%}")
            deep_result = await self._deep_verification_pass(
                hypothesis=hypothesis,
                analysis_context=analysis_context,
                domain=domain,
                first_pass_result=result,
            )
            if deep_result:
                result = self._merge_verification_results(result, deep_result)
                if self._debug_callback:
                    await self._debug_callback("verifier", "deep_done",
                        f"Deep verification merged — new verdict: {result.get('verdict')} conf={result.get('confidence', 0):.0%}")
                self.log.info(
                    "deep_verification_complete",
                    verdict=result.get("verdict"),
                    confidence=result.get("confidence"),
                )

        self.log.info(
            "verifier_done",
            verdict=result.get("verdict", "UNKNOWN"),
            confidence=result.get("confidence", 0.0),
        )
        return result

    def build_prompt(self, context: dict) -> str:
        if context.get("_deep_verification"):
            base = DEEP_VERIFICATION_TEMPLATE.format(
                _session_memory=context.get("_session_memory", ""),
                hypothesis_json=context.get("hypothesis_json", ""),
                analysis_context=context.get("analysis_context", ""),
                first_pass_verdict=context.get("first_pass_verdict", ""),
                first_pass_confidence=context.get("first_pass_confidence", 0.0),
                borderline_checks=context.get("borderline_checks", "[]"),
                fatal_flaws=context.get("fatal_flaws", "[]"),
            )
        else:
            base = VERIFIER_USER_TEMPLATE.format(
                _session_memory=context.get("_session_memory", ""),
                hypothesis_json=context["hypothesis_json"],
                analysis_context=context["analysis_context"],
                domain_constraints=context["domain_constraints"],
                prior_failures=context["prior_failures"],
            )
        retry = context.get("_retry_note", "")
        return base + retry if retry else base

    def _should_deep_verify(self, result: dict) -> bool:
        verdict = result.get("verdict", "UNKNOWN")
        confidence = result.get("confidence", 1.0)
        fatal_flaws = result.get("fatal_flaws", [])

        if verdict == "PASS" and confidence >= 0.85:
            return False
        if verdict == "FAIL" and fatal_flaws:
            return False
        if verdict == "INCONCLUSIVE":
            return False

        checks = result.get("checks_performed", [])
        borderline_count = sum(
            1 for c in checks
            if isinstance(c, dict) and c.get("result") in ("WARNING", "PARTIAL")
        )

        if borderline_count == 0 and confidence >= 0.8:
            return False

        return True

    async def _deep_verification_pass(
        self,
        hypothesis: dict,
        analysis_context: str,
        domain: str,
        first_pass_result: dict,
    ) -> dict | None:
        checks = first_pass_result.get("checks_performed", [])
        borderline = [
            c for c in checks
            if isinstance(c, dict) and c.get("result") in ("WARNING", "PARTIAL")
        ]

        context = {
            "_deep_verification": True,
            "hypothesis_json": json.dumps(hypothesis, indent=2),
            "analysis_context": analysis_context,
            "domain": domain,
            "first_pass_verdict": first_pass_result.get("verdict", "UNKNOWN"),
            "first_pass_confidence": first_pass_result.get("confidence", 0.0),
            "borderline_checks": json.dumps(borderline, indent=2),
            "fatal_flaws": json.dumps(first_pass_result.get("fatal_flaws", []), indent=2),
        }

        old_system_prompt = self.system_prompt
        self.system_prompt = DEEP_VERIFICATION_SYSTEM_PROMPT
        try:
            self.log.info("deep_verification_starting", borderline_count=len(borderline))
            response = await self._think_smart(context, thinking_enabled=False, model=self.sub_model, max_tool_turns=settings.deep_verify_max_tool_turns, timeout_seconds=settings.deep_verify_timeout, json_mode=True)
            result = self.parse_json_block(response)
            if self._debug_callback and "error" not in result:
                deep_checks = result.get("checks_performed", [])
                for c in deep_checks[:8]:
                    if isinstance(c, dict):
                        name = c.get("check", c.get("check_name", "?"))
                        res = c.get("result", "?")
                        note = str(c.get("reasoning", c.get("note", "")))[:150]
                        await self._debug_callback("verifier", "deep_check",
                            f"Deep: {res} {name}" + (f" — {note}" if note else ""), verbosity=VERBOSITY_MED)
            return result if "error" not in result else None
        except Exception as e:
            self.log.info("deep_verification_failed", error=str(e))
            return None
        finally:
            self.system_prompt = old_system_prompt

    def _merge_verification_results(self, first: dict, deep: dict) -> dict:
        merged = {**first}

        deep_checks = deep.get("checks_performed", [])
        if deep_checks:
            existing = {}
            for c in merged.get("checks_performed", []):
                if isinstance(c, dict):
                    key = c.get("check_name") or c.get("check") or c.get("name")
                    if key:
                        existing[key] = c
            for check in deep_checks:
                if isinstance(check, dict):
                    key = check.get("check_name") or check.get("check") or check.get("name")
                    if key and check.get("result") in ("PASS", "FAIL"):
                        existing[key] = check
            merged["checks_performed"] = list(existing.values())

        deep_flaws = deep.get("fatal_flaws", [])
        if deep_flaws:
            existing_flaws = set(merged.get("fatal_flaws", []))
            for flaw in deep_flaws:
                if flaw not in existing_flaws:
                    merged.setdefault("fatal_flaws", []).append(flaw)

        deep_verdict = deep.get("verdict")
        deep_confidence = deep.get("confidence")
        if deep_verdict and deep_confidence is not None:
            if deep_verdict in ("PASS", "FAIL"):
                merged["verdict"] = deep_verdict
                merged["confidence"] = max(
                    merged.get("confidence", 0.0), deep_confidence
                )

        deep_suggestions = deep.get("suggestions", [])
        if deep_suggestions:
            existing_suggestions = set(merged.get("suggestions", []))
            for s in deep_suggestions:
                if s not in existing_suggestions:
                    merged.setdefault("suggestions", []).append(s)

        if deep.get("mathematical_proof"):
            merged["mathematical_proof"] = (
                merged.get("mathematical_proof", "")
                + "\n\n## Deep Verification\n"
                + deep["mathematical_proof"]
            )

        return merged

    async def _load_domain_constraints(self, domain: str) -> str:
        if self._debug_callback:
            await self._debug_callback("verifier", "domain_load",
                f"Loading validators for domain: {domain}", verbosity=VERBOSITY_MED)
        module_path = DOMAIN_VALIDATORS.get(domain)
        if not module_path:
            return f"No validators found for domain: {domain}"

        try:
            module = importlib.import_module(module_path)
            functions = [name for name in dir(module) if name.startswith("validate_") and callable(getattr(module, name))]
            if self._debug_callback:
                await self._debug_callback("verifier", "domain_validators",
                    f"Loaded {len(functions)} validators: {functions}", verbosity=VERBOSITY_MED)
            return f"Available validation functions in {domain}: {json.dumps(functions)}\nModule: {module_path}"
        except ImportError:
            if self._debug_callback:
                await self._debug_callback("verifier", "domain_load_fail",
                    f"Failed to load validators for {domain}: module not found", verbosity=VERBOSITY_MED)
            return f"Validator module {module_path} not available"

    async def _run_numerical_validation(self, hypothesis: dict, domain: str) -> dict | None:
        predicted = hypothesis.get("hypothesis", hypothesis).get("predicted_values", {})
        if not predicted:
            if self._debug_callback:
                await self._debug_callback("verifier", "numerical_skip",
                    "No predicted_values in hypothesis — skipping numerical validation", verbosity=VERBOSITY_MED)
            return None

        results = {}

        if domain == "astrophysics":
            results.update(self._validate_astrophysics(predicted))
        elif domain == "chemistry":
            results.update(self._validate_chemistry(predicted))
            results.update(await self._validate_chemistry_real_world(hypothesis))
        elif domain == "physics":
            results.update(self._validate_physics(predicted))
        elif domain == "particle_nuclear":
            results.update(self._validate_particle_nuclear(predicted))

        if results and self._debug_callback:
            for key, val in results.items():
                status = "FAIL" if isinstance(val, dict) and val.get("valid") is False else "PASS"
                detail = str(val.get("message", val))[:150] if isinstance(val, dict) else str(val)[:150]
                await self._debug_callback("verifier", "numerical",
                    f"{status}: {key} — {detail}", verbosity=VERBOSITY_MED)

        return results if results else None

    async def _validate_chemistry_real_world(self, hypothesis: dict) -> dict:
        results = {}
        hyp = hypothesis.get("hypothesis", hypothesis)
        statement = hyp.get("statement", "").lower()
        predicted = hyp.get("predicted_values", {})

        claimed_yield = predicted.get("yield_percent") or hyp.get("expected_yield_percent")
        if claimed_yield:
            try:
                y = float(claimed_yield)
                reaction_type = "amination" if "amination" in statement else "general"
                typical_ranges = {"amination": (60, 88), "general": (50, 95)}
                lo, hi = typical_ranges.get(reaction_type, (50, 95))
                if y > hi + 5:
                    results["yield_realism"] = {
                        "valid": False,
                        "message": f"Claimed yield {y}% exceeds typical range for this reaction class ({lo}-{hi}%). Requires strong literature precedent.",
                    }
                elif y < lo - 5:
                    results["yield_realism"] = {
                        "valid": True,
                        "message": f"Yield {y}% is conservative — realistic for first attempt.",
                    }
                else:
                    results["yield_realism"] = {
                        "valid": True,
                        "message": f"Yield {y}% is within expected range ({lo}-{hi}%).",
                    }
            except (ValueError, TypeError):
                if self._debug_callback:
                    await self._debug_callback("verifier", "yield_parse_error",
                        f"Could not parse yield value: {claimed_yield}", verbosity=VERBOSITY_HIGH)
                pass

        if self._debug_callback:
            status = "FAIL" if not results.get("yield_realism", {}).get("valid", True) else "PASS"
            msg = results.get("yield_realism", {}).get("message", "yield check skipped")
            await self._debug_callback("verifier", "yield_check",
                f"{status}: {msg}", verbosity=VERBOSITY_MED)

        workup_search_text = statement
        for key in ("workup_procedure", "synthesis_procedure", "isolation", "purification", "procedure"):
            val = hyp.get(key, "")
            if isinstance(val, str) and val.strip():
                workup_search_text += " " + val.lower()

        has_workup = any(
            phrase in workup_search_text
            for phrase in ("workup", "work-up", "extract", "filter", "dry", "recrystallize",
                           "chromatography", "purif", "isolat", "wash", "brine", "aqueous",
                           "organic layer", "separatory")
        )
        if has_workup:
            results["workup_described"] = {"valid": True, "message": "Workup/isolation procedure described."}
        else:
            results["workup_described"] = {
                "valid": False,
                "message": "No workup or isolation procedure described. Hypothesis is incomplete without product isolation steps.",
            }

        if self._debug_callback:
            status = "FAIL" if not results.get("workup_described", {}).get("valid", True) else "PASS"
            await self._debug_callback("verifier", "workup_check",
                f"{status}: workup_described", verbosity=VERBOSITY_MED)

        return results

    def _validate_astrophysics(self, values: dict) -> dict:
        from adal.domains.astrophysics.validators import (
            is_transit_depth_physical,
            kepler_third_law,
            validate_stellar_mass_from_radius,
        )

        results = {}
        if "period_days" in values and "stellar_mass_solar" in values:
            a = kepler_third_law(values["period_days"], values["stellar_mass_solar"])
            results["semi_major_axis_au"] = round(a, 6)

        if "transit_depth" in values:
            ok, msg = is_transit_depth_physical(values["transit_depth"])
            results["transit_depth_physical"] = {"valid": ok, "message": msg}

        if "stellar_mass" in values and "stellar_radius" in values:
            ok, msg = validate_stellar_mass_from_radius(values["stellar_mass"], values["stellar_radius"])
            results["mass_radius_relation"] = {"valid": ok, "message": msg}

        return results

    def _validate_chemistry(self, values: dict) -> dict:
        from adal.domains.chemistry.validators import (
            estimate_reaction_enthalpy,
            validate_reaction_thermodynamics,
        )

        results = {}
        if "delta_h_kcal" in values and "delta_s_cal" in values:
            ok, msg, dg = validate_reaction_thermodynamics(values["delta_h_kcal"], values["delta_s_cal"])
            results["thermodynamics"] = {"valid": ok, "message": msg, "delta_g_kcal": round(dg, 2)}

        if "bonds_broken" in values and "bonds_formed" in values:
            dh = estimate_reaction_enthalpy(values["bonds_broken"], values["bonds_formed"])
            results["estimated_delta_h_kcal"] = round(dh, 2)

        return results

    def _validate_physics(self, values: dict) -> dict:
        from adal.domains.physics.validators import (
            validate_energy_conservation,
            validate_ideal_gas_law,
        )

        results = {}
        if "e_initial" in values and "e_final" in values:
            ok, msg = validate_energy_conservation(values["e_initial"], values["e_final"])
            results["energy_conservation"] = {"valid": ok, "message": msg}

        if all(k in values for k in ("pressure_pa", "volume_m3", "n_moles", "temperature_k")):
            ok, msg = validate_ideal_gas_law(
                values["pressure_pa"], values["volume_m3"], values["n_moles"], values["temperature_k"]
            )
            results["ideal_gas_law"] = {"valid": ok, "message": msg}

        return results

    def _validate_particle_nuclear(self, values: dict) -> dict:
        from adal.domains.particle_nuclear.validators import (
            validate_decay_kinematics,
            validate_electric_charge_conservation,
        )

        results = {}
        if "initial_charges" in values and "final_charges" in values:
            ok, msg = validate_electric_charge_conservation(values["initial_charges"], values["final_charges"])
            results["charge_conservation"] = {"valid": ok, "message": msg}

        if "parent_mass_mev" in values and "daughter_masses_mev" in values:
            ok, msg = validate_decay_kinematics(values["parent_mass_mev"], values["daughter_masses_mev"])
            results["decay_kinematics"] = {"valid": ok, "message": msg}

        return results
