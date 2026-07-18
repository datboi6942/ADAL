import asyncio
import re
from datetime import UTC, datetime

from adal.llm.client import _resolve_sub_model, chat_completion


async def generate_export_filename(query: str, content_preview: str) -> str:
    """Generate a descriptive filename using the LLM sub-model (non-thinking, fast).

    Falls back to timestamp + session ID prefix if the LLM call fails.
    """
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")

    try:
        model = _resolve_sub_model()
        if not model:
            raise ValueError("No sub-model configured")

        preview = content_preview.strip()[:600]
        system = (
            "You name files. Output ONLY a short, descriptive filename — "
            "no extension, no quotes, no commentary. Use lowercase with underscores. "
            "Max 50 characters. Example: synthesis_of_aspirin_from_salicylic_acid"
        )
        user = (
            f"Research query: {query[:200]}\n\n"
            f"Paper content begins:\n{preview[:600]}\n\n"
            "Filename:"
        )

        response = await asyncio.wait_for(
            chat_completion(
                system_prompt=system,
                user_message=user,
                model=model,
                thinking_enabled=False,
                max_tokens=64,
            ),
            timeout=5.0,
        )

        name = response.content.strip().strip('"').strip("'").replace("\n", " ")
        name = re.sub(r"[^a-zA-Z0-9_\- ]", "", name).strip()
        name = re.sub(r"\s+", "_", name)[:50].strip("_-")

        if name:
            return f"{name}_{ts}"
    except Exception:
        pass

    return f"adal_export_{ts}"
