"""Backend-neutral request and response types for one Claude call."""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "claude-opus-5-5"
EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass
class Image:
    """An image to show the model. `name` labels it in the prompt and names its temp file."""

    name: str
    media_type: str
    data_b64: str

    @classmethod
    def from_path(cls, path: str | Path) -> "Image":
        p = Path(path)
        media_type = mimetypes.guess_type(p.name)[0] or "image/png"
        return cls(p.name, media_type, base64.standard_b64encode(p.read_bytes()).decode())

    def suffix(self) -> str:
        return {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "image/webp": ".webp"}.get(self.media_type, ".img")


@dataclass
class WebSearch:
    """Let the model search the web. The API enforces all three limits; the CLI is told
    them in the prompt, and sources outside allowed/blocked domains are dropped."""

    max_uses: int = 10
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None


@dataclass
class Request:
    prompt: str
    system: str | None = None
    images: list[Image] = field(default_factory=list)
    web_search: WebSearch | None = None
    model: str | None = None        # None: API uses DEFAULT_MODEL, CLI uses its configured model
    effort: str | None = None       # None: the model's default
    max_tokens: int = 32000         # API only; the CLI manages its own output budget
    timeout: float = 900            # seconds per call
    tag: str = ""                   # caller label for the usage log, e.g. "vision.notes"
    cache_prefix: str | None = None
    """The opening of the prompt that repeats across calls, cached after the first (API only).

    Caching is a prefix match, so this must be byte-identical every time and the varying
    part of the prompt goes in `prompt`. It only pays when several calls share it: the
    write costs 1.25x and each read 0.1x, so one call that never repeats costs more with
    it than without. Short prefixes do not cache at all -- the model's minimum is 1024 to
    4096 tokens, and a shorter one is silently ignored. Check it worked by reading
    `usage['cache_read_input_tokens']`.
    """


@dataclass
class Response:
    text: str
    backend: str                    # "cli" | "api"
    model: str
    sources: list[dict[str, str]] = field(default_factory=list)   # [{"url", "title"}]
    searches: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)          # see usage.normalise
    stop_reason: str | None = None
    seconds: float = 0.0


class LLMError(RuntimeError):
    """A call failed in a way that retrying the same backend will not fix."""


class LimitReached(LLMError):
    """The CLI's subscription usage limit was hit. `resets_at` is a Unix time when known."""

    def __init__(self, message: str, resets_at: float | None = None):
        super().__init__(message)
        self.resets_at = resets_at
