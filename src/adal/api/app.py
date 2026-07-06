from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from adal.api.orc_runner import OrcRunner
from adal.tui.db_queries import (
    get_hypotheses,
    get_interactions,
    get_library_stats,
    get_session,
    get_validated_procedures,
    get_validation_results,
    list_sessions,
)

app = FastAPI(title="ADAL API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_runners: dict[str, OrcRunner] = {}


class RunRequest(BaseModel):
    query: str
    domain: str | None = None
    model: str | None = None


class ContinueRequest(BaseModel):
    query: str
    model: str | None = None


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/sessions")
async def sessions(limit: int = Query(50, ge=1, le=200)):
    rows = await list_sessions(limit)
    return [
        {
            "id": str(s.id),
            "query": s.query[:200],
            "domain": s.domain.value,
            "status": s.status.value,
            "iteration": s.iteration,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in rows
    ]


@app.get("/api/sessions/{session_id}")
async def session_detail(session_id: str):
    session = await get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    hypotheses = await get_hypotheses(session_id)
    validations = await get_validation_results(session_id)
    interactions = await get_interactions(session_id)

    return {
        "id": str(session.id),
        "query": session.query,
        "domain": session.domain.value,
        "status": session.status.value,
        "iteration": session.iteration,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "hypotheses": [
            {
                "id": str(h.id),
                "iteration": h.iteration,
                "agent_role": h.agent_role.value,
                "status": h.status.value,
                "content": h.content,
            }
            for h in hypotheses
        ],
        "interactions": [
            {
                "id": str(ix.id),
                "hypothesis_id": str(ix.hypothesis_id) if ix.hypothesis_id else None,
                "agent_role": ix.agent_role.value,
                "direction": ix.direction.value,
                "content": ix.content,
                "created_at": ix.created_at.isoformat() if ix.created_at else None,
            }
            for ix in interactions
        ],
        "validations": [
            {
                "id": str(v.id),
                "hypothesis_id": v.hypothesis_id,
                "passed": v.passed,
                "confidence": v.confidence,
                "proof": v.proof,
            }
            for v in validations
        ],
    }


@app.post("/api/run")
async def run_research(req: RunRequest):
    runner = OrcRunner()
    session_id = str(uuid.uuid4())
    _runners[session_id] = runner

    async def _run():
        result = await runner.run_query(req.query, model=req.model)
        result["session_id"] = session_id
        return result

    result = await _run()
    return result


@app.get("/api/sessions/{session_id}/stream")
async def stream_session(session_id: str):
    session = await get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    runner = OrcRunner()
    _runners[session_id] = runner

    async def _event_stream():
        asyncio.create_task(runner.run_restore(session_id, query=session.query))

        while True:
            try:
                event = await asyncio.wait_for(runner.queue.get(), timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "done":
                    break
            except TimeoutError:
                yield "data: {\"type\": \"ping\"}\n\n"
                if not runner.running:
                    break

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/continue")
async def continue_session(session_id: str, req: ContinueRequest):
    runner = OrcRunner()
    _runners[session_id] = runner
    result = await runner.run_restore(session_id, query=req.query, model=req.model)
    result["session_id"] = session_id
    return result


@app.get("/api/library")
async def library(domain: str | None = None, limit: int = Query(50, ge=1, le=200)):
    rows = await get_validated_procedures(domain, limit)
    stats = await get_library_stats()
    return {
        "stats": {str(k): v for k, v in stats.items()},
        "procedures": [
            {
                "hypothesis_id": str(h.id),
                "session_id": str(s.id),
                "iteration": h.iteration,
                "domain": s.domain.value,
                "status": h.status.value,
                "content": h.content,
                "validation": {
                    "passed": v.passed,
                    "confidence": v.confidence,
                    "proof": v.proof,
                } if v else None,
            }
            for h, s, v in rows
        ],
    }


@app.post("/api/stop/{session_id}")
async def stop_session(session_id: str):
    runner = _runners.pop(session_id, None)
    if runner:
        runner.stop()
        return {"status": "stopped", "session_id": session_id}
    raise HTTPException(404, "Session not found or not running")


@app.on_event("startup")
async def _startup():
    from adal.db.session import get_engine, init_db
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: None)
    await init_db()
