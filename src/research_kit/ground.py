"""Ground canonical concepts in a vocabulary from the catalogue under vocab/.

The catalog is upgraded before a domain is researched (samyama-cloud
wiki/decisions/ontology-first-kg-bootstrapping.md). This stage reads what it knows
about the run's domain -- catalog/export/<domain>.json -- loads every vocabulary
that has been built into loadable form, and places each canonical concept against it:

    same      the concept IS this ontology class
    narrower  the concept is a kind of this class (the most specific one offered)
    none      nothing offered fits

Most research concepts are far more specific than an upper ontology, so `narrower`
is the relation that does the work: it replaces a model-invented BROADER parent with
a class that has a publisher behind it. Measured on the materials run against EMMO
1.0.3, only ~1% of concepts have every content word inside a single EMMO class.

Guardrail: an unaligned concept is never dropped and never forced onto a near miss.
It stays in the graph with grounded=false, and the alignment rate is reported as it
is. The model may only choose a target from the candidates it was shown.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_STOP = {
    "a", "an", "the", "of", "and", "or", "for", "in", "on", "to", "with", "by", "from",
    "based", "using", "via", "into", "over", "under", "between", "within", "new", "novel",
    "high", "low",
}


def words(s: str) -> list[str]:
    """Content words, CamelCase split and lightly stemmed: 'ElectricConductivity' ->
    ['electric', 'conductivity']."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    out = []
    for w in re.split(r"[^a-z0-9]+", s.lower()):
        if len(w) < 3 or w in _STOP:
            continue
        out.append(re.sub(r"(ies|es|s)$", "", w) if len(w) > 4 else w)
    return out


@dataclass
class Vocab:
    id: str
    nodes: dict[str, dict] = field(default_factory=dict)
    parents: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    tag: str = ""                       # content hash, so a changed vocabulary misses the cache
    index: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    idf: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, vid: str, build_dir: Path) -> Vocab:
        v = cls(vid)
        nf, ef = build_dir / "nodes.jsonl", build_dir / "edges.jsonl"
        h = hashlib.sha256()
        for line in nf.read_text().splitlines():
            h.update(line.encode())
            n = json.loads(line)
            v.nodes[n["id"]] = n
        if ef.exists():
            for line in ef.read_text().splitlines():
                e = json.loads(line)
                if e.get("rel") == "BROADER":
                    v.parents[e["src"]].append(e["dst"])
        v.tag = h.hexdigest()[:10]
        v.reindex()
        return v

    def reindex(self) -> None:
        self.index, df = defaultdict(set), Counter()
        for nid, n in self.nodes.items():
            ws = set()
            for name in [n.get("name", "")] + (n.get("aliases") or []):
                ws |= set(words(name))
            for w in ws:
                self.index[w].add(nid)
                df[w] += 1
        total = max(1, len(self.nodes))
        self.idf = {w: math.log(total / c) + 1.0 for w, c in df.items()}

    @classmethod
    def merge(cls, vocabs: list[Vocab]) -> Vocab:
        """One vocabulary over several builds. EMMO's domain ontologies subclass EMMO core
        classes; built with a shared id prefix, their parent edges point at core ids, and
        only a merged view lets ancestors() walk from a battery class up into core."""
        if len(vocabs) == 1:
            return vocabs[0]
        m = cls("+".join(v.id for v in vocabs))
        for v in vocabs:
            for nid, n in v.nodes.items():
                m.nodes.setdefault(nid, {**n, "vocabulary": n.get("vocabulary") or v.id})
            for nid, ps in v.parents.items():
                for q in ps:
                    if q not in m.parents[nid]:
                        m.parents[nid].append(q)
        m.tag = hashlib.sha256("".join(v.tag for v in vocabs).encode()).hexdigest()[:10]
        m.reindex()
        return m

    def candidates(self, name: str, k: int = 10) -> list[str]:
        """Classes sharing content words with `name`, IDF-weighted, rarest overlap first."""
        score: Counter = Counter()
        for w in set(words(name)):
            for nid in self.index.get(w, ()):
                score[nid] += self.idf.get(w, 1.0)
        return [nid for nid, _ in score.most_common(k)]

    def label(self, nid: str) -> str:
        n = self.nodes[nid]
        par = [self.nodes[p]["name"] for p in self.parents.get(nid, [])[:2] if p in self.nodes]
        desc = (n.get("description") or "").replace("\n", " ")[:110]
        s = n["name"] + (f" (a kind of {', '.join(par)})" if par else "")
        return s + (f" -- {desc}" if desc else "")

    def ancestors(self, nid: str, limit: int = 12) -> list[str]:
        out, todo, seen = [], list(self.parents.get(nid, [])), {nid}
        while todo and len(out) < limit:
            p = todo.pop(0)
            if p in seen or p not in self.nodes:
                continue
            seen.add(p)
            out.append(p)
            todo.extend(self.parents.get(p, []))
        return out


class GroundingUnavailable(RuntimeError):
    pass


def locate(ontologies: Path, domain: str) -> tuple[dict, list[Vocab]]:
    """Read the catalog's export for `domain` and load every vocabulary built for it."""
    export = ontologies / "catalog" / "export" / f"{domain}.json"
    if not export.exists():
        known = sorted(p.stem for p in (ontologies / "catalog" / "export").glob("*.json"))
        raise GroundingUnavailable(f"no catalog export for domain {domain!r} at {export}. "
                                   f"Known domains: {', '.join(known) or 'none'}")
    spec = json.loads(export.read_text())
    wanted = list(dict.fromkeys((spec.get("grounded_by") or []) + (spec.get("candidates") or [])))
    vocabs, missing = [], []
    for vid in wanted:
        d = ontologies / "build" / vid
        if (d / "nodes.jsonl").exists():
            vocabs.append(Vocab.load(vid, d))
        else:
            missing.append(vid)
    if not vocabs:
        raise GroundingUnavailable(
            f"domain {domain!r} names {wanted or 'no vocabularies'}, but none is built under "
            f"{ontologies / 'build'}. Build it with vocab/vocab_to_graph.py: "
            f"python scripts/fetch_vocab.py <id> && uv run --with rdflib python -I "
            f"scripts/vocab_to_graph.py data/<id>-<version>/... --id <id> --out build/<id>")
    spec["_not_built"] = missing
    spec["_vocabularies"] = [{"id": v.id, "tag": v.tag, "classes": len(v.nodes)} for v in vocabs]
    return spec, [Vocab.merge(vocabs)]


def ground(llm: Any, canon: dict, vocabs: list[Vocab], domain_text: str,
           kind_words: dict[str, str], prompt: str, system: str,
           batch: int = 25, k: int = 10) -> dict:
    """Place every canonical concept. Returns the ground.json payload."""
    by_id = {nid: v for v in vocabs for nid in v.nodes}
    tag = "-".join(f"{v.id}{v.tag}" for v in vocabs)

    def cands(name: str) -> list[str]:
        merged: Counter = Counter()
        for v in vocabs:
            for rank, nid in enumerate(v.candidates(name, k)):
                merged[nid] += k - rank
        return [nid for nid, _ in merged.most_common(k)]

    from .pipeline import slug  # the graph's node-id normaliser: one verdict per node

    work, result, dupes = [], {}, []
    for kind, c in canon.items():
        result[kind] = {}
        first: dict[str, str] = {}
        for name in c.get("canonical") or {}:
            s = slug(name)
            if s in first:              # 'Ceramics' vs 'ceramics', or a trailing space
                dupes.append((kind, name, first[s]))
                continue
            first[s] = name
            cs = cands(name)
            if cs:
                work.append((kind, name, cs))
            else:
                result[kind][name] = {"grounded": False, "reason": "no candidate shares a word"}

    jobs = [work[i:i + batch] for i in range(0, len(work), batch)]

    def run(job: tuple[int, list]) -> list:
        i, items = job
        lines = []
        for j, (kind, name, cs) in enumerate(items):
            lines.append(f"[{j}] kind={kind_words.get(kind, kind)}  \"{name}\"")
            for m, nid in enumerate(cs, 1):
                lines.append(f"    {m}. {by_id[nid].label(nid)}")
        r = llm.json_call("ground", f"{tag}_{i}", prompt.format(
            domain=domain_text, items="\n".join(lines)), system=system, effort="low",
            max_tokens=16000) or {}
        return r.get("results") or []

    answers = llm.pmap(run, list(enumerate(jobs)), "ground", batchable=True)
    rejected = failed = 0
    for items, res in zip(jobs, answers):
        if res is None:
            # every retry failed: these were never judged, so do not record a verdict
            failed += len(items)
            for kind, name, _ in items:
                result[kind][name] = {"grounded": False, "reason": "grounding call failed"}
            continue
        got = {}
        for r in res or []:
            if isinstance(r, dict) and isinstance(r.get("i"), int):
                got[r["i"]] = r
        for j, (kind, name, cs) in enumerate(items):
            r = got.get(j) or {}
            rel, pick = r.get("relation"), r.get("candidate")
            if rel in ("same", "narrower") and isinstance(pick, int) and 1 <= pick <= len(cs):
                nid = cs[pick - 1]
                result[kind][name] = {"grounded": True, "relation": rel, "target": nid,
                                      "target_name": by_id[nid].nodes[nid]["name"],
                                      "vocabulary": by_id[nid].nodes[nid].get("vocabulary")
                                      or by_id[nid].id,
                                      "confidence": r.get("confidence")}
            else:
                if rel in ("same", "narrower"):
                    rejected += 1      # pointed outside the list it was shown: refuse it
                result[kind][name] = {"grounded": False,
                                      "reason": "model chose none" if rel == "none" or not r
                                      else "target outside the offered candidates"}

    for kind, name, same_as in dupes:
        result[kind][name] = {**result[kind][same_as], "duplicate_of": same_as}

    # Carry every target and its ancestor chain, so the graph build reads only the run
    # directory and never reaches into the vocabulary catalogue.
    classes: dict[str, dict] = {}
    for m in result.values():
        for x in m.values():
            if not x.get("grounded"):
                continue
            v = by_id[x["target"]]
            for nid in [x["target"]] + v.ancestors(x["target"]):
                if nid in classes:
                    continue
                n = v.nodes[nid]
                classes[nid] = {"name": n["name"], "vocabulary": n.get("vocabulary") or v.id,
                                "iri": n.get("iri"),
                                "description": n.get("description"),
                                "parents": [q for q in v.parents.get(nid, []) if q in v.nodes]}

    stats = summarize(result, rejected, failed)

    return {"vocabularies": [{"id": v.id, "tag": v.tag, "classes": len(v.nodes)} for v in vocabs],
            "concepts": result,
            "classes": classes,
            "stats": stats}


def summarize(result: dict, rejected: int = 0, failed: int = 0) -> dict:
    """Counts over distinct concepts: a duplicate_of entry shares its node's verdict
    and is not counted twice."""
    by_kind = {}
    for kind, m in result.items():
        own = [x for x in m.values() if not x.get("duplicate_of")]
        n = len(own)
        same = sum(1 for x in own if x.get("relation") == "same")
        nar = sum(1 for x in own if x.get("relation") == "narrower")
        by_kind[kind] = {"concepts": n, "same": same, "narrower": nar,
                         "grounded_pct": round(100 * (same + nar) / n, 1) if n else 0.0}
    tot = sum(s["concepts"] for s in by_kind.values())
    gr = sum(s["same"] + s["narrower"] for s in by_kind.values())
    dup = sum(1 for m in result.values() for x in m.values() if x.get("duplicate_of"))
    return {"by_kind": by_kind, "concepts": tot, "grounded": gr,
            "grounded_pct": round(100 * gr / tot, 1) if tot else 0.0,
            "duplicates": dup, "rejected_out_of_list": rejected, "not_evaluated": failed}
