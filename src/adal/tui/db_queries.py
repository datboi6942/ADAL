from sqlalchemy import desc, func, select

from adal.db.models import (
    AgentInteraction,
    DebugLog,
    DiagnosticSeverity,
    Domain,
    Hypothesis,
    HypothesisStatus,
    MetaDiagnostic,
    Session,
    ValidationResult,
)
from adal.db.session import get_sessionmaker


async def list_sessions(limit: int = 50):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        result = await db.execute(
            select(Session).order_by(desc(Session.created_at)).limit(limit)
        )
        return result.scalars().all()


async def get_session(session_id: str):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        return await db.get(Session, session_id)


async def get_hypotheses(session_id: str):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        result = await db.execute(
            select(Hypothesis)
            .where(Hypothesis.session_id == session_id)
            .order_by(Hypothesis.iteration, Hypothesis.agent_role)
        )
        return result.scalars().all()


async def get_validated_procedures(domain: str | None = None, limit: int = 50):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        stmt = (
            select(Hypothesis, Session, ValidationResult)
            .join(Session, Hypothesis.session_id == Session.id)
            .outerjoin(ValidationResult, ValidationResult.hypothesis_id == Hypothesis.id)
            .where(Hypothesis.status == HypothesisStatus.VERIFIED)
            .order_by(desc(Hypothesis.created_at))
        )
        if domain:
            stmt = stmt.where(Session.domain == Domain(domain))
        result = await db.execute(stmt.limit(limit))
        return result.all()


async def get_library_stats():
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        result = await db.execute(
            select(Session.domain, func.count(Hypothesis.id))
            .join(Hypothesis, Hypothesis.session_id == Session.id)
            .where(Hypothesis.status == HypothesisStatus.VERIFIED)
            .group_by(Session.domain)
        )
        return dict(result.all())


async def get_session_cost(session_id: str) -> float:
    return 0.0


async def get_interactions(session_id: str):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        result = await db.execute(
            select(AgentInteraction)
            .where(AgentInteraction.session_id == session_id)
            .order_by(AgentInteraction.created_at)
        )
        return result.scalars().all()


async def get_validation_results(session_id: str):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        result = await db.execute(
            select(ValidationResult)
            .join(Hypothesis, ValidationResult.hypothesis_id == Hypothesis.id)
            .where(Hypothesis.session_id == session_id)
            .order_by(ValidationResult.created_at)
        )
        return result.scalars().all()


async def delete_session(session_id: str):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        session = await db.get(Session, session_id)
        if session:
            await db.delete(session)
            await db.commit()


async def get_meta_diagnostics(severity: str | None = None, pattern_category: str | None = None, limit: int = 200):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        stmt = (
            select(MetaDiagnostic, Session.query, Session.domain)
            .join(Session, MetaDiagnostic.session_id == Session.id)
            .order_by(desc(MetaDiagnostic.created_at))
        )
        if severity:
            try:
                sev = DiagnosticSeverity(severity)
                stmt = stmt.where(MetaDiagnostic.severity == sev)
            except ValueError:
                pass
        if pattern_category:
            stmt = stmt.where(MetaDiagnostic.pattern_category == pattern_category)
        result = await db.execute(stmt.limit(limit))
        return result.all()


async def get_diagnostic_stats():
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        result = await db.execute(
            select(MetaDiagnostic.severity, func.count(MetaDiagnostic.id))
            .group_by(MetaDiagnostic.severity)
        )
        return dict(result.all())


async def get_debug_logs(session_id: str):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        result = await db.execute(
            select(DebugLog)
            .where(DebugLog.session_id == session_id)
            .order_by(DebugLog.line_order)
        )
        return result.scalars().all()


async def persist_debug_logs(session_id: str, entries: list[dict], start_offset: int = 0):
    if not entries:
        return
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        for i, entry in enumerate(entries):
            db.add(DebugLog(
                session_id=session_id,
                category=entry["category"],
                event=entry["event"],
                detail=entry["detail"],
                verbosity=entry["verbosity"],
                line_order=start_offset + i,
            ))
        await db.commit()


async def delete_debug_logs(session_id: str):
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        from sqlalchemy import delete
        await db.execute(delete(DebugLog).where(DebugLog.session_id == session_id))
        await db.commit()
