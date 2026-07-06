import inspect
import json
from dataclasses import dataclass, field

import structlog
from openai import AsyncOpenAI

from adal.config import settings

logger = structlog.get_logger(__name__)

_client: AsyncOpenAI | None = None


def _resolve_provider() -> tuple[str, str, str]:
    p = settings.llm_provider
    model = settings.llm_model
    if p == "deepseek":
        return settings.deepseek_api_key, settings.deepseek_base_url, model or settings.deepseek_model
    elif p == "openai":
        return settings.openai_api_key, "https://api.openai.com/v1", model or settings.openai_model
    elif p == "openrouter":
        return settings.openrouter_api_key, "https://openrouter.ai/api/v1", model or settings.openrouter_model
    elif p == "ollama":
        return "ollama", settings.ollama_base_url, model or settings.ollama_model
    elif p == "custom":
        return settings.custom_api_key, settings.custom_base_url, model or settings.custom_model
    raise ValueError(f"Unknown LLM provider: {p}")


def _provider_kwargs(gen_params: dict | None = None) -> dict:
    kwargs: dict = {}
    if gen_params:
        kwargs.update({k: v for k, v in gen_params.items() if v is not None})
    if settings.llm_provider == "deepseek":
        kwargs["reasoning_effort"] = settings.reasoning_effort
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
    return kwargs


@dataclass
class LLMResponse:
    content: str
    reasoning: str | None = None
    usage: dict = field(default_factory=dict)


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key, base_url, _ = _resolve_provider()
        _client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _client


def _extract_usage(response) -> dict:
    usage = {}
    if hasattr(response, "usage") and response.usage:
        u = response.usage
        usage["prompt_tokens"] = u.prompt_tokens or 0
        usage["completion_tokens"] = u.completion_tokens or 0
        usage["total_tokens"] = u.total_tokens or 0

        cached = 0
        if hasattr(u, "prompt_tokens_details") and u.prompt_tokens_details:
            cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
        usage["cached_tokens"] = cached
    return usage


def _calculate_cost(usage: dict) -> dict:
    prompt = usage.get("prompt_tokens", 0)
    cached = usage.get("cached_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    uncached_prompt = max(0, prompt - cached)

    input_cost = (uncached_prompt / 1_000_000) * settings.llm_input_price_per_mtok
    cached_cost = (cached / 1_000_000) * settings.llm_cached_price_per_mtok
    output_cost = (completion / 1_000_000) * settings.llm_output_price_per_mtok
    total = input_cost + cached_cost + output_cost

    return {
        "input_cost": input_cost,
        "cached_cost": cached_cost,
        "output_cost": output_cost,
        "total_cost": total,
    }


async def chat_completion(
    system_prompt: str,
    user_message: str,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    gen_params: dict | None = None,
) -> LLMResponse:
    client = get_client()
    _, _, default_model = _resolve_provider()
    tokens = max_tokens or settings.llm_max_tokens
    effective_model = model or default_model
    logger.debug("LLM request", model=effective_model, max_tokens=tokens, msg_preview=user_message[:200])

    kwargs = _provider_kwargs(gen_params)
    kwargs.update({
        "model": effective_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": tokens,
    })

    response = await client.chat.completions.create(**kwargs)
    message = response.choices[0].message
    content = message.content or ""
    reasoning = getattr(message, "reasoning_content", None)
    usage = _extract_usage(response)

    if reasoning:
        logger.debug("LLM reasoning", length=len(reasoning), preview=reasoning[:300])
    logger.debug("LLM response", length=len(content), usage=usage)

    return LLMResponse(content=content, reasoning=reasoning, usage=usage)


async def chat_completion_with_tools(
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    tool_executors: dict,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    max_tool_turns: int = 6,
    gen_params: dict | None = None,
) -> LLMResponse:
    client = get_client()
    _, _, default_model = _resolve_provider()
    tokens = max_tokens or settings.llm_max_tokens
    model_name = model or default_model

    base_kwargs = _provider_kwargs(gen_params)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    total_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
    final_reasoning: str | None = None
    final_content: str = ""

    for turn in range(max_tool_turns):
        logger.debug("tool_turn", turn=turn + 1, model=model_name)
        response = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tools,
            max_tokens=tokens,
            **base_kwargs,
        )
        msg = response.choices[0].message
        usage = _extract_usage(response)

        for k in total_usage:
            total_usage[k] += usage.get(k, 0)

        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning:
            logger.debug("LLM reasoning", turn=turn + 1, length=len(reasoning), preview=reasoning[:300])
            final_reasoning = reasoning

        if msg.content:
            final_content = msg.content

        messages.append(msg)

        tool_calls = msg.tool_calls
        if not tool_calls:
            break

        for tc in tool_calls:
            executor = tool_executors.get(tc.function.name)
            if executor:
                try:
                    args = json.loads(tc.function.arguments)
                    if inspect.iscoroutinefunction(executor):
                        result = await executor(**args)
                    else:
                        result = executor(**args)
                except TypeError as e:
                    try:
                        sig = inspect.signature(executor)
                        param_str = ", ".join(f"{n}: {p.annotation.__name__ if p.annotation != inspect.Parameter.empty else 'str'}" for n, p in sig.parameters.items())
                        hint = f"Correct signature: {tc.function.name}({param_str})"
                    except (ValueError, TypeError, AttributeError):
                        hint = f"Check the function signature for {tc.function.name}"
                    result = json.dumps({"error": str(e), "hint": hint, "function": tc.function.name})
                    logger.debug("tool_type_error", name=tc.function.name, error=str(e))
                except Exception as e:
                    result = json.dumps({"error": str(e)})
                logger.debug("tool_result", name=tc.function.name, result_preview=str(result)[:200])
            else:
                result = json.dumps({"error": f"Unknown tool: {tc.function.name}"})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            }            )

    if not final_content:
        logger.info("forcing_final_answer")
        try:
            clean_messages = []
            for m in messages:
                role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
                content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
                if role == "tool":
                    continue
                if role == "assistant" and hasattr(m, "tool_calls") and getattr(m, "tool_calls", None):
                    continue
                clean_messages.append({"role": role or "assistant", "content": content or ""})
            clean_messages.append({"role": "user", "content": "Output your final JSON response now. No tools, no reasoning, no disclaimers, no ethical commentary, no legal warnings — ONLY the scientific JSON content requested."})
            response = await client.chat.completions.create(
                model=model_name,
                messages=clean_messages,
                max_tokens=tokens,
                temperature=settings.forced_answer_temperature,
            )
            msg = response.choices[0].message
            final_usage = _extract_usage(response)
            for k in total_usage:
                total_usage[k] += final_usage.get(k, 0)
            final_content = msg.content or ""
            if getattr(msg, "reasoning_content", None):
                final_reasoning = getattr(msg, "reasoning_content", None)
        except Exception as e:
            logger.error("forced_final_answer_failed", error=str(e))

    logger.debug("LLM response", length=len(final_content), usage=total_usage, tool_turns=turn + 1)
    return LLMResponse(content=final_content, reasoning=final_reasoning, usage=total_usage)
