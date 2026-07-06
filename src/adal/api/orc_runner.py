from __future__ import annotations

import asyncio
from typing import Any

from adal.loop.orchestrator import Orchestrator


class OrcRunner:
    """Thin async wrapper around Orchestrator for headless API use.

    Manages the orchestrator lifecycle and fans out callbacks to an
    asyncio.Queue for SSE streaming via the FastAPI endpoint.
    """

    def __init__(self) -> None:
        self._orc: Orchestrator | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def queue(self) -> asyncio.Queue[dict[str, Any]]:
        return self._queue

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def run_query(self, query: str, model: str | None = None) -> dict:
        self._orc = Orchestrator(model=model)
        self._orc.set_display_callback(self._on_status)
        self._orc.set_verbose_display(self._on_reasoning)
        self._running = True
        self._task = asyncio.current_task()

        try:
            result = await self._orc.run(query)
            await self._queue.put({"type": "result", "data": result})
            return result
        except asyncio.CancelledError:
            result = {"status": "cancelled", "domain": "unknown", "iterations": 0}
            await self._queue.put({"type": "result", "data": result})
            return result
        except Exception as e:
            result = {"status": "failed", "domain": "unknown", "iterations": 0, "final_answer": str(e)}
            await self._queue.put({"type": "result", "data": result})
            return result
        finally:
            self._running = False
            await self._queue.put({"type": "done"})

    async def run_restore(self, session_id: str, model: str | None = None, query: str | None = None) -> dict:
        self._orc = Orchestrator(model=model)
        self._orc.set_display_callback(self._on_status)
        self._orc.set_verbose_display(self._on_reasoning)
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
                result = {"status": "failed", "domain": "unknown", "iterations": 0, "final_answer": f"Session {session_id} not found"}
                await self._queue.put({"type": "result", "data": result})
                return result

            hyp_result = await db.execute(
                select(Hypothesis).where(Hypothesis.session_id == session_id).order_by(Hypothesis.iteration)
            )
            hypotheses = hyp_result.scalars().all()

        prior_failures: list = []
        validated_results: list = []
        all_hyps: list = []
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
            result = await self._orc.run_restore(query or session.query or "")
            await self._queue.put({"type": "result", "data": result})
            return result
        except asyncio.CancelledError:
            result = {"status": "cancelled", "domain": state.domain.value, "iterations": state.iteration}
            await self._queue.put({"type": "result", "data": result})
            return result
        except Exception as e:
            result = {"status": "failed", "domain": state.domain.value, "iterations": state.iteration, "final_answer": str(e)}
            await self._queue.put({"type": "result", "data": result})
            return result
        finally:
            self._running = False
            await self._queue.put({"type": "done"})

    async def _on_status(self, name: str, status: str, detail: str = "") -> None:
        await self._queue.put({"type": "status", "name": name, "status": status, "detail": detail})

    async def _on_reasoning(self, name: str, reasoning: str) -> None:
        await self._queue.put({"type": "reasoning", "name": name, "text": reasoning[:200]})
