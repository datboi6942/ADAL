import datetime
import enum
import uuid

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Domain(enum.StrEnum):
    ASTROPHYSICS = "astrophysics"
    CHEMISTRY = "chemistry"
    PHYSICS = "physics"
    PARTICLE_NUCLEAR = "particle_nuclear"
    UNKNOWN = "unknown"


class AgentRole(enum.StrEnum):
    PROPOSER = "proposer"
    VERIFIER = "verifier"
    PLANNER = "planner"


class SessionStatus(enum.StrEnum):
    ACTIVE = "active"
    CONVERGED = "converged"
    FAILED = "failed"
    MAX_ITERATIONS = "max_iterations"
    CANCELLED = "cancelled"


class HypothesisStatus(enum.StrEnum):
    PROPOSED = "proposed"
    VALIDATING = "validating"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class InteractionDirection(enum.StrEnum):
    PLANNER_TO_PROPOSER = "planner_to_proposer"
    PROPOSER_TO_VERIFIER = "proposer_to_verifier"
    VERIFIER_TO_PLANNER = "verifier_to_planner"


class PlannerAction(enum.StrEnum):
    CONTINUE = "continue"
    PIVOT = "pivot"
    CONVERGE = "converge"
    FAIL = "fail"


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[Domain] = mapped_column(Enum(Domain), default=Domain.UNKNOWN)
    status: Mapped[SessionStatus] = mapped_column(Enum(SessionStatus), default=SessionStatus.ACTIVE)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.UTC),
        onupdate=lambda: datetime.datetime.now(datetime.UTC),
    )

    hypotheses: Mapped[list["Hypothesis"]] = relationship(back_populates="session", order_by="Hypothesis.iteration")
    interactions: Mapped[list["AgentInteraction"]] = relationship(back_populates="session")


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_role: Mapped[AgentRole] = mapped_column(Enum(AgentRole), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[HypothesisStatus] = mapped_column(Enum(HypothesisStatus), default=HypothesisStatus.PROPOSED)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    session: Mapped["Session"] = relationship(back_populates="hypotheses")
    validation_results: Mapped[list["ValidationResult"]] = relationship(back_populates="hypothesis")
    datasets: Mapped[list["Dataset"]] = relationship(back_populates="hypothesis")
    planner_decisions: Mapped[list["PlannerDecision"]] = relationship(back_populates="hypothesis")


class AgentInteraction(Base):
    __tablename__ = "agent_interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    hypothesis_id: Mapped[str | None] = mapped_column(ForeignKey("hypotheses.id"), nullable=True)
    agent_role: Mapped[AgentRole] = mapped_column(Enum(AgentRole), nullable=False)
    direction: Mapped[InteractionDirection] = mapped_column(Enum(InteractionDirection), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    session: Mapped["Session"] = relationship(back_populates="interactions")


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    proof: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    constraints_applied: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    hypothesis: Mapped["Hypothesis"] = relationship(back_populates="validation_results")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    data_path: Mapped[str] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    hypothesis: Mapped["Hypothesis"] = relationship(back_populates="datasets")


class PlannerDecision(Base):
    __tablename__ = "planner_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), nullable=False)
    action: Mapped[PlannerAction] = mapped_column(Enum(PlannerAction), nullable=False)
    directive: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    hypothesis: Mapped["Hypothesis"] = relationship(back_populates="planner_decisions")
