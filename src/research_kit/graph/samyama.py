"""Load nodes/edges into a samyama-graph container over HTTP and export a .sgsnap.

HTTP API (samyama-graph >= 1.10): POST /api/query {query, params}, POST /api/snapshot/export
(returns the .sgsnap bytes), GET /api/status. The container is started from
ghcr.io/samyama-ai/samyama-graph:<version> unless --url points at a running server.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

IMAGE = "ghcr.io/samyama-ai/samyama-graph"


def log(msg: str) -> None:
    print(f"[research-kit] {msg}", file=sys.stderr)


def port_owner(port: int) -> str | None:
    """The container already publishing `port`, if any."""
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
                         capture_output=True, text=True, check=False).stdout
    for line in out.splitlines():
        cname, _, ports = line.partition("\t")
        if f":{port}->" in ports:
            return cname
    return None


def check_port(port: int, name: str) -> None:
    """Fail before docker does, and say what is holding the port.

    The graph stage runs last. A port clash discovered by `docker run` surfaces as a
    CalledProcessError with the whole command echoed and no hint of the cause, after
    the eight paid stages have already completed.
    """
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return
        except OSError:
            pass
    owner = port_owner(port)
    if owner == name:
        return   # our own container from a previous run; docker rm -f handles it
    hint = f"container {owner!r} is publishing it" if owner else "another process is bound to it"
    raise RuntimeError(f"port {port} is in use: {hint}. "
                       f"Re-run with --port <free port>; every stage is cached, so only "
                       f"the graph stage repeats.")


def start_container(version: str, name: str, port: int, data_dir: Path | None = None) -> str:
    check_port(port, name)
    # Removing a container that is not there is expected, so check=False.
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    cmd = ["docker", "run", "-d", "--name", name, "-p", f"{port}:8080"]
    if data_dir:
        data_dir.mkdir(parents=True, exist_ok=True)
        cmd += ["-v", f"{data_dir.resolve()}:/data"]
    cmd += [f"{IMAGE}:{version}", "samyama", "--host", "0.0.0.0", "--data-path", "/data"]
    subprocess.run(cmd, check=True, capture_output=True)
    url = f"http://localhost:{port}"
    for _ in range(60):
        try:
            if httpx.get(f"{url}/api/status", timeout=2).status_code == 200:
                return url
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError(f"container {name} did not become healthy")


MAX_BODY = 1_500_000   # bytes per request; the server rejects larger bodies with 413


def _chunks(rows: list[dict], n: int) -> Iterator[list[dict]]:
    """At most n rows and about MAX_BODY bytes per request. Catalog problems carry pages
    of text, so a fixed row count overflows the server's body limit."""
    cur: list[dict] = []
    size = 0
    for r in rows:
        b = len(json.dumps(r, ensure_ascii=False, default=str).encode())
        if cur and (len(cur) >= n or size + b > MAX_BODY):
            yield cur
            cur, size = [], 0
        cur.append(r)
        size += b
    if cur:
        yield cur


def _clean(v: Any) -> Any:
    """Samyama properties are scalars or lists of scalars; anything nested becomes JSON text."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, list) and all(isinstance(x, (str, int, float, bool)) for x in v):
        return v
    return json.dumps(v, ensure_ascii=False)


class Samyama:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.http = httpx.Client(timeout=300)

    def status(self) -> dict[str, Any]:
        return self.http.get(f"{self.url}/api/status").json()

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self.http.post(f"{self.url}/api/query", json={"query": cypher, "params": params or {}})
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"error": r.text}
        if r.status_code >= 400 or data.get("error"):
            raise RuntimeError(f"query failed ({r.status_code}): {data.get('error') or r.text[:300]}\n{cypher[:200]}")
        return data

    def rows(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        return self.query(cypher, params).get("records", [])

    def load(self, nodes_file: Path, edges_file: Path, batch: int = 500) -> dict[str, int]:
        nodes = [json.loads(l) for l in nodes_file.open()]
        edges = [json.loads(l) for l in edges_file.open()]
        label_of = {n["id"]: n["label"] for n in nodes}
        by_label: dict[str, list[dict]] = defaultdict(list)
        for n in nodes:
            props = {k: _clean(v) for k, v in n.items() if k != "label" and v is not None}
            by_label[n["label"]].append(props)
        for label in by_label:
            self.query(f"CREATE INDEX ON :{label}(id)")
        t0 = time.time()
        for label, rows in by_label.items():
            for chunk in _chunks(rows, batch):
                self.query(f"UNWIND $rows AS r MERGE (n:{label} {{id: r.id}}) SET n += r",
                           {"rows": chunk})
        log(f"loaded {len(nodes)} nodes in {time.time() - t0:.1f}s")
        groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for e in edges:
            s, d = label_of.get(e["src"]), label_of.get(e["dst"])
            if s and d:
                props = {k: _clean(v) for k, v in e.items() if k not in ("src", "rel", "dst") and v is not None}
                groups[(s, e["rel"], d)].append({"s": e["src"], "t": e["dst"], "p": props})
        t0 = time.time()
        for (s, rel, d), rows in groups.items():
            for chunk in _chunks(rows, batch):
                self.query(f"UNWIND $rows AS r MATCH (a:{s} {{id: r.s}}), (b:{d} {{id: r.t}}) "
                           f"CREATE (a)-[e:{rel}]->(b) SET e += r.p", {"rows": chunk})
        log(f"loaded {sum(len(v) for v in groups.values())} edges in {time.time() - t0:.1f}s")
        st = self.status()["storage"]
        return {"nodes": st["nodes"], "edges": st["edges"]}

    def export_snapshot(self, out: Path) -> int:
        r = self.http.post(f"{self.url}/api/snapshot/export")
        r.raise_for_status()
        out.write_bytes(r.content)
        return len(r.content)

    def import_snapshot(self, path: Path) -> dict[str, Any]:
        with path.open("rb") as f:
            r = self.http.post(f"{self.url}/api/snapshot/import", files={"file": (path.name, f)})
        r.raise_for_status()
        return r.json()
