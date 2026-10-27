"""Anthropic Messages API backend (streaming, server-side web search, pause_turn)."""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from . import usage as U
from .types import DEFAULT_MODEL, LLMError, Request, Response

WEB_SEARCH_TOOL = "web_search_20260318"   # dynamic filtering of results
MAX_PAUSE_CONTINUATIONS = 6
# Server-side refusal fallback: routes a refused request to a model that can answer it.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")


def make_client(api_key: str | None = None):
    import anthropic

    # The SDK reads ANTHROPIC_API_KEY (or an `ant auth login` profile) when api_key is None.
    return anthropic.Anthropic(api_key=api_key, max_retries=5, timeout=900)


def build_params(req: Request) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for img in req.images:
        if len(req.images) > 1:
            content.append({"type": "text", "text": f"Image: {img.name}"})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": img.media_type, "data": img.data_b64}})
    if req.cache_prefix:
        # Its own block with the breakpoint on it: everything up to here is cached and
        # req.prompt, which differs per call, stays outside the cached prefix.
        content.append({"type": "text", "text": req.cache_prefix,
                        "cache_control": {"type": "ephemeral"}})
    content.append({"type": "text", "text": req.prompt})

    model = req.model or DEFAULT_MODEL
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": req.max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    if req.system:
        params["system"] = req.system
    # Thinking is adaptive and always on for current models: effort is the only control.
    # Never send temperature/top_p/top_k or a thinking budget (rejected).
    if req.effort:
        params["output_config"] = {"effort": req.effort}
    if req.web_search:
        ws = req.web_search
        tool: dict[str, Any] = {"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": ws.max_uses}
        if ws.allowed_domains:
            tool["allowed_domains"] = ws.allowed_domains
        if ws.blocked_domains:
            tool["blocked_domains"] = ws.blocked_domains
        params["tools"] = [tool]
    if model in FALLBACK_MODELS:
        params["betas"] = [FALLBACK_BETA]
        params["fallbacks"] = "default"
    return params


def _collect(msg: Any, usage: dict, text_parts: list[str], sources: dict[str, str],
             searches: list[str]) -> None:
    """Fold one Message's text, cited and searched URLs, queries and usage into the totals."""
    U.add_api_usage(usage, msg.usage)
    for block in msg.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)
            for cit in getattr(block, "citations", None) or []:
                url = getattr(cit, "url", None)
                if url:
                    sources.setdefault(url, getattr(cit, "title", None) or url)
        elif btype == "server_tool_use" and getattr(block, "name", "") == "web_search":
            query = (getattr(block, "input", None) or {}).get("query")
            if query:
                searches.append(query)
        elif btype == "web_search_tool_result":
            items = getattr(block, "content", None)
            if isinstance(items, list):   # an error result is a single object, not a list
                for item in items:
                    url = getattr(item, "url", None)
                    if url and getattr(item, "type", "") == "web_search_result":
                        sources.setdefault(url, getattr(item, "title", None) or url)


def run(req: Request, client: Any = None, *, resume: Any = None) -> Response:
    """One request, continuing pause_turn up to MAX_PAUSE_CONTINUATIONS times.

    `resume` is a paused Message from a batch: the turn continues from it here, with its
    text, sources and usage counted, and without the server-side fallback, so the model
    that started the turn finishes it."""
    client = client or make_client()
    params = batch_params(req) if resume is not None else build_params(req)
    messages = params.pop("messages")
    t0 = time.time()

    text_parts: list[str] = []
    sources: dict[str, str] = {}
    searches: list[str] = []
    usage = U.empty()
    stop_reason = None
    model = params["model"]
    stream_api = client.beta.messages if "betas" in params else client.messages
    if resume is not None:
        _collect(resume, usage, text_parts, sources, searches)
        model = getattr(resume, "model", None) or model
        messages = messages + [{"role": "assistant", "content": resume.content}]

    for _ in range(MAX_PAUSE_CONTINUATIONS + 1):
        with stream_api.stream(messages=messages, **params) as stream:
            response = stream.get_final_message()
        stop_reason = response.stop_reason
        model = getattr(response, "model", None) or model
        _collect(response, usage, text_parts, sources, searches)
        if stop_reason != "pause_turn":
            break
        # Long search turns can pause; resend the assistant turn unchanged to continue
        # (thinking blocks must be echoed back unmodified).
        messages = messages + [{"role": "assistant", "content": response.content}]

    if stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise LLMError(f"model refused: {getattr(details, 'category', None) or 'unspecified'}")

    return Response(
        text="".join(text_parts).strip(),
        backend="api",
        model=model,
        sources=[{"url": u, "title": t} for u, t in sources.items()],
        searches=searches,
        usage=usage,
        stop_reason=stop_reason,
        seconds=round(time.time() - t0, 1),
    )


# ---- Message Batches ---------------------------------------------------------------
# 50% off every token, results within 24 h (most within 1 h). Each item is single-shot:
# a search turn that pauses is finished synchronously by run(resume=...), at standard
# price for the continuation only. There is no server-side refusal fallback, so a refusal
# comes back as that item's LLMError and the caller decides whether to ask again without
# the batch. Web search requests are billed per search either way.

BATCH_CHUNK = 10_000      # well under the 100,000-request / 256 MB limit per batch


def batch_params(req: Request) -> dict[str, Any]:
    """build_params() as the Batches API accepts it."""
    params = build_params(req)
    params.pop("betas", None)       # the server-side fallback beta and parameter are
    params.pop("fallbacks", None)   # rejected by the Batches API
    return params


def _batch_response(msg: Any, seconds: float) -> Response | LLMError:
    if msg.stop_reason == "refusal":
        details = getattr(msg, "stop_details", None)
        return LLMError(f"model refused: {getattr(details, 'category', None) or 'unspecified'}")
    usage = U.empty()
    text_parts: list[str] = []
    sources: dict[str, str] = {}
    searches: list[str] = []
    _collect(msg, usage, text_parts, sources, searches)
    return Response(text="".join(text_parts).strip(), backend="api-batch", model=msg.model,
                    sources=[{"url": u, "title": t} for u, t in sources.items()],
                    searches=searches, usage=usage, stop_reason=msg.stop_reason, seconds=seconds)


def run_batch(reqs: list[Request], client: Any = None, *, poll: float = 30,
              state_path: Any = None, label: str = "batch",
              log: Any = None) -> list[Response | LLMError]:
    """Run requests through the Message Batches API. Returns one Response or LLMError per
    request, in request order.

    `state_path` (a Path) records the submitted batch ids. A process that dies while
    waiting -- batches can take hours -- re-attaches to the same batches on restart
    instead of submitting, and paying for, the requests again. The file is keyed by a
    hash of the request bodies, so a changed request set never re-attaches to stale ids.
    """
    import hashlib
    import json
    import sys
    from pathlib import Path

    log = log or (lambda m: print(f"[media-kit] {m}", file=sys.stderr))
    client = client or make_client()
    if not reqs:
        return []
    params = [batch_params(r) for r in reqs]
    digest = hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16]
    chunks = [list(range(i, min(i + BATCH_CHUNK, len(reqs)))) for i in range(0, len(reqs), BATCH_CHUNK)]

    state: dict[str, Any] = {}
    sp = Path(state_path) if state_path else None
    if sp and sp.exists():
        state = json.loads(sp.read_text())
        if state.get("digest") != digest:
            state = {}
    ids: list[str] = state.get("batch_ids") or []
    if len(ids) != len(chunks):
        ids = []
        for chunk in chunks:
            b = client.messages.batches.create(requests=[
                {"custom_id": f"r{i}", "params": params[i]} for i in chunk])
            ids.append(b.id)
        if sp:
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(json.dumps({"digest": digest, "batch_ids": ids, "label": label,
                                      "requests": len(reqs), "submitted": time.time()}, indent=1))
        log(f"{label}: submitted {len(reqs)} requests as {len(ids)} batch(es): {', '.join(ids)}")
    else:
        log(f"{label}: re-attached to {len(ids)} batch(es) from {sp.name}")

    t0 = time.time()
    pending = set(ids)
    while pending:
        for bid in sorted(pending):
            b = client.messages.batches.retrieve(bid)
            if b.processing_status == "ended":
                pending.discard(bid)
            else:
                c = b.request_counts
                log(f"{label}: {bid} {b.processing_status}, processing {c.processing}, "
                    f"succeeded {c.succeeded}, errored {c.errored}; {int(time.time() - t0)}s")
        if pending:
            time.sleep(poll)

    out: list[Response | LLMError | None] = [None] * len(reqs)
    elapsed = round(time.time() - t0, 1)
    paused: list[tuple[int, Any]] = []
    for bid in ids:
        for res in client.messages.batches.results(bid):
            i = int(res.custom_id[1:])
            kind = res.result.type
            if kind == "succeeded" and res.result.message.stop_reason == "pause_turn":
                paused.append((i, res.result.message))
            elif kind == "succeeded":
                out[i] = _batch_response(res.result.message, elapsed)
            elif kind == "errored":
                err = getattr(res.result, "error", None)
                out[i] = LLMError(f"batch item errored: {getattr(err, 'type', None) or err}")
            else:                                   # canceled | expired
                out[i] = LLMError(f"batch item {kind}")
    if paused:
        log(f"{label}: {len(paused)} search turn(s) paused in the batch; finishing them synchronously")
    for i, msg in paused:
        try:
            r = run(reqs[i], client, resume=msg)
            # usage covers the whole turn; usage["batched"] is the part billed at the batch
            # rate, so a caller can price the two parts apart.
            batched = U.empty()
            U.add_api_usage(batched, msg.usage)
            out[i] = dataclasses.replace(r, backend="api-batch+api", usage={**r.usage, "batched": batched},
                                         seconds=round(elapsed + r.seconds, 1))
        except LLMError as e:
            out[i] = e
        except Exception as e:  # noqa: BLE001 -- one failed continuation must not lose the rest
            out[i] = LLMError(f"continuing a paused batch turn failed: {type(e).__name__}: {e}")
    return [x if x is not None else LLMError("no result returned for this request") for x in out]
