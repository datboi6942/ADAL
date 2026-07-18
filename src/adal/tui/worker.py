import asyncio

from textual.message import Message

from adal.loop.orchestrator import Orchestrator
from adal.tui.widgets.debug_panel import VERBOSITY_LOW, DebugLine


class StatusUpdate(Message):
    def __init__(self, name: str, status: str, detail: str = ""):
        super().__init__()
        self.name = name
        self.status = status
        self.detail = detail


class ReasoningUpdate(Message):
    def __init__(self, name: str, text: str):
        super().__init__()
        self.name = name
        self.text = text


class ToolCallUpdate(Message):
    def __init__(self, agent: str, tool_name: str, args_preview: str, result_preview: str):
        super().__init__()
        self.agent = agent
        self.tool_name = tool_name
        self.args_preview = args_preview
        self.result_preview = result_preview


class TokenUpdate(Message):
    def __init__(self, info: str):
        super().__init__()
        self.info = info


class DomainSet(Message):
    def __init__(self, domain: str):
        super().__init__()
        self.domain = domain


class IterationSet(Message):
    def __init__(self, iteration: int):
        super().__init__()
        self.iteration = iteration


class ResultReady(Message):
    def __init__(self, result: dict):
        super().__init__()
        self.result = result


class OrcWorker:
    def __init__(self, app):
        self.app = app
        self.orc: Orchestrator | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._current_agent: str = ""
        self._debug = False

    @property
    def running(self) -> bool:
        return self._running

    def _safe_post_message(self, message: Message):
        try:
            self.app.screen.post_message(message)
        except Exception:
            pass

    async def run_query(self, query: str, model: str | None = None):
        self.orc = Orchestrator(model=model)
        self.orc.set_display_callback(self._on_status)
        self.orc.set_verbose_display(self._on_reasoning)
        self.orc.set_debug_callback(self._on_debug)
        self._running = True
        self._task = asyncio.current_task()

        self._wrap_tool_executors(self.orc)

        try:
            result = await self.orc.run(query)
            self._safe_post_message(ResultReady(result))
        except asyncio.CancelledError:
            result = {"status": "cancelled", "domain": "unknown", "iterations": 0}
            self._safe_post_message(ResultReady(result))
        except Exception as e:
            result = {"status": "failed", "domain": "unknown", "iterations": 0, "final_answer": str(e)}
            self._safe_post_message(ResultReady(result))
        finally:
            self._running = False

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def run_restore(self, session_id: str, model: str | None = None, query: str | None = None):
        self.orc = Orchestrator(model=model)
        self.orc.set_display_callback(self._on_status)
        self.orc.set_verbose_display(self._on_reasoning)
        self.orc.set_debug_callback(self._on_debug)
        self._running = True
        self._task = asyncio.current_task()

        from sqlalchemy import select

        from adal.db.models import Hypothesis, HypothesisStatus, Session
        from adal.db.session import get_sessionmaker
        from adal.loop.orchestrator import LoopState

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            session = await db.get(Session, session_id)
            if not session:
                self._running = False
                self._safe_post_message(ResultReady({"status": "failed", "domain": "unknown", "iterations": 0, "final_answer": f"Session {session_id} not found"}))
                return

            hyp_result = await db.execute(
                select(Hypothesis).where(Hypothesis.session_id == session_id).order_by(Hypothesis.iteration)
            )
            hypotheses = hyp_result.scalars().all()

        prior_failures = []
        validated_results = []
        all_hyps = []
        for h in hypotheses:
            all_hyps.append(h.content)
            if h.status == HypothesisStatus.REJECTED:
                prior_failures.append({"iteration": h.iteration, "hypothesis_summary": str(h.content)[:200], "reason": "Previously rejected"})
            elif h.status == HypothesisStatus.VERIFIED:
                validated_results.append({"iteration": h.iteration, "hypothesis": h.content, "verdict": {}})

        state = LoopState(
            session_id=session_id,
            query=session.query,
            domain=session.domain,
            iteration=session.iteration,
            status=session.status,
        )
        state.hypotheses = all_hyps
        state.prior_failures = prior_failures
        state.validated_results = validated_results

        self._wrap_tool_executors(self.orc)

        follow_up = query or session.query or ""
        context_parts = [f"[CONTINUATION — Session {session_id[:8]}]",
                         f"Original query: {session.query}"]
        if validated_results:
            last_val = validated_results[-1]
            last_hyp = last_val.get("hypothesis", {})
            if isinstance(last_hyp, dict):
                context_parts.append(f"Last validated result: {str(last_hyp.get('statement', last_hyp))[:500]}")
            else:
                context_parts.append(f"Last validated result: {str(last_hyp)[:500]}")
        elif all_hyps:
            last = all_hyps[-1]
            if isinstance(last, dict):
                context_parts.append(f"Last hypothesis: {str(last.get('statement', last))[:500]}")
            else:
                context_parts.append(f"Last hypothesis: {str(last)[:500]}")
        context_parts.append(f"\nNow answer this follow-up, building on the above findings:\n{follow_up}")
        enriched = "\n\n".join(context_parts)

        try:
            result = await self.orc.run_restore(enriched, state=state)
            self._safe_post_message(ResultReady(result))
        except asyncio.CancelledError:
            self._safe_post_message(ResultReady({"status": "cancelled", "domain": state.domain.value, "iterations": state.iteration}))
        except Exception as e:
            self._safe_post_message(ResultReady({"status": "failed", "domain": state.domain.value, "iterations": state.iteration, "final_answer": str(e)}))
        finally:
            self._running = False

    def _wrap_tool_executors(self, orc: Orchestrator):
        import inspect
        from functools import wraps

        for agent_attr in ("planner", "proposer", "verifier"):
            agent = getattr(orc, agent_attr, None)
            if agent is None or not agent.tool_executors:
                continue

            original = dict(agent.tool_executors)
            agent_label = agent_attr

            for tool_name, executor in original.items():
                if getattr(executor, "_adal_wrapped", False):
                    continue
                if inspect.iscoroutinefunction(executor):

                    @wraps(executor)
                    async def _wrapped(*args, _tn=tool_name, _al=agent_label, _orig=executor, **kwargs):
                        args_str = ", ".join(
                            f"{k}={str(v)[:60]}" for k, v in
                            (list(kwargs.items()) + [("query", str(args[0])[:80])] if args else [])
                        )
                        if self._debug:
                            self._safe_post_message(
                                DebugLine("tool", _tn, f"Calling: {args_str[:200]}")
                            )
                        try:
                            result = await _orig(*args, **kwargs)
                            result_preview = str(result)[:120].replace("\n", " ")
                            self._safe_post_message(
                                ToolCallUpdate(_al, _tn, args_str[:100], result_preview)
                            )
                            if self._debug:
                                self._safe_post_message(
                                    DebugLine("tool", _tn, f"{args_str[:200]} → {result_preview}")
                                )
                            return result
                        except Exception as e:
                            self._safe_post_message(
                                ToolCallUpdate(_al, _tn, args_str[:100], f"Error: {e}")
                            )
                            raise

                    _wrapped._adal_wrapped = True
                    agent.tool_executors[tool_name] = _wrapped

    async def _on_debug(self, category: str, event: str, detail: str = "",
                        verbosity: int = VERBOSITY_LOW):
        if self._debug:
            self._safe_post_message(DebugLine(category, event, detail, verbosity=verbosity))

    async def _on_status(self, name: str, status: str, detail: str = "",
                         verbosity: int = VERBOSITY_LOW):
        self._current_agent = name.lower()
        self._safe_post_message(StatusUpdate(name, status, detail))
        if self._debug and detail:
            self._safe_post_message(DebugLine(name.lower(), status, detail[:800], verbosity=verbosity))

    async def _on_reasoning(self, name: str, reasoning: str,
                            verbosity: int = VERBOSITY_LOW):
        self._safe_post_message(ReasoningUpdate(name, reasoning))
        if self._debug:
            self._safe_post_message(DebugLine(name.lower(), "reasoning", reasoning[:1000], verbosity=verbosity))
