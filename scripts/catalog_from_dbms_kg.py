"""Export a dbms-research-kg build as a research-kit problem catalog.

    <kg-checkout>/.venv/bin/python scripts/catalog_from_dbms_kg.py <kg-checkout> --out catalogs/dbms

Runs inside the KG checkout's own environment: it calls that repo's `etl.loader.prepare`
on `build/source_catalog.json`, so the rows are exactly the typed rows the KG loads into
Samyama -- the ones its 48 scope questions were benchmarked on. Writes (54 MB for DBMS; catalogs/ is gitignored):

    nodes.jsonl  {"id", "label", ...properties}        research-kit graph shape
    edges.jsonl  {"src", "rel", "dst", ...properties}
    meta.json    source repo, commit, as-of date, counts

Build the KG first (its README, Quick start): download_data, source_parser.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

SRC_KEYS = ("source_node_id", "problem_id", "paper_id", "bound_id", "person_id")
DROP = {"id", "target_id", "source_label", "target_label", *SRC_KEYS}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kg", type=Path, help="dbms-research-kg checkout with build/source_catalog.json")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    sys.path.insert(0, str(a.kg.resolve()))
    from etl.loader import prepare  # the KG's own row builder

    cat = json.loads((a.kg / "build" / "source_catalog.json").read_text())
    data = prepare(cat)
    a.out.mkdir(parents=True, exist_ok=True)
    labels, rels, ids = Counter(), Counter(), set()
    with (a.out / "nodes.jsonl").open("w") as nf, (a.out / "edges.jsonl").open("w") as ef:
        for kind, rows in data.items():
            if not isinstance(rows, list):
                continue
            if kind != kind.upper():                  # node label
                for r in rows:
                    if r["id"] in ids:
                        sys.exit(f"duplicate node id {r['id']!r}")
                    ids.add(r["id"])
                    nf.write(json.dumps({"label": kind, **r}, ensure_ascii=False) + "\n")
                    labels[kind] += 1
            else:                                     # relationship type
                for r in rows:
                    src = next((r[k] for k in SRC_KEYS if r.get(k)), None)
                    if not src:
                        sys.exit(f"{kind}: no source key in {sorted(r)}")
                    props = {k: v for k, v in r.items() if k not in DROP}
                    ef.write(json.dumps({"src": src, "rel": kind, "dst": r["target_id"], **props},
                                        ensure_ascii=False) + "\n")
                    rels[kind] += 1
    src = cat.get("source") or {}
    kg_commit = subprocess.run(["git", "-C", str(a.kg), "rev-parse", "HEAD"], capture_output=True,
                               text=True, check=False).stdout.strip() or None
    meta = {"name": "dbms-research-kg", "kg_commit": kg_commit,
            "source_repo": src.get("repository"), "source_commit": src.get("actual_commit"),
            "as_of": src.get("source_date"),
            "retrieved_at": src.get("retrieved_at"),
            "nodes": sum(labels.values()), "edges": sum(rels.values()),
            "labels": dict(labels.most_common()), "relations": dict(rels.most_common())}
    (a.out / "meta.json").write_text(json.dumps(meta, indent=1))
    print(f"{meta['nodes']} nodes, {meta['edges']} edges -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
