import asyncio
import inspect
import json
import time as _time
from dataclasses import dataclass, field

import httpx
import structlog
from openai import AsyncOpenAI

from adal.config import settings
from adal.constants import VERBOSITY_HIGH, VERBOSITY_MED

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


def _resolve_sub_model() -> str:
    p = settings.llm_provider
    if p == "deepseek":
        return settings.deepseek_sub_model or settings.deepseek_model
    elif p == "openai":
        return settings.openai_sub_model or settings.openai_model
    elif p == "openrouter":
        return settings.openrouter_sub_model or settings.openrouter_model
    elif p == "ollama":
        return settings.ollama_sub_model or settings.ollama_model
    elif p == "custom":
        return settings.custom_sub_model or settings.custom_model
    return ""


def _provider_kwargs(gen_params: dict | None = None, thinking_enabled: bool = True) -> dict:
    kwargs: dict = {}
    if gen_params:
        kwargs.update({k: v for k, v in gen_params.items() if v is not None})
    if thinking_enabled and settings.llm_provider == "deepseek":
        kwargs["reasoning_effort"] = settings.reasoning_effort
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
    return kwargs


@dataclass
class LLMResponse:
    content: str
    reasoning: str | None = None
    usage: dict = field(default_factory=dict)
    was_forced: bool = False
    tool_turns_used: int = 0


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key, base_url, _ = _resolve_provider()
        _client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0,
                              timeout=httpx.Timeout(120.0, connect=10.0))
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


def _tool_failed(result_content: str) -> bool:
    if not result_content or not result_content.strip():
        return True
    lower = result_content.lower()
    if '"error"' in lower:
        return True
    if any(phrase in lower for phrase in
           ['http 403', 'http 404', 'timed out', 'pdf content cannot be extracted',
            'all search providers failed', 'status: 403', 'status: 404']):
        return True
    return False


async def chat_completion(
    system_prompt: str,
    user_message: str,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    gen_params: dict | None = None,
    thinking_enabled: bool = True,
    debug_callback=None,
    json_mode: bool = False,
) -> LLMResponse:
    client = get_client()
    _, _, default_model = _resolve_provider()
    tokens = max_tokens or settings.llm_max_tokens
    effective_model = model or default_model
    if debug_callback:
        await debug_callback("llm", "call",
            f"Model={effective_model} thinking={thinking_enabled} json_mode={json_mode} tokens={tokens} prompt_len={len(user_message)}",
            verbosity=VERBOSITY_MED)
    logger.debug("LLM request", model=effective_model, max_tokens=tokens, msg_preview=user_message[:200])

    kwargs = _provider_kwargs(gen_params, thinking_enabled=thinking_enabled)
    kwargs.update({
        "model": effective_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": tokens,
    })
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = await client.chat.completions.create(**kwargs)
    message = response.choices[0].message
    content = message.content or ""
    reasoning = getattr(message, "reasoning_content", None)
    usage = _extract_usage(response)

    if debug_callback:
        await debug_callback("llm", "response",
            f"Reply: {len(content)} chars, {usage.get('total_tokens', 0)} tokens "
            f"(prompt={usage.get('prompt_tokens', 0)}, comp={usage.get('completion_tokens', 0)})",
            verbosity=VERBOSITY_MED)
    if debug_callback and content:
        has_braces = '{' in content and '}' in content
        has_brackets = '[' in content and ']' in content
        if has_braces or has_brackets:
            await debug_callback("llm", "json_detect",
                f"Response contains {'JSON object' if has_braces else 'JSON array'} — {content[:200]}",
                verbosity=VERBOSITY_HIGH)

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
    max_tool_turns: int = settings.llm_max_tool_turns,
    gen_params: dict | None = None,
    thinking_enabled: bool = True,
    debug_callback=None,
    timeout_seconds: float | None = None,
    json_mode: bool = False,
) -> LLMResponse:
    client = get_client()
    _, _, default_model = _resolve_provider()
    tokens = max_tokens or settings.llm_max_tokens
    model_name = model or default_model
    _start_time = _time.time()

    _loop_deadline = None
    if timeout_seconds is not None:
        _loop_deadline = timeout_seconds - settings.forced_answer_time_budget

    if debug_callback:
        await debug_callback("llm", "call",
            f"Model={model_name} thinking={thinking_enabled} tokens={tokens} tools={len(tools)} turns={max_tool_turns}",
            verbosity=VERBOSITY_MED)

    base_kwargs = _provider_kwargs(gen_params, thinking_enabled=thinking_enabled)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    total_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
    final_reasoning: str | None = None
    final_content: str = ""
    tool_fail_streak = 0

    turn = 0
    for turn in range(max_tool_turns):
        if _loop_deadline is not None and (_time.time() - _start_time) > _loop_deadline:
            if debug_callback:
                await debug_callback("llm", "timeout",
                    f"Tool-loop deadline ({_loop_deadline:.0f}s) reached after {turn} turns "
                    f"(reserved {settings.forced_answer_time_budget:.0f}s for forced answer within "
                    f"{timeout_seconds:.0f}s outer deadline) — forcing final answer",
                    verbosity=1)
            break
        if debug_callback:
            await debug_callback("llm", "turn",
                f"Turn {turn+1}/{max_tool_turns} — requesting LLM completion (msg_count={len(messages)})",
                verbosity=VERBOSITY_MED)
        logger.debug("tool_turn", turn=turn + 1, model=model_name)
        create_kwargs: dict = {
            "model": model_name,
            "messages": messages,
            "tools": tools,
            "max_tokens": tokens,
            **base_kwargs,
        }
        if json_mode:
            create_kwargs["response_format"] = {"type": "json_object"}
        response = await client.chat.completions.create(**create_kwargs)
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
        if tool_calls:
            if len(tool_calls) > settings.max_parallel_tools:
                if debug_callback:
                    await debug_callback("llm", "parallel_limit",
                        f"Limiting {len(tool_calls)} tool calls to {settings.max_parallel_tools}",
                        verbosity=2)
                skipped = tool_calls[settings.max_parallel_tools:]
                tool_calls = tool_calls[:settings.max_parallel_tools]
                for tc in skipped:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"error": f"skipped — parallel limit ({settings.max_parallel_tools}) reached, re-request this tool next turn"}),
                    })
            if debug_callback:
                tool_names = [tc.function.name for tc in tool_calls]
                await debug_callback("llm", "tools_requested",
                    f"Turn {turn+1}: LLM requested {len(tool_calls)} tools: {', '.join(tool_names)}",
                    verbosity=VERBOSITY_MED)
        else:
            if debug_callback:
                await debug_callback("llm", "no_tools",
                    f"Turn {turn+1}: LLM returned content without tool calls — exiting tool loop",
                    verbosity=VERBOSITY_MED)
            break

        async def _run_one_tool(tc):
            executor = tool_executors.get(tc.function.name)
            if not executor:
                return {"tool_call_id": tc.id, "content": json.dumps({"error": f"Unknown tool: {tc.function.name}"})}
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
            return {"tool_call_id": tc.id, "content": result}

        results = await asyncio.gather(*[_run_one_tool(tc) for tc in tool_calls])
        any_failed = any(_tool_failed(r.get("content", "")) for r in results)
        if any_failed:
            tool_fail_streak += 1
        else:
            tool_fail_streak = 0

        if tool_fail_streak >= settings.tool_fail_streak_limit:
            if debug_callback:
                await debug_callback("llm", "fail_streak",
                    f"{tool_fail_streak} consecutive tool failures — forcing final answer",
                    verbosity=1)
            break
        for r in results:
            messages.append({
                "role": "tool",
                "tool_call_id": r["tool_call_id"],
                "content": r["content"],
            })

    if debug_callback and not final_content:
        stripped_count = sum(1 for m in messages if
            (isinstance(m, dict) and m.get('role') in ('tool',)) or
            (hasattr(m, 'tool_calls') and getattr(m, 'tool_calls', None)))
        await debug_callback("llm", "forced_answer",
            f"No content after {turn+1} tool turns — forcing final answer. "
            f"Stripping {stripped_count} tool messages, thinking DISABLED, temperature={settings.forced_answer_temperature}",
            verbosity=VERBOSITY_MED)

    was_forced = False

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
            _fail_count = sum(1 for m in messages
                if isinstance(m, dict) and m.get('role') == 'tool'
                and _tool_failed(str(m.get('content', ''))))
            _warning = ""
            if _fail_count > 0:
                _warning = (f" You attempted {len(messages)//2} tool calls over {turn+1} turns with "
                            f"{_fail_count} failures (HTTP errors, timeouts, dead URLs). "
                            f"Dead URLs and failed searches are NOT a reason to search for more. ")
            clean_messages.append({"role": "user", "content":
                _warning + "Output your final JSON response now. No tools, no reasoning, no disclaimers, no ethical commentary, no legal warnings — ONLY the scientific JSON content requested."})
            forced_kwargs: dict = {
                "model": _resolve_sub_model() or model_name,
                "messages": clean_messages,
                "max_tokens": min(tokens, 4096),
                "temperature": settings.forced_answer_temperature,
                "response_format": {"type": "json_object"},
            }
            response = await client.chat.completions.create(**forced_kwargs)
            msg = response.choices[0].message
            final_usage = _extract_usage(response)
            for k in total_usage:
                total_usage[k] += final_usage.get(k, 0)
            final_content = msg.content or ""
            was_forced = True
            if getattr(msg, "reasoning_content", None):
                final_reasoning = getattr(msg, "reasoning_content", None)
        except Exception as e:
            logger.error("forced_final_answer_failed", error=str(e))

    logger.debug("LLM response", length=len(final_content), usage=total_usage, tool_turns=turn + 1)
    return LLMResponse(content=final_content, reasoning=final_reasoning, usage=total_usage,
                       was_forced=was_forced, tool_turns_used=turn + 1)
