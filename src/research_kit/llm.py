"""Claude calls, with JSON parsing, disk caching and a thread pool.

Backend selection is the vendored backend's (`--backend`, env RESEARCH_KIT_LLM_BACKEND, else auto).
Every call is cached by (stage, key) as JSON under the run's `llm/` directory, so a
re-run only pays for calls that did not finish.

Batch mode (`batch=True`, the CLI's --batch) sends the calls of a batchable stage through
the Message Batches API at 50% of standard prices. pmap(..., batchable=True) runs the
stage twice: a collecting pass in which json_call records each uncached request instead
of making it, one batch for everything collected, whose results are written to the same
cache files, then the normal pass, which reads them. Anything the batch did not return
-- an error, an expiry, unparseable JSON -- is simply not cached, so the normal pass
makes that call synchronously with the usual retries. So is a refusal: batches have no
server-side fallback, and the synchronous call has it. Web-search calls batch too; a
search turn that pauses in the batch is finished synchronously by media-kit.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from research_kit.llm_backend import LLMError, Request, Response, WebSearch, ask, run_batch

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

# A dropped connection or a 5xx is worth another attempt; the SDK's own retries do not
# cover a stream that dies after the headers arrived. Matched by class name so this layer
# needs no httpx or anthropic import.
_TRANSIENT = {"RemoteProtocolError", "ReadError", "ReadTimeout", "WriteError", "ConnectError",
              "ConnectTimeout", "PoolTimeout", "APIConnectionError", "APITimeoutError",
              "InternalServerError", "ServiceUnavailableError", "OverloadedError"}


def is_transient(e: BaseException) -> bool:
    if type(e).__name__ in _TRANSIENT:
        return True
    status = getattr(e, "status_code", None)
    return isinstance(status, int) and status >= 500


def parse_json(text: str) -> Any:
    """Parse the last JSON object/array in a model reply (fenced or bare)."""
    blocks = _FENCE.findall(text)
    for cand in reversed(blocks or [text]):
        cand = cand.strip()
        for opener, closer in (("{", "}"), ("[", "]")):
            i, j = cand.find(opener), cand.rfind(closer)
            if i != -1 and j > i:
                try:
                    return json.loads(cand[i:j + 1])
                except json.JSONDecodeError:
                    continue
    raise ValueError(f"no JSON in reply: {text[:300]!r}")


class Deferred(Exception):
    """Raised by json_call in a collecting pass: the request was recorded for the batch."""


@dataclass
class LLM:
    run_dir: Path
    backend: str | None = None
    model_bulk: str = "claude-sonnet-5-5"     # per-paper extraction
    model_deep: str = "claude-opus-5-5"       # profiles, synthesis, ideas
    jobs: int = 6
    batch: bool = False                       # route batchable stages via Message Batches
    calls: list[dict[str, Any]] = field(default_factory=list)
    _collect: list[dict[str, Any]] | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _path(self, stage: str, key: str) -> Path:
        d = self.run_dir / "llm" / stage
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', key)[:120]}.json"

    def json_call(self, stage: str, key: str, prompt: str, *, system: str | None = None,
                  deep: bool = False, effort: str | None = None, web_search: int = 0,
                  max_tokens: int = 32000, retries: int = 2) -> Any:
        f = self._path(stage, key)
        if f.exists():
            return json.loads(f.read_text())["data"]
        # A refusal is recorded so a resumed run goes straight to the caller's fallback
        # instead of paying for the same refusal again. Delete the file to ask once more.
        refused = f.with_suffix(".refused.json")
        if refused.exists():
            raise RuntimeError(f"{stage}/{key} failed: {json.loads(refused.read_text())['error']}")
        if self._collect is not None:
            with self._lock:
                self._collect.append({"stage": stage, "key": key, "path": f, "req": Request(
                    prompt=prompt, system=system, model=self.model_deep if deep else self.model_bulk,
                    effort=effort, max_tokens=max_tokens, tag=f"research-kit.{stage}",
                    web_search=WebSearch(max_uses=web_search) if web_search else None)})
            raise Deferred(key)
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = ask(prompt, system=system, backend=self.backend,
                        model=self.model_deep if deep else self.model_bulk,
                        effort=effort, max_tokens=max_tokens, tag=f"research-kit.{stage}",
                        web_search=WebSearch(max_uses=web_search) if web_search else None,
                        timeout=1800)
                data = parse_json(r.text)
            except (ValueError, LLMError) as e:
                last = e
                if isinstance(e, LLMError) and "refused" in str(e):
                    # A refusal is the same every time: retrying it only spends the call again.
                    print(f"[research-kit] {stage}/{key}: {e}; not retried", file=sys.stderr)
                    refused.write_text(json.dumps({"error": str(e), "model": self.model_deep
                                                   if deep else self.model_bulk}, indent=1))
                    break
                print(f"[research-kit] {stage}/{key}: {e}; retrying", file=sys.stderr)
                continue
            except Exception as e:
                # A connection that dies mid-stream used to end the whole run, discarding
                # every stage that had not been cached yet.
                if not is_transient(e):
                    raise
                last = e
                time.sleep(min(2 ** attempt * 5, 60))
                print(f"[research-kit] {stage}/{key}: {type(e).__name__}: {e}; retrying",
                      file=sys.stderr)
                continue
            rec = {"data": data, "sources": r.sources, "searches": r.searches,
                   "usage": r.usage, "model": r.model, "backend": r.backend}
            f.write_text(json.dumps(rec, indent=1))
            return data
        raise RuntimeError(f"{stage}/{key} failed: {last}")

    def sources(self, stage: str, key: str) -> list[dict[str, str]]:
        f = self._path(stage, key)
        return json.loads(f.read_text()).get("sources", []) if f.exists() else []

    def pmap(self, fn: Callable[[Any], Any], items: list[Any], label: str,
             batchable: bool = False) -> list[Any]:
        """Run fn over items in a thread pool; failed items return None (logged).

        batchable=True marks a stage whose calls are independent and tool-free. In batch
        mode those calls go out as one Message Batch first (see the module docstring)."""
        if batchable and self.batch:
            self._batch_pass(fn, items, label)
        return self._pmap(fn, items, label)

    def _batch_pass(self, fn: Callable[[Any], Any], items: list[Any], label: str) -> None:
        self._collect = []
        try:
            with ThreadPoolExecutor(self.jobs) as ex:
                for fut in [ex.submit(fn, it) for it in items]:
                    try:
                        fut.result()
                    except Exception:  # noqa: BLE001, S110 -- Deferred, or an error the real pass reports
                        pass
            todo = self._collect
        finally:
            self._collect = None
        if not todo:
            return
        stage = todo[0]["stage"]
        digest = hashlib.sha256("|".join(sorted(c["key"] for c in todo)).encode()).hexdigest()[:12]
        state = self.run_dir / "llm" / "_batches" / f"{re.sub(r'[^A-Za-z0-9_-]', '_', label)}-{digest}.json"
        results = run_batch([c["req"] for c in todo], backend="api", state_path=state, label=label,
                            log=lambda m: print(f"[research-kit] {m}", file=sys.stderr))
        ok = refused = failed = 0
        for c, r in zip(todo, results):
            f: Path = c["path"]
            if isinstance(r, Response):
                try:
                    data = parse_json(r.text)
                except ValueError:
                    failed += 1     # not cached: the normal pass re-asks synchronously
                    continue
                f.write_text(json.dumps({"data": data, "sources": r.sources, "searches": r.searches,
                                         "usage": r.usage, "model": r.model, "backend": r.backend}, indent=1))
                ok += 1
            elif "refused" in str(r):
                # Not recorded as a refusal: batches have no server-side fallback, so the
                # synchronous pass asks once more with it before the caller falls back.
                refused += 1
            else:
                failed += 1
        print(f"[research-kit] {label}: batch returned {ok} of {len(todo)} for {stage}; "
              f"{refused} refused and {failed} failed, left for the synchronous pass", file=sys.stderr)

    def _pmap(self, fn: Callable[[Any], Any], items: list[Any], label: str) -> list[Any]:
        out: list[Any] = [None] * len(items)
        with ThreadPoolExecutor(self.jobs) as ex:
            futs = {ex.submit(fn, it): i for i, it in enumerate(items)}
            done = 0
            for fut in as_completed(futs):
                i = futs[fut]
                try:
                    out[i] = fut.result()
                except Exception as e:  # keep going; one bad batch should not sink the run
                    if type(e).__name__ == "BudgetExhausted":
                        for f in futs:
                            f.cancel()
                        raise
                    print(f"[research-kit] {label} item {i} failed: {e}", file=sys.stderr)
                done += 1
                if done % max(1, len(items) // 10) == 0 or done == len(items):
                    print(f"[research-kit] {label}: {done}/{len(items)}", file=sys.stderr)
        return out

    def usage_summary(self) -> dict[str, Any]:
        tot: dict[str, Any] = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                               "cache_read_input_tokens": 0, "web_search_requests": 0, "by_model": {}}
        for f in (self.run_dir / "llm").rglob("*.json"):
            if f.parent.name == "_batches":     # batch ids, not calls
                continue
            rec = json.loads(f.read_text())
            u = rec.get("usage") or {}
            tot["calls"] += 1
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "web_search_requests"):
                tot[k] += u.get(k) or 0
            m = tot["by_model"].setdefault(rec.get("model") or "?", {"calls": 0, "in": 0, "out": 0})
            m["calls"] += 1
            m["in"] += u.get("input_tokens") or 0
            m["out"] += u.get("output_tokens") or 0
            if (rec.get("backend") or "").startswith("api-batch"):   # priced at 50%: keep them separable
                # "api-batch+api" is a search turn that paused in the batch and finished
                # synchronously; only usage["batched"] was billed at the batch rate.
                b = u.get("batched") or u
                m["batch_calls"] = m.get("batch_calls", 0) + 1
                m["batch_in"] = m.get("batch_in", 0) + (b.get("input_tokens") or 0)
                m["batch_out"] = m.get("batch_out", 0) + (b.get("output_tokens") or 0)
        return tot
