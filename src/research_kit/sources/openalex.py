"""OpenAlex client: authors, works, abstracts, references and citing works.

OpenAlex needs an API key for real use (free; https://help.openalex.org/api/authentication/).
Keyless requests share a tiny per-IP daily budget. The key comes from `api_key=` or env
OPENALEX_API_KEY and is sent as a Bearer header (never written to the cache key or logs).
Every response is cached on disk under `cache_dir` so a re-run makes no network calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable

import httpx

BASE = "https://api.openalex.org"
WORK_FIELDS = ",".join([
    "id", "doi", "title", "publication_year", "type", "cited_by_count", "authorships",
    "primary_location", "abstract_inverted_index", "primary_topic", "topics", "keywords",
    "referenced_works", "open_access", "biblio",
])


class BudgetExhausted(RuntimeError):
    """OpenAlex daily budget is spent; retrying before the reset only wastes time."""


def short_id(oa_id: str | None) -> str:
    """'https://openalex.org/W123' -> 'W123'."""
    return (oa_id or "").rsplit("/", 1)[-1]


def abstract_text(inv: dict[str, list[int]] | None) -> str:
    """Rebuild an abstract from OpenAlex's inverted index."""
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


class OpenAlex:
    def __init__(self, cache_dir: Path, mailto: str | None = None, min_interval: float = 0.12,
                 api_key: str | None = None):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.mailto = mailto or os.environ.get("OPENALEX_MAILTO")
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()
        key = api_key or os.environ.get("OPENALEX_API_KEY")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.http = httpx.Client(timeout=60, follow_redirects=True, headers=headers)

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        if self.mailto:
            params["mailto"] = self.mailto
        key = hashlib.sha1(json.dumps([path, sorted(params.items())], default=str).encode()).hexdigest()
        f = self.cache / f"{key}.json"
        if f.exists():
            return json.loads(f.read_text())
        for attempt in range(6):
            with self._lock:
                wait = self.min_interval - (time.time() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self._last = time.time()
            r = self.http.get(f"{BASE}{path}", params=params)
            if r.status_code == 429:
                retry = float(r.headers.get("retry-after") or 0)
                if retry > 120 or r.headers.get("x-ratelimit-remaining-usd") == "0":
                    raise BudgetExhausted(f"OpenAlex budget used up (resets in {retry / 3600:.1f} h): "
                                          f"{(r.json() if r.content else {}).get('message', '')[:200]}")
                time.sleep(max(retry, 2 ** attempt))
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            data = r.json()
            f.write_text(json.dumps(data))
            return data
        r.raise_for_status()
        return {}

    def paged(self, path: str, limit: int | None = None, **params: Any) -> Iterable[dict[str, Any]]:
        cursor, n = "*", 0
        while cursor:
            d = self.get(path, cursor=cursor, **{"per-page": 200, **params})
            for item in d.get("results", []):
                yield item
                n += 1
                if limit and n >= limit:
                    return
            cursor = (d.get("meta") or {}).get("next_cursor")

    # ---- authors -------------------------------------------------------------
    def search_authors(self, name: str, n: int = 10) -> list[dict[str, Any]]:
        return self.get("/authors", search=name, **{"per-page": n}).get("results", [])

    def author(self, aid: str) -> dict[str, Any]:
        return self.get(f"/authors/{short_id(aid)}")

    def institution(self, iid: str) -> dict[str, Any]:
        return self.get(f"/institutions/{short_id(iid)}")

    # ---- works ---------------------------------------------------------------
    def works_by_authors(self, author_ids: list[str]) -> list[dict[str, Any]]:
        ids = "|".join(short_id(a) for a in author_ids)
        return list(self.paged("/works", filter=f"author.id:{ids}", select=WORK_FIELDS,
                               sort="publication_year:desc"))

    def works_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        ids = [short_id(i) for i in ids]
        for k in range(0, len(ids), 50):
            chunk = "|".join(ids[k:k + 50])
            out += self.get("/works", filter=f"openalex:{chunk}", select=WORK_FIELDS,
                            **{"per-page": 50}).get("results", [])
        return out

    def citing_works(self, work_id: str, n: int = 25) -> list[dict[str, Any]]:
        return self.get("/works", filter=f"cites:{short_id(work_id)}", select=WORK_FIELDS,
                        sort="cited_by_count:desc", **{"per-page": n}).get("results", [])

    def search_works(self, query: str, n: int = 25, since: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"search": query, "select": WORK_FIELDS,
                                  "sort": "cited_by_count:desc", "per-page": n}
        if since:
            params["filter"] = f"from_publication_date:{since}-01-01"
        return self.get("/works", **params).get("results", [])
