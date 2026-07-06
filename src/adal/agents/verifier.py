import importlib
import json
from typing import Any

import structlog

from adal.agents.base import BaseAgent
from adal.config import settings
from adal.prompts.verifier import VERIFIER_SYSTEM_PROMPT, VERIFIER_USER_TEMPLATE
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

    def __init__(self, model: str | None = None):
        super().__init__(model=model)
        self.tools = WEB_TOOLS
        self.tool_executors = TOOL_EXECUTORS
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

    async def _think_smart(self, context: dict) -> str:
        if self.tools:
            return await self.think_with_tools(context, max_tokens=49152)
        return await self.think_with_retry(context, max_tokens=49152)

    async def verify(
        self,
        hypothesis: dict,
        analysis_context: str,
        domain: str,
        prior_failures: list[dict],
    ) -> dict[str, Any]:
        domain_constraints = self._load_domain_constraints(domain)

        numerical_results = self._run_numerical_validation(hypothesis, domain)
        if domain == "chemistry":
            real_world = self._validate_chemistry_real_world(hypothesis)
            if numerical_results:
                numerical_results.update(real_world)
            else:
                numerical_results = real_world

        pre_flaws = []
        if numerical_results:
            for key, check in numerical_results.items():
                if isinstance(check, dict) and check.get("valid") is False:
                    pre_flaws.append(f"{key}: {check.get('message', 'failed')}")
            if pre_flaws:
                self.log.info("pre_llm_fatal_flaws_found", flaws=pre_flaws)
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

        context = {
            "hypothesis_json": json.dumps(hypothesis, indent=2),
            "analysis_context": analysis_context,
            "domain_constraints": domain_constraints,
            "prior_failures": json.dumps(prior_failures, indent=2) if prior_failures else "None",
        }

        self.log.info("verifier_starting", domain=domain)
        response = await self._think_smart(context)
        result = self.parse_json_block(response)

        if "error" in result:
            self.log.error("verifier_parse_failed", error=result["error"])
            retry_context = {**context}
            retry_context["_retry_note"] = (
                "\n\n[SYSTEM NOTE: Your previous response was not valid JSON or was empty. "
                "You MUST output the complete JSON response with ALL required fields: "
                "verdict, confidence, checks_performed, mathematical_proof, fatal_flaws, suggestions.]"
            )
            response = await self._think_smart(retry_context)
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

        self.log.info(
            "verifier_done",
            verdict=result.get("verdict", "UNKNOWN"),
            confidence=result.get("confidence", 0.0),
        )
        return result

    def build_prompt(self, context: dict) -> str:
        base = VERIFIER_USER_TEMPLATE.format(
            _session_memory=context.get("_session_memory", ""),
            hypothesis_json=context["hypothesis_json"],
            analysis_context=context["analysis_context"],
            domain_constraints=context["domain_constraints"],
            prior_failures=context["prior_failures"],
        )
        retry = context.get("_retry_note", "")
        return base + retry if retry else base

    def _load_domain_constraints(self, domain: str) -> str:
        module_path = DOMAIN_VALIDATORS.get(domain)
        if not module_path:
            return f"No validators found for domain: {domain}"

        try:
            module = importlib.import_module(module_path)
            functions = [name for name in dir(module) if name.startswith("validate_") and callable(getattr(module, name))]
            return f"Available validation functions in {domain}: {json.dumps(functions)}\nModule: {module_path}"
        except ImportError:
            return f"Validator module {module_path} not available"

    def _run_numerical_validation(self, hypothesis: dict, domain: str) -> dict | None:
        predicted = hypothesis.get("hypothesis", hypothesis).get("predicted_values", {})
        if not predicted:
            return None

        results = {}

        if domain == "astrophysics":
            results.update(self._validate_astrophysics(predicted))
        elif domain == "chemistry":
            results.update(self._validate_chemistry(predicted))
            results.update(self._validate_chemistry_real_world(hypothesis))
        elif domain == "physics":
            results.update(self._validate_physics(predicted))
        elif domain == "particle_nuclear":
            results.update(self._validate_particle_nuclear(predicted))

        return results if results else None

    def _validate_chemistry_real_world(self, hypothesis: dict) -> dict:
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
                pass

        has_workup = any(
            phrase in statement
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
