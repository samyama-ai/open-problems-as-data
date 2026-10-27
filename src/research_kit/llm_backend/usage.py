"""One usage shape for both backends, and an append-only log of every call.

Normalised keys (missing ones are 0 / None):
  input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens,
  thinking_tokens, web_search_requests, cost_usd (CLI reports it; API leaves None)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .types import Request, Response

KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
        "cache_creation_input_tokens", "thinking_tokens", "web_search_requests")


def empty() -> dict[str, Any]:
    return {**{k: 0 for k in KEYS}, "cost_usd": None}


def add_api_usage(total: dict[str, Any], usage: Any) -> None:
    """Accumulate one Messages API `usage` object into a normalised dict."""
    if usage is None:
        return
    data = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
    for k in KEYS[:4]:
        total[k] += data.get(k) or 0
    total["thinking_tokens"] += (data.get("output_tokens_details") or {}).get("thinking_tokens") or 0
    total["web_search_requests"] += (data.get("server_tool_use") or {}).get("web_search_requests") or 0


def from_cli_result(result: dict[str, Any]) -> dict[str, Any]:
    """Build a normalised dict from the CLI's final `result` event (sums `modelUsage`)."""
    total = empty()
    for m in (result.get("modelUsage") or {}).values():
        total["input_tokens"] += m.get("inputTokens") or 0
        total["output_tokens"] += m.get("outputTokens") or 0
        total["cache_read_input_tokens"] += m.get("cacheReadInputTokens") or 0
        total["cache_creation_input_tokens"] += m.get("cacheCreationInputTokens") or 0
        total["thinking_tokens"] += m.get("thinkingTokens") or 0
        total["web_search_requests"] += m.get("webSearchRequests") or 0
    total["cost_usd"] = result.get("total_cost_usd")
    return total


def log_path() -> Path | None:
    raw = os.environ.get("RESEARCH_KIT_USAGE_LOG", "~/.local/state/research-kit/usage.jsonl")
    return None if raw in ("", "0", "off") else Path(raw).expanduser()


def record(req: Request, resp: Response) -> None:
    """Append one line per call. Never raises: a broken log must not fail the work."""
    path = log_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"ts": round(time.time(), 1), "tag": req.tag, "backend": resp.backend,
                "model": resp.model, "effort": req.effort, "seconds": resp.seconds,
                **resp.usage}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass
