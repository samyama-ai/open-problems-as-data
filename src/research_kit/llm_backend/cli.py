"""Claude Code CLI backend (`claude -p`, subscription auth).

Each call runs isolated from the user's Claude Code setup: no settings files (so no
hooks or CLAUDE.md), no MCP servers, no saved session, and only the tools the request
needs (Read for images, WebSearch for web search).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import usage as U
from .types import LimitReached, LLMError, Request, Response

DEFAULT_SYSTEM = "You are a careful, capable assistant. Follow the user's instructions exactly."
# Env vars that would make the CLI bill an API key instead of the subscription.
_STRIP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
_LIMIT = re.compile(r"limit reached|hit your [\w -]*limit|usage limit|session limit|weekly limit"
                    r"|rate[ _-]?limit", re.I)
_EPOCH = re.compile(r"\|(\d{10})\b")


def binary() -> str:
    return os.environ.get("CLAUDE_BIN", "claude")


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}


@lru_cache(maxsize=1)
def available() -> bool:
    """True when the CLI is installed and logged in to a subscription."""
    if not shutil.which(binary()):
        return False
    try:
        out = subprocess.run([binary(), "auth", "status"], capture_output=True, text=True,
                             timeout=30, env=_env(), stdin=subprocess.DEVNULL).stdout
        return bool(json.loads(out).get("loggedIn"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def build_command(req: Request, image_paths: list[Path], workdir: Path) -> tuple[list[str], str]:
    """Return (argv, stdin prompt). Pure, so tests can check it without running anything."""
    tools = []
    if image_paths:
        tools.append("Read")
    if req.web_search:
        tools.append("WebSearch")
    cmd = [binary(), "-p", "--output-format", "stream-json", "--verbose",
           "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
           "--system-prompt", req.system or DEFAULT_SYSTEM,
           "--tools", ",".join(tools)]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    if image_paths:
        cmd += ["--add-dir", str(workdir)]
    if req.model:
        cmd += ["--model", req.model]
    if req.effort:
        cmd += ["--effort", req.effort]

    parts = []
    if image_paths:
        listing = "\n".join(f"- {p}" for p in image_paths)
        parts.append("Use the Read tool to view each of these images before you answer "
                     f"(they are the images this request refers to):\n{listing}")
    if req.web_search:
        ws = req.web_search
        rule = f"You may run at most {ws.max_uses} WebSearch calls."
        if ws.allowed_domains:
            rule += f" On every WebSearch call pass allowed_domains={json.dumps(ws.allowed_domains)}."
        if ws.blocked_domains:
            rule += f" On every WebSearch call pass blocked_domains={json.dumps(ws.blocked_domains)}."
        parts.append(rule)
    parts.append(req.prompt)
    # The prompt goes on stdin: variadic flags such as --add-dir would swallow a positional one.
    return cmd, "\n\n".join(parts)


def _domain_ok(url: str, req: Request) -> bool:
    ws = req.web_search
    host = (urlparse(url).hostname or "").lower()

    def match(domains):
        return any(host == d.lower() or host.endswith("." + d.lower()) for d in domains)

    if ws and ws.allowed_domains and not match(ws.allowed_domains):
        return False
    return not (ws and ws.blocked_domains and match(ws.blocked_domains))


def parse_stream(lines: list[str], req: Request) -> tuple[dict[str, Any] | None, str, list[str], dict[str, str]]:
    """Return (result event, model, searches, sources) from stream-json output."""
    result, model, searches, sources = None, req.model or "", [], {}
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            model = ev.get("model") or model
        elif kind == "assistant":
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "WebSearch":
                    q = (b.get("input") or {}).get("query")
                    if q:
                        searches.append(q)
        elif kind == "user":
            tur = ev.get("tool_use_result")
            if isinstance(tur, dict) and isinstance(tur.get("results"), list):
                for r in tur["results"]:
                    for item in (r.get("content") if isinstance(r, dict) else None) or []:
                        url = isinstance(item, dict) and item.get("url")
                        if url and _domain_ok(url, req):
                            sources.setdefault(url, item.get("title") or url)
        elif kind == "result":
            result = ev
    return result, model, searches, sources


def _limit_error(text: str) -> LimitReached | None:
    if not _LIMIT.search(text or ""):
        return None
    m = _EPOCH.search(text)
    return LimitReached(text.strip()[:300], float(m.group(1)) if m else None)


def run(req: Request) -> Response:
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="media-kit-") as tmp:
        workdir = Path(tmp)
        image_paths = []
        for i, img in enumerate(req.images):
            stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(img.name).stem)[:60] or "image"
            p = workdir / f"{i:02d}-{stem}{img.suffix()}"
            p.write_bytes(base64.standard_b64decode(img.data_b64))
            image_paths.append(p)
        cmd, prompt = build_command(req, image_paths, workdir)
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  timeout=req.timeout, cwd=workdir, env=_env())
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude CLI timed out after {req.timeout}s") from e

    result, model, searches, sources = parse_stream(proc.stdout.splitlines(), req)
    if result is None:
        err = (proc.stderr or proc.stdout or "").strip()
        raise _limit_error(err) or LLMError(f"claude CLI exit {proc.returncode}: {err[:500]}")
    if result.get("is_error"):
        text = str(result.get("result") or result.get("subtype") or "")
        if result.get("api_error_status") == 429:
            raise LimitReached(text[:300] or "rate limited (429)")
        raise _limit_error(text) or LLMError(f"claude CLI error: {text[:500]}")

    return Response(
        text=str(result.get("result") or "").strip(),
        backend="cli",
        model=model,
        sources=[{"url": u, "title": t} for u, t in sources.items()],
        searches=searches,
        usage=U.from_cli_result(result),
        stop_reason=result.get("stop_reason"),
        seconds=round(time.time() - t0, 1),
    )
