import json
import re
from typing import Any

import structlog

from adal.agents.base import BaseAgent
from adal.config import settings
from adal.db.models import Domain
from adal.prompts.planner import PLANNER_SYSTEM_PROMPT, PLANNER_USER_TEMPLATE
from adal.tools.web_search import TOOL_DEFINITIONS as WEB_TOOLS
from adal.tools.web_search import TOOL_EXECUTORS

logger = structlog.get_logger(__name__)

DOMAIN_KEYWORDS = {
    Domain.ASTROPHYSICS: [
        r"\bstar(s?)\b", r"\bplanet(ary|s)?\b", r"\bexoplanet\b", r"\btransit\b",
        r"\blight[\s-]?curve\b", r"\borbit(al)?\b", r"\bgalax(y|ies|ic)\b",
        r"\bstellar\b", r"\bkepler\b", r"\btess\b", r"\beclipse\b",
        r"\bradial[\s-]?velocity\b", r"\bspectroscopy\b", r"\bspectra(l)?\b",
        r"\bcosmolog(y|ical)\b", r"\bredshift\b", r"\bsupernova\b",
        r"\bblack[\s-]?hole\b", r"\buniverse\b", r"\bastrometry\b",
        r"\bparallax\b", r"\bmagnitude\b", r"\bluminosity\b",
        r"\binterstellar\b", r"\bcelestial\b", r"\btelescope\b",
    ],
    Domain.CHEMISTRY: [
        r"\bsynthes(is|ize|es|is procedure)\b", r"\bmolecule(s|ular)?\b",
        r"\bcompound\b", r"\breaction\b", r"\borganic\b", r"\binorganic\b",
        r"\bcatalyst\b", r"\bbond(ing)?\b", r"\bpolymer\b", r"\bsolvent\b",
        r"\breagent\b", r"\bfunctional[\s-]?group\b", r"\bnmr\b",
        r"\bchromatography\b", r"\btitration\b", r"\boxidation\b",
        r"\breduction\b", r"\breductive\b", r"\bamination\b",
        r"\breductive[\s-]?amination\b", r"\bacid\b", r"\bbase\b",
        r"\bph\b", r"\benzyme\b", r"\bprotein\b", r"\bdrug\b",
        r"\bpharmaceutical\b", r"\baspirin\b", r"\b(desoxy|deoxy)benzoin\b",
        r"\bisopropylphenidine\b", r"\bisopropylamine\b", r"\bborohydride\b",
        r"\btriacetoxyborohydride\b", r"\bamine\b", r"\bamide\b",
        r"\bsubstrate\b", r"\bintermediate\b", r"\bworkup\b",
        r"\bpurification\b", r"\brecrystallization\b", r"\breflux\b",
        r"\bstoichiometry\b", r"\bmechanism\b", r"\byield\b",
        r"\bprotecting[\s-]?group\b", r"\bester\b", r"\bketone\b",
        r"\baldehyde\b", r"\balcohol\b", r"\bcarbonyl\b",
        r"\bcarboxylic[\s-]?acid\b", r"\bphenidine\b", r"\bproduce\b",
    ],
    Domain.PHYSICS: [
        r"\bforce\b", r"\benergy\b", r"\bmomentum\b", r"\bthermodynamics\b",
        r"\bentropy\b", r"\bwave\b", r"\bquantum\b", r"\brelativity\b",
        r"\belectromagnetism\b", r"\bgravity\b", r"\bfluid\b",
        r"\boscillation\b", r"\bharmonic\b", r"\bdiffraction\b",
        r"\binterference\b", r"\bdoppler\b", r"\bpressure\b",
        r"\btemperature\b", r"\bvolume\b", r"\benthalpy\b",
    ],
    Domain.PARTICLE_NUCLEAR: [
        r"\bparticle\b", r"\bquark\b", r"\blepton\b", r"\bboson\b",
        r"\bneutrino\b", r"\bmuon\b", r"\bpion\b", r"\bkaon\b",
        r"\bdecay\b", r"\bcross[\s-]?section\b", r"\bstandard[\s-]?model\b",
        r"\blhc\b", r"\bcollider\b", r"\bnuclear\b", r"\bisotope\b",
        r"\bradioactive\b", r"\bfission\b", r"\bfusion\b",
        r"\bbinding[\s-]?energy\b", r"\bbaryon\b", r"\bmeson\b",
        r"\bhiggs\b", r"\bw[\s-]?boson\b", r"\bz[\s-]?boson\b", r"\bgluon\b",
    ],
}


class Planner(BaseAgent):
    role = "planner"
    system_prompt = PLANNER_SYSTEM_PROMPT

    def __init__(self, model: str | None = None):
        super().__init__(model=model)
        self.tools = WEB_TOOLS
        self.tool_executors = TOOL_EXECUTORS
        self.gen_params = {
            "temperature": settings.planner_temperature,
            "top_p": settings.planner_top_p,
            "frequency_penalty": settings.planner_frequency_penalty,
            "presence_penalty": settings.planner_presence_penalty,
        }
        if settings.planner_top_k > 0:
            self.gen_params["top_k"] = settings.planner_top_k
        if settings.planner_seed is not None:
            self.gen_params["seed"] = settings.planner_seed

    async def _think_smart(self, context: dict) -> str:
        if self.tools:
            return await self.think_with_tools(context)
        return await self.think_with_retry(context)

    def classify_domain(self, query: str) -> Domain:
        query_lower = query.lower()
        scores: dict[Domain, int] = {domain: 0 for domain in Domain}

        for domain, patterns in DOMAIN_KEYWORDS.items():
            for pattern in patterns:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    scores[domain] += 1

        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return Domain.UNKNOWN

        tied = [d for d, s in scores.items() if s == scores[best]]
        if len(tied) > 1:
            weighted = {d: 0 for d in tied}
            spec_regex = r"\b(desoxybenzoin|isopropylphenidine|isopropylamine|triacetoxyborohydride|borohydride|phenidine|reductive\s+amination)\b"
            long_regex = r"\b(synthesis[\s-]?(procedure|pathway|route)|reductive[\s-]?amination|protecting[\s-]?group|functional[\s-]?group|radial[\s-]?velocity|light[\s-]?curve|binding[\s-]?energy|cross[\s-]?section|standard[\s-]?model|black[\s-]?hole|w[\s-]?boson|z[\s-]?boson|orbital[\s-]?period|semi[\s-]?major[\s-]?axis)\b"
            for d in tied:
                if d == Domain.CHEMISTRY:
                    weighted[d] += len(re.findall(spec_regex, query_lower, re.IGNORECASE)) * 5
                    weighted[d] += len(re.findall(long_regex, query_lower, re.IGNORECASE))
                elif d == Domain.PARTICLE_NUCLEAR:
                    weighted[d] += len(re.findall(spec_regex, query_lower, re.IGNORECASE)) * 5
                    weighted[d] += len(re.findall(long_regex, query_lower, re.IGNORECASE))

            best = max(weighted, key=weighted.get) if max(weighted.values()) > 0 else tied[0]
            if max(weighted.values()) == 0:
                best = tied[0]

        logger.info("domain_classified", domain=best.value, scores=scores)
        return best

    async def plan(
        self,
        user_query: str,
        state: dict[str, Any],
        verdict: dict[str, Any] | None = None,
        hypotheses_history: list[dict] | None = None,
    ) -> dict[str, Any]:
        context = {
            "user_query": user_query,
            "state_json": json.dumps(state, indent=2),
            "verdict_json": json.dumps(verdict, indent=2) if verdict else "None (initial planning)",
            "hypotheses_history": json.dumps(hypotheses_history, indent=2) if hypotheses_history else "[]",
        }

        self.log.info("planner_thinking", iteration=state.get("iteration", 0))
        response = await self._think_smart(context)
        result = self.parse_json_block(response)

        if "error" in result:
            self.log.error("planner_parse_failed", error=result["error"])
            retry_context = {**context}
            retry_context["_retry_note"] = (
                "\n\n[SYSTEM NOTE: Your previous response was not valid JSON. "
                "You MUST output a complete, valid JSON object with ALL required fields. "
                "Check for unescaped quotes, trailing commas, or missing closing brackets.]"
            )
            response = await self._think_smart(retry_context)
            result = self.parse_json_block(response)

        if result.get("error"):
            self.log.error("planner_fatal_parse_failure", error=result["error"])
            result = {
                "action": "continue",
                "session_status": "ACTIVE",
                "reasoning": f"Planner JSON parse failed: {result['error']}",
                "directive_to_proposer": "Retry the previous hypothesis with corrected JSON format.",
            }

        if "domain_classification" not in result and state.get("iteration", 0) == 0:
            result["domain_classification"] = self.classify_domain(user_query).value

        return result

    async def initial_plan(self, user_query: str) -> dict[str, Any]:
        domain = self.classify_domain(user_query)
        initial_state = {
            "iteration": 0,
            "status": "active",
            "domain": domain.value,
        }

        result = await self.plan(
            user_query=user_query,
            state=initial_state,
            verdict=None,
            hypotheses_history=[],
        )
        result["domain_classification"] = domain.value
        return result

    def build_prompt(self, context: dict) -> str:
        base = PLANNER_USER_TEMPLATE.format(
            _session_memory=context.get("_session_memory", ""),
            user_query=context["user_query"],
            state_json=context["state_json"],
            verdict_json=context["verdict_json"],
            hypotheses_history=context["hypotheses_history"],
        )
        retry = context.get("_retry_note", "")
        return base + retry if retry else base
