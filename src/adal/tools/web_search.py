"""Web search and fetch tools for ADAL agents."""

import asyncio
import json
import random
import re
import time as _time
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse
from urllib.parse import urlparse as _urlparse

import httpx
import structlog

from adal.config import settings

logger = structlog.get_logger(__name__)

_last_request_time: float = 0.0
_query_cache: dict[str, str] = {}
_after_rate_limit: bool = False
_search_lock = asyncio.Lock()


def _get_blocked_hosts() -> set[str]:
    hosts = settings.blocked_fetch_hosts or "pubchem.ncbi.nlm.nih.gov"
    return {h.strip() for h in hosts.split(",") if h.strip()}


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]


def _clean_ddg_url(url: str) -> str:
    if "uddg=" in url or "l/?uddg=" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "uddg" in qs:
            return qs["uddg"][0]
    return url


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self.text.append(stripped)


async def async_search_web(query: str, max_results: int | None = None, _cache: dict | None = None) -> str:
    """Search the web and return structured results with retry on server
    errors. Falls back to Wikipedia opensearch on persistent DDG failure."""
    if max_results is None:
        max_results = settings.search_max_results

    logger.info("web_search", query=query[:100])

    cache = _cache if _cache is not None else _query_cache
    cache_key = f"{query.strip().lower()}|{max_results}"
    if cache_key in cache:
        logger.debug("web_search_cache_hit", query=query[:100])
        return cache[cache_key]

    async with _search_lock:
        global _last_request_time, _after_rate_limit
        elapsed = _time.time() - _last_request_time
        min_delay = settings.search_throttle_delay * (2.0 if _after_rate_limit else 1.0)
        if elapsed < min_delay:
            await asyncio.sleep(min_delay - elapsed)

        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.search_timeout)) as client:
            for attempt in range(settings.search_max_retries):
                try:
                    ua = random.choice(USER_AGENTS)
                    _last_request_time = _time.time()
                    resp = await client.get(
                        "https://html.duckduckgo.com/html/",
                        params={"q": query},
                        headers={"User-Agent": ua},
                        follow_redirects=True,
                    )
                    if resp.status_code in (202, 429):
                        _after_rate_limit = True
                        wait = 2 ** attempt
                        logger.info("web_search_rate_limited", attempt=attempt, wait=wait)
                        await asyncio.sleep(wait)
                        continue
                    if resp.status_code in (500, 502, 503, 504):
                        wait = 2 ** attempt
                        logger.info("web_search_server_error", attempt=attempt, status=resp.status_code, wait=wait)
                        await asyncio.sleep(wait)
                        continue
                    if resp.status_code != 200:
                        logger.info("web_search_non_200", status=resp.status_code, query=query[:100])
                        continue

                    results = _parse_ddg(resp.text, max_results)
                    if not results:
                        logger.warning("web_search_empty_results", query=query[:100])
                    for r in results:
                        r["url"] = _clean_ddg_url(r["url"])
                    result = json.dumps({"query": query, "results": results, "source": "duckduckgo"}, ensure_ascii=False)
                    cache[cache_key] = result
                    _after_rate_limit = False
                    return result

                except httpx.TimeoutException:
                    if attempt < 2:
                        logger.info("web_search_timeout_retry", attempt=attempt)
                        await asyncio.sleep(2 ** attempt)
                        continue
                except Exception as e:
                    if attempt < 2:
                        logger.info("web_search_error_retry", attempt=attempt, error=str(e))
                        await asyncio.sleep(2 ** attempt)
                        continue
                    logger.error("web_search_failed", error=str(e))
                    break

            logger.info("web_search_fallback", provider="wikipedia", query=query[:100])
            return await _wikipedia_search(query, max_results)


async def _wikipedia_search(query: str, max_results: int | None = None) -> str:
    if max_results is None:
        max_results = settings.search_max_results
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.search_timeout * 0.75)) as client:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": max_results,
                    "format": "json",
                },
                headers={"User-Agent": random.choice(USER_AGENTS)},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return json.dumps({"error": f"All search providers failed (DDG + Wikipedia). Status: {resp.status_code}", "query": query})

            data = resp.json()
            results = []
            if isinstance(data, list) and len(data) >= 4:
                titles = data[1]
                urls = data[3] if len(data) > 3 else []
                for i, title in enumerate(titles):
                    url = urls[i] if i < len(urls) else ""
                    results.append({
                        "title": title,
                        "url": url,
                        "snippet": f"Wikipedia article: {title}",
                    })
            return json.dumps({"query": query, "results": results, "source": "fallback:wikipedia"}, ensure_ascii=False)

    except Exception as e:
        logger.error("wikipedia_fallback_failed", error=str(e))
        return json.dumps({"error": f"All search providers failed: {e}", "query": query})


async def async_fetch_url(url: str, max_chars: int | None = None, _cache: dict | None = None) -> str:
    """Fetch and extract text content from a URL with retry and sanitization."""
    if max_chars is None:
        max_chars = settings.fetch_max_chars
    url = _clean_ddg_url(url)
    logger.info("web_fetch", url=url[:100])

    if _cache is not None:
        cache_key = url
        if cache_key in _cache:
            return _cache[cache_key]

    host = _urlparse(url).hostname or ""
    if host in _get_blocked_hosts():
        return json.dumps({"error": f"{host} blocks automated fetching; use web_search for summaries instead", "url": url})

    for attempt in range(settings.fetch_max_retries):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(settings.fetch_timeout)) as client:
                ua = random.choice(USER_AGENTS)
                resp = await client.get(
                    url,
                    headers={"User-Agent": ua},
                    follow_redirects=True,
                )
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.info("fetch_rate_limited", attempt=attempt, wait=wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code in (503, 502):
                    wait = 2 ** attempt
                    logger.info("fetch_server_error", attempt=attempt, wait=wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code != 200:
                    return json.dumps({"error": f"Fetch failed: HTTP {resp.status_code}", "url": url})

                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type:
                    parser = _TextExtractor()
                    parser.feed(resp.text)
                    text = " ".join(parser.text)[:max_chars]
                elif "application/pdf" in content_type:
                    return json.dumps({"error": "PDF content cannot be extracted as text; try a different URL", "url": url})
                else:
                    text = resp.text[:max_chars]

                result = json.dumps({"url": url, "content": text, "length": len(text)}, ensure_ascii=False)
                if _cache is not None and result:
                    _cache[url] = result
                return result

        except httpx.TimeoutException:
            if attempt < 2:
                logger.info("fetch_timeout_retry", attempt=attempt)
                await asyncio.sleep(2 ** attempt)
                continue
            return json.dumps({"error": "Fetch timed out after retries", "url": url})
        except Exception as e:
            if attempt < 2:
                logger.info("fetch_error_retry", attempt=attempt, error=str(e))
                await asyncio.sleep(2 ** attempt)
                continue
            logger.error("web_fetch_failed", error=str(e))
            return json.dumps({"error": str(e), "url": url})

    return json.dumps({"error": "Fetch failed after retries", "url": url})


def _parse_ddg(html: str, max_results: int) -> list[dict]:
    results = []
    link_pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i in range(min(len(links), max_results)):
        href, title_html = links[i]
        snippet = snippets[i] if i < len(snippets) else ""
        title = re.sub(r"<[^>]+>", "", title_html).strip()
        snippet = re.sub(r"<[^>]+>", "", snippet).strip()
        results.append({"title": title, "url": href, "snippet": snippet})

    return results


async def async_calculate(expression: str) -> str:
    safe_ns = {
        "math": __import__("math"),
        "np": __import__("numpy"),
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "len": len, "int": int, "float": float,
        "pow": pow, "range": range,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, safe_ns)
        return json.dumps({"expression": expression, "result": result})
    except Exception as e:
        return json.dumps({"expression": expression, "error": str(e)})


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for scientific information, data, literature references, "
                "chemical properties, synthesis procedures, spectroscopic data, physical constants, "
                "and any other real-world information needed for validation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query string (e.g., 'desoxybenzoin PubChem molecular weight', 'NaBH(OAc)3 reductive amination yield DCE'). Must be a plain string, not wrapped in a type annotation.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch and extract text content from a specific URL. "
                "WARNING: Cannot extract PDF content — skip .pdf links. "
                "PubChem blocks automated fetching — use web_search for compound summaries instead. "
                "Best for: Wikipedia, open-access papers, educational sites. "
                "Returns: plain text up to ~10000 characters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL string to fetch content from. Must be a plain string, not wrapped in a type annotation.",
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Evaluate a mathematical expression for exact arithmetic. "
                "Use for: stoichiometry calculations, yield percentages, mass/mole conversions, "
                "concentration/dilution, thermodynamic calculations. "
                "Available: math.* (log, sqrt, exp, etc.), numpy as np, abs, round, min, max, pow. "
                "Example: '2.5 * 180.16 / 0.85', 'math.log(0.05) * 8.314 * 298 / 1000'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "A single Python arithmetic expression to evaluate. No statements, no imports.",
                    },
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_EXECUTORS = {
    "web_search": async_search_web,
    "fetch_url": async_fetch_url,
    "calculate": async_calculate,
}
