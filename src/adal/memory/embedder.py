import structlog
from openai import AsyncOpenAI

from adal.config import settings

logger = structlog.get_logger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI | None:
    global _client
    if not settings.openai_api_key:
        return None
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def reset_embedder():
    global _client
    _client = None


async def get_embedding(text: str) -> list[float]:
    if not text or not text.strip():
        return [0.0] * 1536

    client = _get_client()
    if client is None:
        logger.info("embedder_unavailable", reason="no_openai_api_key")
        return [0.0] * 1536

    try:
        response = await client.embeddings.create(
            model=settings.openai_embedding_model,
            input=[text[:8000]],
        )
        vector = response.data[0].embedding
        if len(vector) < 1536:
            vector.extend([0.0] * (1536 - len(vector)))
        return vector[:1536]
    except Exception as e:
        logger.error("embedding_failed", error=str(e))
        return [0.0] * 1536
