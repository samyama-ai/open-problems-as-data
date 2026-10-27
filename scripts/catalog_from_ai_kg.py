"""Export an ai-research-kg build as a research-kit problem catalog.

    python3 scripts/catalog_from_ai_kg.py <kg-checkout> --out catalogs/ai

Reads `<kg-checkout>/data/graph.json`, the graph `python -m etl.build` writes without an
engine (its README, Quick start: download_data, then etl.build). Those are the rows the KG
loads into Samyama, so the catalog layer is the graph its 35 scope questions run on.
Writes (catalogs/ is gitignored):

    nodes.jsonl  {"id", "label", ...properties}        research-kit graph shape
    edges.jsonl  {"src", "rel", "dst", ...properties}
    meta.json    source repo, commit, as-of date, counts

Same output as scripts/catalog_from_dbms_kg.py. The two KGs build differently, so each has
its own exporter.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kg", type=Path, help="ai-research-kg checkout with data/graph.json")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    g = json.loads((a.kg / "data" / "graph.json").read_text())
    a.out.mkdir(parents=True, exist_ok=True)
    labels, rels, ids = Counter(), Counter(), set()
    with (a.out / "nodes.jsonl").open("w") as nf:
        for label, rows in g["nodes"].items():
            for r in rows:
                if r["id"] in ids:
                    sys.exit(f"duplicate node id {r['id']!r}")
                ids.add(r["id"])
                nf.write(json.dumps({"label": label, **r}, ensure_ascii=False) + "\n")
                labels[label] += 1
    with (a.out / "edges.jsonl").open("w") as ef:
        for _sl, src, rel, _dl, dst, props in g["edges"]:     # [src label, src, rel, dst label, dst, props]
            if src not in ids or dst not in ids:
                sys.exit(f"{rel}: dangling edge {src!r} -> {dst!r}")
            ef.write(json.dumps({"src": src, "rel": rel, "dst": dst, **(props or {})}, ensure_ascii=False) + "\n")
            rels[rel] += 1
    ds = (g["nodes"].get("DataSource") or [{}])[0]
    kg_commit = subprocess.run(["git", "-C", str(a.kg), "rev-parse", "HEAD"], capture_output=True,
                               text=True, check=False).stdout.strip() or None
    meta = {"name": "ai-research-kg", "kg_commit": kg_commit,
            "source_repo": ds.get("url"), "source_commit": ds.get("version"),
            "as_of": ds.get("source_date"),
            "retrieved_at": ds.get("retrieved_at"),
            "nodes": sum(labels.values()), "edges": sum(rels.values()),
            "labels": dict(labels.most_common()), "relations": dict(rels.most_common())}
    (a.out / "meta.json").write_text(json.dumps(meta, indent=1))
    print(f"{meta['nodes']} nodes, {meta['edges']} edges -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
