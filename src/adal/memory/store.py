import time

import lancedb
import pyarrow as pa
import structlog

from adal.config import settings
from adal.memory.embedder import get_embedding

logger = structlog.get_logger(__name__)

SCHEMA = pa.schema([
    pa.field("vector", pa.list_(pa.float32(), 1536)),
    pa.field("text", pa.string()),
    pa.field("session_id", pa.string()),
    pa.field("memory_type", pa.string()),
    pa.field("agent_role", pa.string()),
    pa.field("iteration_turn", pa.int32()),
    pa.field("timestamp", pa.float64()),
])


class MemoryStore:
    def __init__(self, db_path: str | None = None):
        self._path = db_path or settings.memory_db_path
        self._db: lancedb.DBConnection | None = None
        self._table = None
        self._connected = False
        self._failure_vectors: list[list[float]] = []
        self._failure_vectors_loaded = False

    @property
    def enabled(self) -> bool:
        return settings.memory_enabled and bool(settings.openai_api_key)

    def _connect(self):
        if self._connected:
            return
        try:
            self._db = lancedb.connect(self._path)
            if "agent_memory" in self._db.table_names():
                self._table = self._db.open_table("agent_memory")
            else:
                self._table = self._db.create_table("agent_memory", schema=SCHEMA, exist_ok=True)
            try:
                row_count = self._table.count_rows()
                if row_count >= 256:
                    self._table.create_index(num_partitions=min(256, row_count // 4))
            except Exception as idx_err:
                logger.warning("vector_index_creation_skipped", error=str(idx_err))
            self._connected = True
            logger.info("memory_store_connected", path=self._path)
        except Exception as e:
            logger.error("memory_connect_failed", error=str(e))
            self._connected = False

    def reset_for_session(self, session_id: str):
        self._failure_vectors = []
        self._failure_vectors_loaded = False
        try:
            self._connect()
            if self._table:
                results = (
                    self._table.search()
                    .where(f"session_id == '{session_id}' AND memory_type == 'episodic_failure'")
                    .limit(100)
                    .to_list()
                )
                for r in results:
                    vec = r.get("vector")
                    if vec:
                        self._failure_vectors.append(vec)
                self._failure_vectors_loaded = True
                logger.debug("failure_vectors_restored", count=len(results), session_id=session_id)
            else:
                self._failure_vectors_loaded = True
        except Exception as e:
            logger.debug("failure_vectors_restore_skipped", error=str(e))
            self._failure_vectors_loaded = True

    async def record_memory(
        self,
        text: str,
        session_id: str,
        agent_role: str,
        memory_type: str = "episodic",
        iteration_turn: int = 0,
    ):
        if not self.enabled:
            return
        self._connect()
        if not self._connected or not text or not text.strip():
            return

        try:
            vector = await get_embedding(text)
            data = [{
                "vector": [float(v) for v in vector],
                "text": text,
                "session_id": session_id,
                "memory_type": memory_type,
                "agent_role": agent_role,
                "iteration_turn": iteration_turn,
                "timestamp": time.time(),
            }]
            self._table.add(data)
            logger.debug("memory_recorded", session_id=session_id, agent_role=agent_role, memory_type=memory_type, text_preview=text[:100])
        except Exception as e:
            logger.error("memory_record_failed", error=str(e), session_id=session_id)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def record_failure(
        self,
        text: str,
        session_id: str,
        agent_role: str,
        iteration: int = 0,
    ):
        if not self.enabled or not text or not text.strip():
            return
        try:
            vector = await get_embedding(text)
            vector_f = [float(v) for v in vector]
            self._failure_vectors.append(vector_f)
            data = [{
                "vector": vector_f,
                "text": text,
                "session_id": session_id,
                "memory_type": "episodic_failure",
                "agent_role": agent_role,
                "iteration_turn": iteration,
                "timestamp": time.time(),
            }]
            self._connect()
            if self._table is not None:
                self._table.add(data)
            logger.debug("failure_recorded", session_id=session_id, agent_role=agent_role, text_preview=text[:100])
        except Exception as e:
            logger.error("failure_record_failed", error=str(e), session_id=session_id)

    async def _load_failure_vectors(self, session_id: str):
        if self._failure_vectors_loaded:
            return
        self._connect()
        if not self._table:
            return
        try:
            results = (
                self._table.search()
                .where(f"session_id == '{session_id}' AND memory_type == 'episodic_failure'")
                .limit(100)
                .to_list()
            )
            for r in results:
                vec = r.get("vector")
                if vec:
                    self._failure_vectors.append(vec)
            self._failure_vectors_loaded = True
            logger.debug("failure_vectors_loaded", count=len(results), session_id=session_id)
        except Exception as e:
            logger.error("failure_vectors_load_failed", error=str(e))
            self._failure_vectors_loaded = True

    async def query_session_memory(self, query_text: str, session_id: str, limit: int | None = None) -> list[str]:
        if not self.enabled:
            return []
        self._connect()
        if not self._connected:
            return []

        max_results = limit or settings.memory_max_episodic
        prune_threshold = settings.memory_prune_threshold

        try:
            vector = await get_embedding(query_text)
            vector_f = [float(v) for v in vector]

            fetch_n = max(10, max_results * 3)
            results = (
                self._table.search(vector_f)
                .where(f"session_id == '{session_id}' AND memory_type == 'episodic'")
                .limit(fetch_n)
                .to_list()
            )

            await self._load_failure_vectors(session_id)

            if self._failure_vectors:
                survivors = []
                for r in results:
                    r_vec = r.get("vector", [])
                    max_sim = 0.0
                    for fail_vec in self._failure_vectors:
                        sim = self._cosine_similarity(r_vec, fail_vec)
                        if sim > max_sim:
                            max_sim = sim
                    if max_sim < prune_threshold:
                        survivors.append(r["text"])
                    else:
                        logger.debug(
                            "memory_pruned",
                            text_preview=r["text"][:80],
                            max_similarity=round(max_sim, 3),
                            threshold=prune_threshold,
                        )
                texts = survivors[:max_results]
            else:
                texts = [r["text"] for r in results[:max_results]]

            logger.debug("session_memory_queried", session_id=session_id, fetched=len(results), returned=len(texts), pruned=(len(results) - len(texts)) if self._failure_vectors else 0)
            return texts
        except Exception as e:
            logger.error("session_memory_query_failed", error=str(e), session_id=session_id)
            return []

    async def query_global_lessons(self, query_text: str, limit: int | None = None) -> list[str]:
        if not self.enabled:
            return []
        self._connect()
        if not self._connected:
            return []

        max_results = limit or settings.memory_max_global
        try:
            vector = await get_embedding(query_text)
            results = (
                self._table.search([float(v) for v in vector])
                .where("memory_type == 'global_lesson'")
                .limit(max_results)
                .to_list()
            )
            texts = [r["text"] for r in results]
            logger.debug("global_lessons_queried", results=len(texts))
            return texts
        except Exception as e:
            logger.error("global_lessons_query_failed", error=str(e))
            return []

    async def summarize_and_record_lesson(
        self,
        session_id: str,
        hypotheses_history: list[dict],
        final_status: str,
        summarize_text: str | None = None,
    ):
        if not self.enabled:
            return
        self._connect()
        if not self._connected:
            return

        summary = summarize_text or _build_lesson_summary(session_id, hypotheses_history, final_status)
        if not summary.strip():
            return

        try:
            vector = await get_embedding(summary)
            data = [{
                "vector": [float(v) for v in vector],
                "text": summary,
                "session_id": session_id,
                "memory_type": "global_lesson",
                "agent_role": "planner",
                "iteration_turn": len(hypotheses_history),
                "timestamp": time.time(),
            }]
            self._table.add(data)
            logger.info("global_lesson_recorded", session_id=session_id, status=final_status)
        except Exception as e:
            logger.error("global_lesson_record_failed", error=str(e), session_id=session_id)


def _build_lesson_summary(
    session_id: str,
    hypotheses_history: list[dict],
    final_status: str,
) -> str:
    total = len(hypotheses_history)
    if total == 0:
        return ""

    parts = [
        f"Session {session_id[:8]}: {final_status.upper()} after {total} hypotheses.",
    ]

    verdicts = [h.get("verdict", "UNKNOWN") for h in hypotheses_history if isinstance(h, dict)]
    passed = sum(1 for v in verdicts if v == "PASS")
    failed = sum(1 for v in verdicts if v in ("FAIL", "REJECTED"))
    partial = sum(1 for v in verdicts if v == "PARTIAL")

    parts.append(f"Results: {passed} passed, {failed} rejected, {partial} partial.")

    flaws = []
    for h in hypotheses_history:
        if isinstance(h, dict):
            for f in (h.get("fatal_flaws") or []):
                if isinstance(f, str) and f not in flaws:
                    flaws.append(f)
    if flaws:
        parts.append(f"Common fatal flaws: {'; '.join(flaws[:5])}")

    suggestions = []
    for h in hypotheses_history:
        if isinstance(h, dict):
            for s in (h.get("suggestions") or []):
                if isinstance(s, str) and s not in suggestions:
                    suggestions.append(s)
    if suggestions:
        parts.append(f"Key suggestions: {'; '.join(suggestions[:5])}")

    return " ".join(parts)
