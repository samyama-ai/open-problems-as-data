"""Run a file of Cypher questions against a graph and record what each returns.

The question file is dbms-research-kg's benchmarks/scope_questions.cypher format: a
`// Qn · question` comment line, then the query on the following non-comment lines. A
question with no query (Q39 needs vector search) is recorded as skipped.

This records answers; it does not grade them. Grading V1 against V3 needs a person or
the KG's reference checker: the same row count can be right on one graph and wrong on
the other, because V3 adds evidence-layer data on purpose.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from .graph.samyama import Samyama, start_container


def parse(path: Path) -> list[dict]:
    qs: list[dict] = []
    for line in path.read_text().splitlines():
        m = re.match(r"//\s*Q(\d+)\s*[·:.-]\s*(.+)", line)
        if m:
            qs.append({"n": int(m.group(1)), "question": m.group(2).strip(), "cypher": ""})
        elif qs and line.strip() and not line.lstrip().startswith("//"):
            qs[-1]["cypher"] = (qs[-1]["cypher"] + " " + line.strip()).strip()
    return qs


def short(rows: list[Any], cols: list[str], n: int = 3) -> str:
    out = []
    for r in rows[:n]:
        vals = r if isinstance(r, list) else [r]
        out.append("; ".join(f"{c} {str(v)[:60]}" for c, v in zip(cols, vals)))
    more = f" (+{len(rows) - n} more)" if len(rows) > n else ""
    return " / ".join(out) + more if out else "no rows"


def bench(a: Any) -> int:
    name = f"research-kit-bench-{a.port}"
    url = a.url
    if not url:
        url = start_container(a.graph_version, name, a.port)
        db = Samyama(url)
        if a.snapshot:
            print(json.dumps(db.import_snapshot(a.snapshot)), file=sys.stderr)
        elif a.load_dir:
            print(db.load(a.load_dir / "nodes.jsonl", a.load_dir / "edges.jsonl"), file=sys.stderr)
    db = Samyama(url)
    results = []
    for q in parse(a.cypher):
        if not q["cypher"]:
            results.append({**q, "rows": None, "ms": None, "answer": "skipped: no Cypher"})
            continue
        t0 = time.time()
        try:
            d = db.query(q["cypher"])
            rows, cols = d.get("records", []), d.get("columns", [])
            results.append({**q, "rows": len(rows), "ms": round((time.time() - t0) * 1000),
                            "columns": cols, "records": rows[:20], "answer": short(rows, cols)})
        except RuntimeError as e:
            results.append({**q, "rows": None, "ms": None, "error": str(e)[:300],
                            "answer": f"error: {str(e)[:120]}"})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"url": url, "snapshot": str(a.snapshot or a.load_dir or ""),
                                 "results": results}, indent=1, ensure_ascii=False, default=str))
    md = ["| # | Question | Rows | ms | Answer |", "|---|---|---:|---:|---|"]
    for r in results:
        ans = r["answer"].replace("|", "\\|").replace("\n", " ")
        md.append(f"| {r['n']} | {r['question']} | {r['rows'] if r['rows'] is not None else '–'} | "
                  f"{r['ms'] if r['ms'] is not None else '–'} | {ans} |")
    a.out.with_suffix(".md").write_text("\n".join(md) + "\n")
    errs = sum(1 for r in results if r.get("error"))
    print(f"[research-kit] bench: {len(results)} questions, {errs} errors -> {a.out}", file=sys.stderr)
    if not a.url and not a.keep_running and not os.environ.get("RESEARCH_KIT_KEEP"):
        os.system(f"docker rm -f {name} >/dev/null 2>&1")
    return 0
