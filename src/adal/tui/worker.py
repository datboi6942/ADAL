import asyncio

from textual.message import Message

from adal.loop.orchestrator import Orchestrator


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

    @property
    def running(self) -> bool:
        return self._running

    async def run_query(self, query: str, model: str | None = None):
        self.orc = Orchestrator(model=model)
        self.orc.set_display_callback(self._on_status)
        self.orc.set_verbose_display(self._on_reasoning)
        self._running = True
        self._task = asyncio.current_task()

        try:
            result = await self.orc.run(query)
            self.app.screen.post_message(ResultReady(result))
        except asyncio.CancelledError:
            result = {"status": "cancelled", "domain": "unknown", "iterations": 0}
            self.app.screen.post_message(ResultReady(result))
        except Exception as e:
            result = {"status": "failed", "domain": "unknown", "iterations": 0, "final_answer": str(e)}
            self.app.screen.post_message(ResultReady(result))
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
                self.app.screen.post_message(ResultReady({"status": "failed", "domain": "unknown", "iterations": 0, "final_answer": f"Session {session_id} not found"}))
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

        try:
            result = await self.orc.run_restore(query or session.query or "")
            self.app.screen.post_message(ResultReady(result))
        except asyncio.CancelledError:
            self.app.screen.post_message(ResultReady({"status": "cancelled", "domain": state.domain.value, "iterations": state.iteration}))
        except Exception as e:
            self.app.screen.post_message(ResultReady({"status": "failed", "domain": state.domain.value, "iterations": state.iteration, "final_answer": str(e)}))
        finally:
            self._running = False

    async def _on_status(self, name: str, status: str, detail: str = ""):
        self.app.screen.post_message(StatusUpdate(name, status, detail))

    async def _on_reasoning(self, name: str, reasoning: str):
        self.app.screen.post_message(ReasoningUpdate(name, reasoning))
