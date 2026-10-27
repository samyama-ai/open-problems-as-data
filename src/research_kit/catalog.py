"""V3 problem layer: a problem-catalog KG carried into a run, then linked to the literature
the run collects. Rationale: samyama-cloud wiki/comparisons/research-kg-v1-vs-v2.md.

A catalog (dbms-research-kg and its kind) is problem-first: ~1,000 curated problems with a
status, bounds and what would close them, and papers attached only as citations. This kit
is literature-first: papers, people and per-paper problems with no status. Neither has
the link between the two, so this module adds it in four steps:

    bridge     catalog papers -> OpenAlex works, by DOI, then arXiv id, then title + year
    seed       researchers for the run, from the authors of bridged catalog papers
    ground     the run's canonical problems placed against catalog problems, with the
               same machinery and guardrails as ontology grounding (research_kit.ground)
    status     for each open catalog problem, the evidence papers grounded to it are read
               for a claim that solves or advances it

The catalog itself is never rewritten. Its nodes keep their ids, labels and properties
and gain only `layer`, `oa_*` (from OpenAlex) and `status_*` (from evidence) fields; a
suggested status sits beside the catalog's own and never replaces it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from . import ground as GR
from .sources.openalex import WORK_FIELDS, BudgetExhausted, short_id

PAPER_SELECT = WORK_FIELDS + ",funders"
# methodologically-blocked: the ai_research catalog's status for a problem whose measurement is
# not yet well defined. Still open; dbms_research has no such status.
OPEN = ("open", "partially-solved", "empirically-open", "methodologically-blocked")


@dataclass
class Catalog:
    dir: Path
    nodes: dict[str, dict]
    edges: list[dict]
    meta: dict

    @classmethod
    def load(cls, d: Path) -> Catalog:
        d = Path(d)
        nodes = {}
        for line in (d / "nodes.jsonl").open():
            n = json.loads(line)
            nodes[n["id"]] = n
        edges = [json.loads(line) for line in (d / "edges.jsonl").open()]
        meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
        return cls(d, nodes, edges, meta)

    def by_label(self, label: str) -> dict[str, dict]:
        return {i: n for i, n in self.nodes.items() if n["label"] == label}

    def out(self, rel: str) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = defaultdict(list)
        for e in self.edges:
            if e["rel"] == rel:
                adj[e["src"]].append(e["dst"])
        return adj

    def inv(self, rel: str) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = defaultdict(list)
        for e in self.edges:
            if e["rel"] == rel:
                adj[e["dst"]].append(e["src"])
        return adj


def norm_doi(s: str | None) -> str | None:
    s = (s or "").strip().lower()
    s = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", s)
    return s or None


def arxiv_key(s: str | None) -> str | None:
    """`1706.03762v5`, `arXiv:1706.03762` -> `1706.03762`; old-style `cs/0101001` kept."""
    m = re.search(r"([0-9]{4}\.[0-9]{4,5}|[a-z-]+(?:\.[a-z]{2})?/[0-9]{7})", (s or "").lower())
    return m.group(1) if m else None


def title_key(s: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


def title_sim(a: str | None, b: str | None) -> float:
    return SequenceMatcher(None, title_key(a), title_key(b)).ratio()


# ---- bridge ------------------------------------------------------------------
def bridge(oa: Any, cat: Catalog, log: Callable[[str], None], min_title: float = 0.92) -> dict:
    """Resolve catalog papers to OpenAlex works. DOI first; title + year only for papers
    without one, and only above `min_title` similarity with the year within one."""
    papers = cat.by_label("Paper")
    by_doi: dict[str, str] = {}
    for pid, p in papers.items():
        d = norm_doi(p.get("doi"))
        if d and "|" not in d and "," not in d:     # the OR-filter separator and list separator
            by_doi[d] = pid
    out: dict[str, dict] = {}
    works: dict[str, dict] = {}
    dois = sorted(by_doi)
    for k in range(0, len(dois), 50):
        res = oa.get("/works", filter="doi:" + "|".join(dois[k:k + 50]), select=PAPER_SELECT,
                     **{"per-page": 50}).get("results", [])
        for w in res:
            pid = by_doi.get(norm_doi(w.get("doi")) or "")
            if pid:
                out[pid] = {"work": short_id(w["id"]), "method": "doi", "score": 1.0}
                works[short_id(w["id"])] = w
    log(f"catalog bridge: {len(out)}/{len(by_doi)} papers by DOI")

    # arXiv ids. OpenAlex answers the arXiv DOI (10.48550/arxiv.<id>) with the merged work,
    # whose own doi is often the publisher's, so a result is mapped back through the arXiv id
    # in its locations. ai_research cites 3,081 of its 4,932 papers by arXiv id and 1 by DOI.
    by_ax: dict[str, str] = {}
    for pid, p in papers.items():
        ax = arxiv_key(p.get("arxiv_id"))
        if ax and pid not in out:
            by_ax[ax] = pid
    axs, n_ax = sorted(by_ax), 0
    for k in range(0, len(axs), 50):
        res = oa.get("/works", filter="doi:" + "|".join(f"10.48550/arxiv.{x}" for x in axs[k:k + 50]),
                     select=PAPER_SELECT + ",locations", **{"per-page": 50}).get("results", [])
        for w in res:
            locs = w.pop("locations", None) or []
            for ax in {arxiv_key(m) for u in [w.get("doi")] + [l.get("landing_page_url") for l in locs]
                       for m in re.findall(r"arxiv[./](?:org/(?:abs|pdf)/)?([0-9]{4}\.[0-9]{4,5}|[a-z-]+/[0-9]{7})",
                                           (u or "").lower())}:
                pid = by_ax.get(ax)
                if pid and pid not in out:
                    out[pid] = {"work": short_id(w["id"]), "method": "arxiv", "score": 1.0}
                    works[short_id(w["id"])] = w
                    n_ax += 1
    log(f"catalog bridge: {n_ax}/{len(by_ax)} more by arXiv id")

    n_title = 0
    for pid, p in papers.items():
        if pid in out or not p.get("title"):
            continue
        q = title_key(p["title"])[:250]               # OpenAlex search rejects ':' and '?'
        try:
            res = oa.get("/works", search=q, select=PAPER_SELECT, **{"per-page": 5}).get("results", [])
        except BudgetExhausted:
            raise                 # no partial bridge checkpoint: a re-run after the reset resumes from cache
        except Exception as e:  # noqa: BLE001 -- one bad title must not stop the bridge
            log(f"catalog bridge: title search failed for {pid}: {type(e).__name__}")
            continue
        best, score = None, 0.0
        for w in res:
            s = title_sim(p["title"], w.get("title"))
            y, wy = p.get("year"), w.get("publication_year")
            if s > score and (not y or not wy or abs(int(y) - int(wy)) <= 1):
                best, score = w, s
        if best is not None and score >= min_title:
            out[pid] = {"work": short_id(best["id"]), "method": "title+year", "score": round(score, 3)}
            works[short_id(best["id"])] = best
            n_title += 1
    log(f"catalog bridge: {n_title} more by title + year; {len(out)}/{len(papers)} papers resolved")
    return {"papers": out, "works": works,
            "unresolved": sorted(set(papers) - set(out))}


# ---- seed researchers --------------------------------------------------------
def seed_researchers(cat: Catalog, br: dict, n: int, since: int, min_papers: int = 2) -> list[dict]:
    """Authors of bridged catalog papers, picked round-robin across catalog topics.

    Ranking all authors by problems covered let the co-author lists of a few heavily cited
    papers take the top places (the learned-index paper's authors include RL and
    recommender researchers). So an author needs `min_papers` distinct catalog papers, and
    each round takes the best remaining author for each topic in turn, ranked by that
    topic's problems their papers from `since` on cover."""
    cited_by = cat.inv("CITES")                       # paper -> problems citing it
    topic_of = {p: ts[0] for p, ts in cat.out("IN_TOPIC").items() if ts}
    papers: dict[str, set] = defaultdict(set)
    per_topic: dict[str, Counter] = defaultdict(Counter)     # topic -> author -> recent problems
    total: dict[str, set] = defaultdict(set)
    latest: dict[str, tuple[int, str, str]] = {}
    for pid, m in br["papers"].items():
        w = br["works"].get(m["work"]) or {}
        year = w.get("publication_year") or 0
        probs = set(cited_by.get(pid, []))
        for a in w.get("authorships") or []:
            au = a.get("author") or {}
            aid = short_id(au.get("id"))
            if not aid:
                continue
            papers[aid].add(pid)
            total[aid] |= probs
            if year >= since:
                for pr in probs:
                    if pr in topic_of:
                        per_topic[topic_of[pr]][aid] += 1
            inst = next((x.get("display_name") for x in a.get("institutions") or [] if x.get("display_name")), "")
            if year >= latest.get(aid, (0, "", ""))[0]:
                latest[aid] = (year, au.get("display_name") or "", inst)
    eligible = {a for a, ps in papers.items() if len(ps) >= min_papers and latest[a][1]}
    topics = sorted(per_topic, key=lambda t: -sum(per_topic[t].values()))
    picked: list[str] = []
    for _ in range(n):
        before = len(picked)
        for t in topics:
            best = next((a for a, _ in per_topic[t].most_common() if a in eligible and a not in picked), None)
            if best:
                picked.append(best)
                if len(picked) == n:
                    break
        if len(picked) in (n, before):
            break
    best_topic = {a: max(topics, key=lambda t: per_topic[t][a]) for a in picked}
    return [{"name": latest[a][1], "institution": latest[a][2], "author_ids": [a],
             "topic": best_topic[a], "catalog_papers": len(papers[a]),
             "problems_recent": sum(per_topic[t][a] for t in topics), "problems_all": len(total[a]),
             "latest_year": latest[a][0]} for a in picked]


def link_people(cat: Catalog, br: dict) -> dict[str, dict]:
    """Catalog Person (often a surname) -> OpenAlex author, only when unambiguous.

    A person who AUTHORED_BY a bridged paper is matched by surname against that work's
    authors. A person named only in Current Research (ACTIVE_ON) is matched against the
    authors of the papers that problem cites. One surname match or nothing."""
    people = cat.by_label("Person")
    authored = cat.inv("AUTHORED_BY")                 # person -> papers
    active = cat.out("ACTIVE_ON")                     # person -> problems
    cites = cat.out("CITES")                          # problem -> papers

    def authors(pid: str) -> list[tuple[str, str]]:
        m = br["papers"].get(pid)
        w = br["works"].get(m["work"]) if m else None
        return [(short_id((a.get("author") or {}).get("id")), (a.get("author") or {}).get("display_name") or "")
                for a in (w or {}).get("authorships") or []]

    def surname(s: str) -> str:
        parts = re.findall(r"[a-zà-ÿ'-]+", s.lower())
        return parts[-1] if parts else ""

    def initials_ok(cat_name: str, oa_name: str) -> bool:
        toks = [t for t in re.split(r"[\s.]+", cat_name) if t][:-1]
        first = re.findall(r"[A-Za-zÀ-ÿ]+", oa_name)
        return not toks or not first or toks[0][0].lower() == first[0][0].lower()

    out = {}
    for pid, p in people.items():
        name = p.get("name") or ""
        sn = surname(name)
        if not sn:
            continue
        for method, pool in (("authored", [x for pp in authored.get(pid, []) for x in authors(pp)]),
                             ("active_on", [x for pr in active.get(pid, []) for pp in cites.get(pr, [])
                                            for x in authors(pp)])):
            cands = {aid: nm for aid, nm in pool if aid and surname(nm) == sn and initials_ok(name, nm)}
            if len(cands) == 1:
                aid, nm = next(iter(cands.items()))
                out[pid] = {"author": aid, "name": nm, "method": method}
                break
    return out


# ---- ground run problems in catalog problems ----------------------------------
class ProblemVocab(GR.Vocab):
    """Catalog problems as a vocabulary. Titles are short ('Acyclic Join Dependency
    Recognition'), so the opening of the statement is indexed too."""

    def reindex(self) -> None:
        import math
        self.index, df = defaultdict(set), Counter()
        for nid, n in self.nodes.items():
            ws = set(GR.words(n.get("name", ""))) | set(GR.words(n.get("index_text", "")))
            for w in ws:
                self.index[w].add(nid)
                df[w] += 1
        total = max(1, len(self.nodes))
        self.idf = {w: math.log(total / c) + 1.0 for w, c in df.items()}


def clean_md(s: str | None, n: int) -> str:
    s = re.sub(r"\$[^$]*\$", " ", s or "")           # LaTeX
    s = re.sub(r"[*_`#>|]", "", s)
    return re.sub(r"\s+", " ", s).strip()[:n]


def problem_vocab(cat: Catalog) -> ProblemVocab:
    v = ProblemVocab("catalog")
    topic_of = cat.out("IN_TOPIC")
    topics = cat.by_label("Topic")
    h = hashlib.sha256()
    for pid, p in cat.by_label("Problem").items():
        st = clean_md(p.get("statement") or p.get("problem_statement"), 400)
        tname = next((topics[t]["name"] for t in topic_of.get(pid, []) if t in topics), "")
        v.nodes[pid] = {"id": pid, "name": p.get("title") or pid, "vocabulary": "catalog",
                        "description": f"[{p.get('status')}; {tname}] {st[:200]}",
                        "index_text": st[:300]}
        h.update(f"{pid}|{p.get('title')}|{p.get('status')}".encode())
    v.tag = h.hexdigest()[:10]
    v.reindex()
    return v


def ground_problems(llm: Any, cat: Catalog, canon_problems: dict, domain: str,
                    prompt: str, system: str) -> dict:
    vocab = problem_vocab(cat)
    res = GR.ground(llm, {"problems": canon_problems}, [vocab], domain,
                    {"problems": "research problem"}, prompt, system, k=8)
    res.pop("classes", None)                          # the catalog layer carries its own nodes
    return res


def evidence(cg: dict, canon_problems: dict, ext: dict) -> dict[str, list[str]]:
    """Catalog problem -> works whose extracted problems were placed on it."""
    amap = {k.lower(): v for k, v in (canon_problems.get("map") or {}).items()}
    placed = {name: x["target"] for name, x in (cg.get("concepts", {}).get("problems") or {}).items()
              if x.get("grounded")}
    placed_l = {k.lower(): v for k, v in placed.items()}
    out: dict[str, set] = defaultdict(set)
    for wid, p in ext.items():
        for x in p.get("problems") or []:
            name = x.get("name") if isinstance(x, dict) else x
            if not name:
                continue
            c = amap.get(name.lower(), name)
            if (t := placed.get(c) or placed_l.get(c.lower())):
                out[t].add(wid)
    return {k: sorted(v) for k, v in out.items()}


# ---- status from evidence ----------------------------------------------------
def status_check(llm: Any, cat: Catalog, ev: dict[str, list[str]], works: dict, ext: dict,
                 prompt: str, system: str, per: int = 8) -> dict:
    problems = cat.by_label("Problem")
    as_of = cat.meta.get("as_of") or ""
    jobs = [pid for pid in sorted(ev) if pid in problems and problems[pid].get("status") in OPEN]

    def paper_line(j: int, wid: str) -> str:
        w, p = works.get(wid) or {}, ext.get(wid) or {}
        res = "; ".join(r.get("statement", "") for r in (p.get("results") or [])[:3])
        claims = "; ".join(f"{x.get('name')}: {x.get('status_in_paper')}" for x in p.get("problems") or []
                           if isinstance(x, dict) and x.get("status_in_paper"))
        return (f"[{j}] {w.get('title')} ({w.get('year')})\n"
                f"    summary: {(p.get('summary') or '')[:400]}\n    results: {res[:500]}"
                + (f"\n    the paper's own claims: {claims[:300]}" if claims else ""))

    def run(pid: str) -> dict:
        p = problems[pid]
        papers = sorted(ev[pid], key=lambda w: -((works.get(w) or {}).get("year") or 0))[:per]
        d = llm.json_call("status", re.sub(r"[^A-Za-z0-9_-]", "_", pid), prompt.format(
            title=p.get("title"), status=p.get("status"), as_of=as_of,
            statement=clean_md(p.get("statement"), 1500),
            upper=clean_md(p.get("upper_bound_text"), 600), lower=clean_md(p.get("lower_bound_text"), 600),
            gap=clean_md(p.get("gap_text"), 600),
            papers="\n".join(paper_line(j, w) for j, w in enumerate(papers))),
            system=system, effort="medium", max_tokens=8000) or {}
        verdicts = []
        for r in d.get("papers") or []:
            i = r.get("i")
            if isinstance(i, int) and 0 <= i < len(papers) and r.get("verdict") in (
                    "solves", "advances", "refutes", "restates", "unrelated"):
                verdicts.append({"work": papers[i], "verdict": r["verdict"],
                                 "quote": (r.get("quote") or "")[:400], "confidence": r.get("confidence")})
        sug = d.get("suggested_status")
        solved = any(v["verdict"] == "solves" for v in verdicts)
        return {"checked": datetime.now(UTC).date().isoformat(), "catalog_status": p.get("status"),
                "papers": verdicts,
                # a status change is only suggested when some paper claims to solve it
                "suggested_status": sug if solved and sug and sug != p.get("status") else None,
                "rationale": (d.get("rationale") or "")[:600]}

    out = llm.pmap(run, jobs, "status", batchable=True)
    return {pid: r for pid, r in zip(jobs, out) if r}
