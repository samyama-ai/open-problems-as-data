"""research-kit command line.

  research-kit run --domain "database systems research" \\
      --catalog catalogs/dbms --catalog-seed 40 --ground-domain cs \\
      --graph-version 1.11.0 --out runs/dbms --backend api --env-file .env
  research-kit run --domain "a field" --researcher "Family Name|Institution" \\
      --graph-version 1.11.0 --out runs/example --backend api --env-file .env
  research-kit graph   --out runs/dbms --graph-version 1.11.0   # rebuild graph + snapshot only
  research-kit ground  --out runs/graphs --ground-domain cs --batch    # (re)ground an existing run, rebuild its graph
  research-kit serve   SNAPSHOT.sgsnap --graph-version 1.11.0 [--port 18080]
"""

from __future__ import annotations

# The vocabulary catalogue ships with this repository: vocab/ holds catalog/export/<domain>.json
# and the fetcher for the vocabularies themselves. parents[3] is the repository root from
# src/research_kit/cli.py.

from pathlib import Path as _P
VOCAB = _P(__file__).resolve().parents[2] / "vocab"

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .graph import build as B
from .graph.samyama import Samyama, start_container
from .llm import LLM
from .pipeline import Config, Pipeline, Researcher, slug
from . import pipeline as PL
from .report import queries, write_report


def load_env(path: str | None) -> None:
    if not path:
        return
    for line in Path(path).read_text().splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and not k.startswith("#") and v and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")


def graph_stage(run_dir: Path, version: str, port: int, keep: bool, url: str | None,
                s3_prefix: str | None = None) -> None:
    state = json.loads((run_dir / "state.json").read_text())
    g = B.build(state)
    nf, ef = B.write(g, run_dir / "graph")
    st = B.stats(g)
    (run_dir / "graph" / "stats.json").write_text(json.dumps(st, indent=1))
    print(f"[research-kit] graph: {st['nodes']} nodes, {st['edges']} edges", file=sys.stderr)
    name = f"research-kit-{slug(run_dir.name)}"
    url = url or start_container(version, name, port)
    db = Samyama(url)
    loaded = db.load(nf, ef)
    snap = run_dir / f"{run_dir.name}.sgsnap"
    size = db.export_snapshot(snap)
    print(f"[research-kit] snapshot {snap} ({size:,} bytes); server has {loaded}", file=sys.stderr)
    results = []
    relabel = B.EVIDENCE_RELABEL if state.get("catalog") else None
    for title, q in queries(PL.use_preset(state["config"].get("preset", "materials")), relabel):
        try:
            results.append((title, q, db.query(q)))
        except RuntimeError as e:
            results.append((title, q, {"error": str(e)}))
    write_report(run_dir, state, st, loaded, snap, size, version, results)
    if s3_prefix:
        dest = f"{s3_prefix.rstrip('/')}/research-kit-{run_dir.name}.sgsnap"
        subprocess.run(["aws", "s3", "cp", str(snap), dest, "--only-show-errors"], check=True)
        print(f"[research-kit] uploaded {dest}", file=sys.stderr)
    if not keep and not os.environ.get("RESEARCH_KIT_KEEP"):
        os.system(f"docker rm -f {name} >/dev/null 2>&1")
    else:
        print(f"[research-kit] server running at {url} (container {name})", file=sys.stderr)


def ground_stage(a: argparse.Namespace) -> int:
    """Ground a finished run without re-running anything before it.

    Re-running `research-kit run` with --ground-domain would re-extract every paper whose
    cached answer was made with an older extraction prompt; this reads the run's saved
    canonical concepts instead, so the only model calls are the grounding ones. Usage goes to
    ground-usage.json, leaving the run's own usage.json as it was.
    """
    for f in a.env_file:
        load_env(f)
    state_path = a.out / "state.json"
    state = json.loads(state_path.read_text())
    gpath = a.out / "ground.json"
    if a.redo and gpath.exists():
        gpath.rename(a.out / "ground.previous.json")
    if gpath.exists():
        grounding = json.loads(gpath.read_text())
    else:
        cfg = Config(domain=state["config"]["domain"], researchers=[], run_dir=a.out,
                     preset=state["config"].get("preset", "materials"),
                     ground_domain=a.ground_domain, ontologies=a.ontologies)
        llm = LLM(a.out, backend=a.backend, model_bulk=a.model_bulk, model_deep=a.model_deep,
                  jobs=a.jobs, batch=a.batch)
        grounding = Pipeline(cfg, llm).ground(state["canonical"])
        gpath.write_text(json.dumps(grounding, indent=1, ensure_ascii=False))
        (a.out / "ground-usage.json").write_text(json.dumps(llm.usage_summary(), indent=1))
    state["ground"] = grounding
    state_path.write_text(json.dumps(state, indent=1, ensure_ascii=False))
    graph_stage(a.out, a.graph_version, a.port, a.keep_running, a.url, a.s3_prefix)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="research-kit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("run", "graph"):
        s = sub.add_parser(cmd)
        s.add_argument("--out", required=True, type=Path)
        s.add_argument("--graph-version", default="1.11.0")
        s.add_argument("--port", type=int, default=18080)
        s.add_argument("--url", help="use a running samyama-graph server instead of a container")
        s.add_argument("--keep-running", action="store_true")
        s.add_argument("--s3-prefix", help="upload the .sgsnap as <prefix>/research-kit-<run>.sgsnap, "
                                            "e.g. s3://your-bucket/snapshots")
        if cmd == "run":
            s.add_argument("--domain", required=True)
            s.add_argument("--researcher", action="append", default=[], help='"Name|Institution"')
            s.add_argument("--researchers-file", type=Path, help='one "Name|Institution" per line; # comments')
            s.add_argument("--preset", choices=sorted(PL.PRESETS), default="materials")
            s.add_argument("--max-seed-works", type=int, default=0, help="per researcher, most-cited first (0 = all)")
            s.add_argument("--recent-seed-works", type=int, default=20)
            s.add_argument("--citing-seed-papers", type=int, default=12)
            s.add_argument("--citing-per-paper", type=int, default=6)
            s.add_argument("--landmark-per-query", type=int, default=6)
            s.add_argument("--backend", choices=["auto", "cli", "api"], default=None)
            s.add_argument("--env-file", action="append", default=[],
                           help="read ANTHROPIC_API_KEY / OPENALEX_API_KEY from this .env (repeatable)")
            s.add_argument("--model-bulk", default="claude-sonnet-5-5")
            s.add_argument("--model-deep", default="claude-opus-5-5")
            s.add_argument("-j", "--jobs", type=int, default=6)
            s.add_argument("--refs-top", type=int, default=80)
            s.add_argument("--ideas", type=int, default=20)
            s.add_argument("--batch", action="store_true",
                           help="send the tool-free stages (extract, canonical, ground) through "
                                "the Message Batches API at 50%% of standard prices; API backend "
                                "only; each stage then waits for its batch, usually under an hour")
            s.add_argument("--ground-domain",
                           help="vocabulary-catalogue domain to ground concepts in (e.g. cs); "
                                "read from <--ontologies>/catalog/export/<domain>.json")
            s.add_argument("--ontologies", type=Path, default=VOCAB,
                           help="the vocabulary catalogue (default: vocab/ in this repository)")
            s.add_argument("--catalog", type=Path,
                           help="V3: a problem-catalog export (nodes.jsonl, edges.jsonl, meta.json; "
                                "see scripts/catalog_from_dbms_kg.py) carried in as the problem layer")
            s.add_argument("--catalog-seed", type=int, default=0,
                           help="V3: with no --researcher, seed this many from the catalog's authors")
            s.add_argument("--catalog-since", type=int, default=2018)
            s.add_argument("--mailto", default=os.environ.get("OPENALEX_MAILTO"))
    s = sub.add_parser("ground", help="ground an existing run's concepts in a vocabulary-catalogue "
                                       "domain, then rebuild its graph and snapshot; no other stage runs")
    s.add_argument("--out", required=True, type=Path, help="the run directory (has state.json)")
    s.add_argument("--ground-domain", required=True)
    s.add_argument("--ontologies", type=Path, default=VOCAB)
    s.add_argument("--redo", action="store_true", help="discard an existing ground.json first")
    s.add_argument("--backend", choices=["auto", "cli", "api"], default=None)
    s.add_argument("--env-file", action="append", default=[])
    s.add_argument("--model-bulk", default="claude-sonnet-5-5")
    s.add_argument("--model-deep", default="claude-opus-5-5")
    s.add_argument("-j", "--jobs", type=int, default=6)
    s.add_argument("--batch", action="store_true")
    s.add_argument("--graph-version", default="1.11.0")
    s.add_argument("--port", type=int, default=18080)
    s.add_argument("--url")
    s.add_argument("--keep-running", action="store_true")
    s.add_argument("--s3-prefix")
    s = sub.add_parser("bench", help="run a file of Cypher questions against a graph and score it")
    s.add_argument("cypher", type=Path, help='"// Qn · question" comment, then the query')
    s.add_argument("--snapshot", type=Path, help="import this .sgsnap into a fresh container")
    s.add_argument("--load-dir", type=Path, help="or load nodes.jsonl/edges.jsonl from this directory")
    s.add_argument("--url", help="or query a running server")
    s.add_argument("--graph-version", default="1.11.0")
    s.add_argument("--port", type=int, default=18090)
    s.add_argument("--out", type=Path, required=True, help="results .json (a .md is written beside it)")
    s.add_argument("--keep-running", action="store_true")
    s = sub.add_parser("serve")
    s.add_argument("snapshot", type=Path)
    s.add_argument("--graph-version", default="1.11.0")
    s.add_argument("--port", type=int, default=18080)
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        url = start_container(a.graph_version, f"research-kit-{slug(a.snapshot.stem)}", a.port)
        print(json.dumps(Samyama(url).import_snapshot(a.snapshot)))
        print(f"serving {a.snapshot} at {url}")
        return 0
    if a.cmd == "bench":
        from .bench import bench
        return bench(a)
    if a.cmd == "ground":
        return ground_stage(a)
    if a.cmd == "run":
        for f in a.env_file:
            load_env(f)
        specs = list(a.researcher)
        if a.researchers_file:
            specs += [l.strip() for l in a.researchers_file.read_text().splitlines()
                      if l.strip() and not l.lstrip().startswith("#")]
        if not specs and not (a.catalog and a.catalog_seed):
            ap.error("give --researcher or --researchers-file (or --catalog with --catalog-seed)")
        cfg = Config(domain=a.domain, researchers=[Researcher.parse(r) for r in specs],
                     run_dir=a.out, refs_top=a.refs_top, ideas=a.ideas, mailto=a.mailto,
                     preset=a.preset, max_seed_works=a.max_seed_works,
                     recent_seed_works=a.recent_seed_works, citing_seed_papers=a.citing_seed_papers,
                     citing_per_paper=a.citing_per_paper, landmark_per_query=a.landmark_per_query,
                     ground_domain=a.ground_domain, ontologies=a.ontologies,
                     catalog=a.catalog, catalog_seed=a.catalog_seed, catalog_since=a.catalog_since)
        if a.batch and a.backend == "cli":
            print("research-kit: --batch needs the API backend; drop --backend cli", file=sys.stderr)
            return 2
        llm = LLM(a.out, backend=a.backend, model_bulk=a.model_bulk, model_deep=a.model_deep,
                  jobs=a.jobs, batch=a.batch)
        Pipeline(cfg, llm).run()
        (a.out / "usage.json").write_text(json.dumps(llm.usage_summary(), indent=1))
    graph_stage(a.out, a.graph_version, a.port, a.keep_running, a.url, a.s3_prefix)
    return 0


if __name__ == "__main__":
    sys.exit(main())
