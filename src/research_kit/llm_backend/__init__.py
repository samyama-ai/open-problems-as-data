"""One way to call Claude: the Claude Code CLI first, the Anthropic API as fallback.

    from research_kit.llm_backend import ask, Image, WebSearch
    r = ask("Describe this.", images=[Image.from_path("a.jpg")], web_search=WebSearch(5))
    r.text, r.sources, r.usage, r.backend

Backend choice, first match wins:
  1. `backend=` argument ("cli" | "api" | "auto")
  2. env RESEARCH_KIT_LLM_BACKEND
  3. auto: the CLI if it is installed and logged in, else the API.

A CLI usage-limit error never falls over to the API (that would spend API credit no one
asked for). It sleeps until the reset time (or RESEARCH_KIT_LIMIT_SLEEP seconds when the
reset is unknown, default 900) and retries, up to RESEARCH_KIT_LIMIT_MAX_WAIT seconds in
total (default 21600 = 6 h), then raises LimitReached.
"""

from __future__ import annotations

import os
import sys
import time

from . import api, cli
from . import usage as _usage
from .types import (
    DEFAULT_MODEL,
    EFFORTS,
    Image,
    LimitReached,
    LLMError,
    Request,
    Response,
    WebSearch,
)

__all__ = [
    "DEFAULT_MODEL",
    "EFFORTS",
    "Image",
    "LLMError",
    "LimitReached",
    "Request",
    "Response",
    "WebSearch",
    "ask",
    "choose_backend",
    "run",
    "run_batch",
]


def choose_backend(backend: str | None = None) -> str:
    choice = (backend or os.environ.get("RESEARCH_KIT_LLM_BACKEND") or "auto").lower()
    if choice not in ("auto", "cli", "api"):
        raise ValueError(f"unknown backend {choice!r} (use auto, cli or api)")
    if choice == "auto":
        return "cli" if cli.available() else "api"
    return choice


def _run_cli_with_limit_wait(req: Request) -> Response:
    sleep_default = float(os.environ.get("RESEARCH_KIT_LIMIT_SLEEP", "900"))
    max_wait = float(os.environ.get("RESEARCH_KIT_LIMIT_MAX_WAIT", "21600"))
    waited = 0.0
    while True:
        try:
            return cli.run(req)
        except LimitReached as e:
            wait = sleep_default
            if e.resets_at:
                wait = max(60.0, e.resets_at - time.time() + 60)
            if waited + wait > max_wait:
                raise
            print(f"[media-kit] CLI limit reached ({e}); sleeping {wait / 60:.0f} min "
                  f"(waited {waited / 60:.0f} of {max_wait / 60:.0f} min)", file=sys.stderr)
            time.sleep(wait)
            waited += wait


def run(req: Request, backend: str | None = None, client=None) -> Response:
    """Run one request. `client` is an Anthropic client override for the API backend."""
    which = choose_backend(backend)
    resp = _run_cli_with_limit_wait(req) if which == "cli" else api.run(req, client=client)
    _usage.record(req, resp)
    return resp


def ask(prompt: str, *, backend: str | None = None, client=None, **fields) -> Response:
    """Shorthand for run(Request(prompt, **fields))."""
    return run(Request(prompt=prompt, **fields), backend=backend, client=client)


def run_batch(reqs: list[Request], backend: str | None = None, client=None, **kw) -> list:
    """Run requests through the Message Batches API at 50% of standard prices.

    API backend only: the CLI has no batch mode, and silently running a batch one call at
    a time on the subscription would defeat the point. Returns one Response or LLMError
    per request, in order; see api.run_batch for state_path (crash re-attach) and poll.
    """
    which = choose_backend(backend)
    if which != "api":
        raise LLMError(f"batch mode needs the API backend; {which!r} was selected "
                       f"(pass backend='api' or set RESEARCH_KIT_LLM_BACKEND=api)")
    out = api.run_batch(reqs, client=client, **kw)
    for req, resp in zip(reqs, out):
        if isinstance(resp, Response):
            _usage.record(req, resp)
    return out
