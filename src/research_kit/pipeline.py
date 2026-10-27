"""Research pipeline: researchers + domain -> literature, people, concepts, ideas -> graph.

Stages (each writes to the run directory and is skipped on re-run when its output exists):
  1 resolve     researcher names -> OpenAlex author ids (model disambiguates split profiles)
  2 works       all works of the seed researchers
  3 expand      most-referenced works + most-cited citing works
  4 extract     per-paper problems/methods/materials/properties/results (batched model calls)
  5 profile     per-researcher profile with web search
  6 domain      domain map with web search; landmark works from its search queries
  7 canonical   merge synonyms per concept kind, add BROADER parents
  8 ideas       cross-group research ideas grounded in papers and open problems
  9 graph       nodes.jsonl + edges.jsonl  (graph.build)
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import prompts as P
from .llm import LLM
from .sources.openalex import OpenAlex, abstract_text, short_id

PRESETS: dict[str, dict[str, Any]] = {
    "materials": {
        "kinds": {   # extraction key -> (graph label, prompt word)
            "problems": ("Problem", "research problem"),
            "methods": ("Method", "method/technique"),
            "materials": ("Material", "material/material class"),
            "properties": ("Property", "material property/phenomenon"),
            "datasets_tools": ("Tool", "dataset/software/instrument"),
            "applications": ("Application", "application"),
        },
        "subject": "materials", "metric": "properties",
        "result_subject": "material", "result_metric": "property",
        "on_subject": "ON_MATERIAL", "of_metric": "OF_PROPERTY",
        "examples": '"solid-state electrolyte", "DFT", "LiNi0.8Mn0.1Co0.1O2", "ionic conductivity"',
    },
    "cs": {
        "kinds": {
            "problems": ("Problem", "research problem"),
            "methods": ("Method", "method/technique/algorithm/system design"),
            "subjects": ("Subject", "object of study (data model, graph class, workload, query class, hardware, system type)"),
            "metrics": ("Metric", "metric or property evaluated"),
            "datasets_tools": ("Tool", "dataset/benchmark/software system"),
            "applications": ("Application", "application"),
        },
        "subject": "subjects", "metric": "metrics",
        "result_subject": "subject", "result_metric": "metric",
        "on_subject": "ON_SUBJECT", "of_metric": "OF_METRIC",
        "examples": '"subgraph matching", "worst-case optimal join", "property graphs", "query latency", "LDBC SNB"',
    },
    "media": {
        "kinds": {
            "problems": ("Problem", "research problem"),
            "methods": ("Method", "method/model/algorithm/auction or market mechanism/estimator"),
            "subjects": ("Subject", "object of study (ad format or placement, channel or platform type, "
                                    "audience segment, market or auction design, content type, delivery system)"),
            "metrics": ("Metric", "metric or outcome measured (engagement, revenue, lift, quality, cost)"),
            "datasets_tools": ("Tool", "dataset/benchmark/platform/software system"),
            "applications": ("Application", "application or commercial use case"),
        },
        "subject": "subjects", "metric": "metrics",
        "result_subject": "subject", "result_metric": "metric",
        "on_subject": "ON_SUBJECT", "of_metric": "OF_METRIC",
        "examples": '"server-side ad insertion", "second-price auction", "connected TV", '
                    '"incrementality", "click-through rate", "quality of experience"',
    },
    "bio": {
        "kinds": {
            "problems": ("Problem", "research problem"),
            "methods": ("Method", "method/technique/modality/engineering strategy"),
            "targets": ("Target", "biological subject (antigen, gene, pathway, cell type, cell product)"),
            "outcomes": ("Outcome", "outcome or property measured (efficacy, persistence, toxicity, yield)"),
            "datasets_tools": ("Tool", "dataset/assay/platform/vector/instrument"),
            "applications": ("Application", "disease indication or application"),
        },
        "subject": "targets", "metric": "outcomes",
        "result_subject": "target", "result_metric": "outcome",
        "on_subject": "ON_TARGET", "of_metric": "OF_OUTCOME",
        "examples": '"CAR-T persistence", "CRISPR knockout", "CD19", "gamma delta T cells", "cytokine release syndrome"',
    },
}
CONCEPT_KINDS = PRESETS["materials"]["kinds"]   # set by Pipeline / graph.build from the run's preset


def use_preset(name: str) -> dict[str, Any]:
    global CONCEPT_KINDS
    CONCEPT_KINDS = PRESETS[name]["kinds"]
    return PRESETS[name]


def log(msg: str) -> None:
    print(f"[research-kit] {msg}", file=sys.stderr)


_NO_DECOMP = str.maketrans({"ı": "i", "ł": "l", "ø": "o", "đ": "d", "ß": "ss", "æ": "ae",
                            "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-"})


def fold(s: str) -> str:
    """Lowercase and strip accents: 'Özsu' -> 'ozsu', 'Buluç' -> 'buluc'."""
    s = s.lower().translate(_NO_DECOMP)
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")[:80]


def concept_key(name: str) -> str:
    """Identity of a concept name for de-duplication: case, accents, whitespace,
    punctuation and plural ending ignored. 'Phase transitions ' == 'phase transition'."""
    toks = re.split(r"[^a-z0-9]+", fold(name))
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
                    for w in toks if w)


def repair_canonical(c: dict) -> tuple[dict, dict]:
    """Make one kind's canonical output self-consistent. Deterministic, idempotent, no
    model calls, so it can be applied to a cached canonical.json.

    1. A name listed as a canonical concept AND mapped as an alias of another concept
       ('LLZO' -> 'garnet solid electrolytes'). Left alone, every paper naming LLZO links
       to the class and the LLZO node is orphaned. The specific concept is kept: it maps
       to itself, and the concept it had been folded into becomes its parent (BROADER).
    2. Duplicate concepts differing only in case, whitespace or a plural ending
       ('Ceramics' / 'ceramics', 'thin film deposition '). Merged onto the spelling most
       raw names already map to.
    """
    mapping, canon = dict(c.get("map") or {}), {k: dict(v) for k, v in (c.get("canonical") or {}).items()}
    conflicts = 0
    for k in list(canon):
        tgt = mapping.get(k)
        if tgt is not None and tgt != k and concept_key(tgt) != concept_key(k):
            mapping[k] = k
            canon[k].setdefault("parent", None)
            if not canon[k]["parent"]:
                canon[k]["parent"] = tgt
            canon[k]["was_alias_of"] = tgt
            conflicts += 1

    support = Counter(mapping.values())
    groups: dict[str, list[str]] = defaultdict(list)
    for k in canon:
        groups[concept_key(k)].append(k)
    rep: dict[str, str] = {}
    for ks in groups.values():
        if len(ks) < 2:
            continue
        keep = max(ks, key=lambda k: (support[k], k == k.strip(), k == k.lower(), -len(k)))
        rep.update({k: keep for k in ks if k != keep})
    for n, cn in list(mapping.items()):
        if cn in rep:
            mapping[n] = rep[cn]
    for k, keep in rep.items():
        mapping[k] = keep
        gone = canon.pop(k)
        for field_ in ("description", "parent"):
            if not canon[keep].get(field_) and gone.get(field_):
                canon[keep][field_] = gone[field_]
    for info in canon.values():
        if info.get("parent") in rep:
            info["parent"] = rep[info["parent"]]
        if info.get("parent") and concept_key(info["parent"]) == concept_key(info.get("name") or ""):
            info["parent"] = None
    return {"map": mapping, "canonical": canon}, {"alias_conflicts": conflicts,
                                                   "duplicates_merged": len(rep)}


@dataclass
class Researcher:
    name: str
    institution: str
    author_ids: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return slug(self.name)

    @classmethod
    def parse(cls, spec: str) -> "Researcher":
        """"Name|Institution", or "Name|Institution|A123,A456" to pin the OpenAlex ids.

        Pinning skips the search and the disambiguation call. Use it when a name search
        cannot find the person (OpenAlex lists them under another name order) or when
        their profile is split and one part carries the current employer.
        """
        name, _, rest = spec.partition("|")
        inst, _, ids = rest.partition("|")
        return cls(name.strip(), inst.strip(),
                   tuple(i.strip() for i in ids.split(",") if i.strip()))


@dataclass
class Config:
    domain: str
    researchers: list[Researcher]
    run_dir: Path
    refs_top: int = 80            # most-referenced works pulled in as literature
    citing_seed_papers: int = 12  # per researcher: most-cited seed works whose citers we fetch
    citing_per_paper: int = 6
    landmark_per_query: int = 6
    batch: int = 8                # papers per extraction call
    ideas: int = 20
    max_seed_works: int = 0        # per researcher, most-cited first; 0 = all
    recent_seed_works: int = 20    # plus this many most recent, so new directions are not lost
    mailto: str | None = None
    preset: str = "materials"
    ground_domain: str | None = None   # vocabulary-catalogue domain to ground concepts in
    ontologies: Path | None = None     # the vocabulary catalogue (vocab/)
    catalog: Path | None = None        # V3 problem layer: a catalog export (research_kit.catalog)
    catalog_seed: int = 0              # seed this many researchers from the catalog's authors
    catalog_since: int = 2018          # ...ranked by catalog problems their papers since then cover
    extra: dict[str, Any] = field(default_factory=dict)


def norm_work(w: dict[str, Any]) -> dict[str, Any]:
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    authors = []
    for i, a in enumerate(w.get("authorships") or []):
        au = a.get("author") or {}
        authors.append({
            "id": short_id(au.get("id")), "name": au.get("display_name"), "orcid": au.get("orcid"),
            "position": a.get("author_position") or str(i),
            "institutions": [{"id": short_id(x.get("id")), "name": x.get("display_name"),
                              "country": x.get("country_code"), "type": x.get("type")}
                             for x in a.get("institutions") or [] if x.get("id")],
        })
    topics = []
    for t in w.get("topics") or []:
        topics.append({"id": short_id(t.get("id")), "name": t.get("display_name"), "score": t.get("score"),
                       "subfield": (t.get("subfield") or {}).get("display_name"),
                       "subfield_id": short_id((t.get("subfield") or {}).get("id")),
                       "field": (t.get("field") or {}).get("display_name"),
                       "field_id": short_id((t.get("field") or {}).get("id")),
                       "domain": (t.get("domain") or {}).get("display_name"),
                       "domain_id": short_id((t.get("domain") or {}).get("id"))})
    return {
        "id": short_id(w["id"]), "doi": w.get("doi"), "title": (w.get("title") or "").strip(),
        "year": w.get("publication_year"), "type": w.get("type"), "cited_by": w.get("cited_by_count") or 0,
        "venue": src.get("display_name"), "venue_id": short_id(src.get("id")), "venue_type": src.get("type"),
        "oa_url": (w.get("open_access") or {}).get("oa_url"),
        "abstract": abstract_text(w.get("abstract_inverted_index")),
        "authors": authors, "topics": topics,
        "keywords": [k.get("display_name") for k in w.get("keywords") or []],
        "refs": [short_id(r) for r in w.get("referenced_works") or []],
        # only catalog-bridged works are fetched with funders (research_kit.catalog)
        "funders": sorted({f.get("display_name") for f in w.get("funders") or []
                           if f.get("display_name")}),
        "tiers": [], "seed_of": [],
    }


class Pipeline:
    def __init__(self, cfg: Config, llm: LLM):
        self.cfg = cfg
        self.llm = llm
        self.dir = cfg.run_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.oa = OpenAlex(self.dir / "cache" / "openalex", mailto=cfg.mailto)
        self.preset = use_preset(cfg.preset)

    # ---- helpers ---------------------------------------------------------------
    def _load(self, name: str) -> Any:
        f = self.dir / name
        return json.loads(f.read_text()) if f.exists() else None

    def _save(self, name: str, data: Any) -> None:
        (self.dir / name).write_text(json.dumps(data, indent=1, ensure_ascii=False))

    # ---- 1 resolve -------------------------------------------------------------
    def resolve(self) -> dict[str, Any]:
        if (got := self._load("resolve.json")) is not None:
            return got
        res = self.llm.pmap(self._resolve_one, self.cfg.researchers, "resolve")
        errored = [r.name for r, x in zip(self.cfg.researchers, res) if x is None]
        if errored:   # do not save a partial resolve.json: a re-run must retry these
            raise RuntimeError(f"resolve failed for {len(errored)} researchers (see log): {', '.join(errored[:8])}")
        out = {r.key: x for r, x in zip(self.cfg.researchers, res) if x.get("author_ids")}
        missing = [r.name for r, x in zip(self.cfg.researchers, res) if not x.get("author_ids")]
        if missing:
            log(f"resolve: skipped {len(missing)} unresolved: {', '.join(missing)}")
        self._save("resolve.json", out)
        self._save("unresolved.json", missing)
        return out

    def _resolve_one(self, r: Researcher) -> dict[str, Any] | None:
        if r.author_ids:
            got = [self.oa.author(a) for a in r.author_ids]
            log(f"resolve {r.name}: {list(r.author_ids)} (pinned; "
                f"{sum(a.get('works_count') or 0 for a in got)} works)")
            return {"name": r.name, "institution": r.institution, "author_ids": list(r.author_ids),
                    "reason": "author ids pinned in the input, not resolved by search",
                    "openalex": [{"id": short_id(a["id"]), "display_name": a.get("display_name"),
                                  "orcid": a.get("orcid"), "works_count": a.get("works_count"),
                                  "cited_by_count": a.get("cited_by_count")} for a in got]}
        parts = fold(r.name).replace(".", " ").replace("-", " ").split()
        surname, first = parts[-1], parts[0]
        cands: dict[str, dict] = {}
        for q in (r.name, f"{parts[0][0]} {r.name.split()[-1]}"):
            for a in self.oa.search_authors(q, n=50):
                dn = fold(a.get("display_name") or "").replace(".", " ").replace("-", " ").split()
                # surname must match; first name must match, or be an initial / a split
                # spelling of it ("Naga Phani" for "Nagaphani")
                if not dn or surname not in dn:
                    continue
                given = [t for t in dn if t != surname]
                if not given or not (first in given or "".join(given).startswith(first)
                                     or first.startswith("".join(given[:2]))
                                     or (len(given[0]) == 1 and given[0] == first[0])):
                    continue
                cands[short_id(a["id"])] = a
        inst_words = {w for w in re.split(r"\W+", fold(r.institution)) if len(w) > 2} - {"university", "institute", "the"}

        def inst_names(a: dict) -> list[str]:
            names = [i.get("display_name", "") for i in a.get("last_known_institutions") or []]
            names += [(x.get("institution") or {}).get("display_name", "") for x in a.get("affiliations") or []]
            return [n for n in names if n]

        def matches(a: dict) -> bool:
            text = fold(" ".join(inst_names(a)))
            return not inst_words or any(w in text for w in inst_words)

        by_size = sorted(cands.values(), key=lambda a: -(a.get("works_count") or 0))
        # Institution matches first, then the largest profiles whatever their institution.
        # An industry researcher's papers usually predate the employer we were given, so the
        # profile carrying that employer can be a near-empty split of the real record. Showing
        # both lets the model keep both ids instead of only the one that names the employer.
        hit = [a for a in by_size if matches(a)][:12]
        shortlist = hit + [a for a in by_size[:8] if a not in hit] if hit else by_size[:8]
        if not shortlist:
            log(f"resolve {r.name}: no OpenAlex candidates")
            return {"unresolved": "no candidates"}
        lines = []
        for a in shortlist:
            titles = [w["title"] for w in self.oa.get("/works", filter=f"author.id:{short_id(a['id'])}",
                                                      sort="cited_by_count:desc", select="title",
                                                      **{"per-page": 4}).get("results", []) if w.get("title")]
            lines.append(f"- {short_id(a['id'])} | {a.get('display_name')} | {a.get('works_count')} works | "
                         f"{a.get('cited_by_count')} cites | {'; '.join(sorted(set(inst_names(a)))[:4])} | "
                         f"{' // '.join(titles)}")
        res = self.llm.json_call("resolve", r.key, P.DISAMBIGUATE.format(
            name=r.name, institution=r.institution, domain=self.cfg.domain, candidates="\n".join(lines)),
            system=P.SYSTEM, deep=True, effort="medium", web_search=4)
        keep = [k for k in res.get("keep", []) if k in cands]
        log(f"resolve {r.name}: {keep or 'NONE'} ({(res.get('reason') or '')[:160]})")
        if not keep:
            return {"unresolved": res.get("reason")}
        return {"name": r.name, "institution": r.institution, "author_ids": keep,
                "reason": res.get("reason"),
                "openalex": [{"id": k, "display_name": cands[k].get("display_name"),
                              "orcid": cands[k].get("orcid"), "works_count": cands[k].get("works_count"),
                              "cited_by_count": cands[k].get("cited_by_count"),
                              "h_index": (cands[k].get("summary_stats") or {}).get("h_index")}
                             for k in keep]}

    # ---- 2+3 works and literature ---------------------------------------------
    def works(self, resolved: dict[str, Any]) -> dict[str, dict]:
        if (got := self._load("works.json")) is not None:
            return got
        works: dict[str, dict] = {}

        def add(raw: dict, tier: str, seed_of: str | None = None) -> None:
            w = works.get(short_id(raw["id"])) or norm_work(raw)
            works[w["id"]] = w
            if tier not in w["tiers"]:
                w["tiers"].append(tier)
            if seed_of and seed_of not in w["seed_of"]:
                w["seed_of"].append(seed_of)

        for key, r in resolved.items():
            seed = self.oa.works_by_authors(r["author_ids"])
            if self.cfg.max_seed_works and len(seed) > self.cfg.max_seed_works:
                total = len(seed)
                top = sorted(seed, key=lambda w: -(w.get("cited_by_count") or 0))[:self.cfg.max_seed_works]
                recent = sorted(seed, key=lambda w: -(w.get("publication_year") or 0))[:self.cfg.recent_seed_works]
                seed = list({w["id"]: w for w in top + recent}.values())
                log(f"works {r['name']}: capped {total} -> {len(seed)}")
            for raw in seed:
                add(raw, "seed", key)
            log(f"works {r['name']}: {len(seed)}")

        seeds = [w for w in works.values() if "seed" in w["tiers"]]
        ref_counts = Counter(ref for w in seeds for ref in w["refs"] if ref not in works)
        top_refs = [rid for rid, _ in ref_counts.most_common(self.cfg.refs_top)]
        for raw in self.oa.works_by_ids(top_refs):
            add(raw, "reference")
        for w in works.values():
            if w["id"] in ref_counts:
                w["ref_count_from_seed"] = ref_counts[w["id"]]
        log(f"expand references: {len(top_refs)} (most-cited-by-seed)")

        for key in resolved:
            mine = sorted((w for w in seeds if key in w["seed_of"]), key=lambda w: -w["cited_by"])
            for w in mine[:self.cfg.citing_seed_papers]:
                for raw in self.oa.citing_works(w["id"], n=self.cfg.citing_per_paper):
                    add(raw, "citing")
        log(f"expand citing: total works now {len(works)}")
        self._save("works.json", works)
        return works

    # ---- 4 extract -------------------------------------------------------------
    def extract(self, works: dict[str, dict], ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = self._load("extract.json") or {}
        ids = sorted(i for i in ids if works[i]["title"] and i not in out)
        batches = [ids[k:k + self.cfg.batch] for k in range(0, len(ids), self.cfg.batch)]

        def run(batch: list[str]) -> list[dict]:
            text = "\n\n".join(
                f"[{i}] {works[i]['title']} ({works[i]['year']}, {works[i]['venue'] or 'n/a'})\n"
                f"Keywords: {', '.join(works[i]['keywords'][:8])}\n"
                f"Abstract: {works[i]['abstract'][:3500] or '(no abstract; use the title only)'}"
                for i in batch)
            key = f"{batch[0]}_{batch[-1]}_{len(batch)}"
            pr = self.preset
            d = self.llm.json_call("extract", key, P.EXTRACT.format(
                domain=self.cfg.domain, papers=text, examples=pr["examples"],
                subject_key=pr["subject"], subject_desc=pr["kinds"][pr["subject"]][1],
                metric_key=pr["metric"], metric_desc=pr["kinds"][pr["metric"]][1],
                rs=pr["result_subject"], rm=pr["result_metric"],
                methods_desc=pr["kinds"]["methods"][1]),
                                   system=P.SYSTEM, effort="medium", max_tokens=24000)
            return d.get("papers", [])

        for res in self.llm.pmap(run, batches, "extract", batchable=True):
            for p in res or []:
                if p.get("id") in works:
                    out[p["id"]] = p
        self._save("extract.json", out)
        return out

    # ---- 5 profile -------------------------------------------------------------
    def profiles(self, resolved: dict, works: dict, ext: dict) -> dict[str, dict]:
        def run(key: str) -> dict:
            r = resolved[key]
            mine = sorted((w for w in works.values() if key in w["seed_of"]),
                          key=lambda w: -(w["year"] or 0))
            lines = "\n".join(f"{w['id']} | {w['year']} | {w['title']} | {ext.get(w['id'], {}).get('summary', '')[:220]}"
                              for w in mine)
            prompt = P.PROFILE.format(name=r["name"], institution=r["institution"],
                                      domain=self.cfg.domain, works=lines)
            try:
                return self.llm.json_call("profile", key, prompt, system=P.SYSTEM,
                                          deep=True, effort="high", web_search=12)
            except RuntimeError as e:
                # A refused profile call used to leave the researcher with no profile at all,
                # which silently skews the domain map and the ideas. Fall back to one narrower
                # request -- the papers, no web -- and mark where the profile came from. This is
                # a smaller question than the one that failed, not a retry of the same one.
                if "refused" not in str(e):
                    raise
                log(f"profile/{key}: {e}; retrying without web search (papers only)")
                p = self.llm.json_call("profile_noweb", key, prompt, system=P.SYSTEM,
                                       deep=True, effort="high", web_search=0)
                return {**p, "profile_source": "papers only; no web search (first call refused)"}
        keys = list(resolved)
        out = dict(zip(keys, self.llm.pmap(run, keys, "profile", batchable=True)))
        if (lost := [resolved[k]["name"] for k, v in out.items() if not v]):
            # The domain map and the ideas are written from these profiles, so a missing one
            # skews both toward whoever did profile. Say so here and in REPORT.md.
            log(f"profile: NO PROFILE for {len(lost)}/{len(keys)}: {', '.join(lost)} "
                "-- domain map and ideas will be skewed; REPORT.md will say so")
        return out

    # ---- 6 domain --------------------------------------------------------------
    def domain(self, resolved: dict, profiles: dict, ext: dict) -> dict:
        def top(kind: str, n: int) -> str:
            c = Counter()
            for p in ext.values():
                for x in p.get(kind) or []:
                    name = x.get("name") if isinstance(x, dict) else x
                    if name:
                        c[name.lower()] += 1
            return "; ".join(f"{k} ({v})" for k, v in c.most_common(n))
        rs = "\n".join(f"- {r['name']} ({r['institution']}): " +
                       "; ".join(t.get("name", "") for t in (profiles.get(k) or {}).get("research_themes", []))
                       for k, r in resolved.items())
        return self.llm.json_call("domain", slug(self.cfg.domain), P.DOMAIN.format(
            domain=self.cfg.domain, researchers=rs, problems=top("problems", 80),
            methods=top("methods", 60), materials=top(self.preset["subject"], 60)),
            system=P.SYSTEM, deep=True, effort="high", web_search=20)

    def landmarks(self, works: dict, dom: dict) -> list[str]:
        new = []
        for sa in dom.get("subareas", []):
            for q in sa.get("search_queries", [])[:3]:
                for raw in self.oa.search_works(q, n=self.cfg.landmark_per_query):
                    wid = short_id(raw["id"])
                    w = works.get(wid) or norm_work(raw)
                    works[wid] = w
                    if "landmark" not in w["tiers"]:
                        w["tiers"].append("landmark")
                        w.setdefault("subareas", []).append(sa["name"])
                        new.append(wid)
        log(f"landmarks: {len(new)} works from {sum(len(s.get('search_queries', [])[:3]) for s in dom.get('subareas', []))} queries")
        return new

    # ---- 7 canonical -----------------------------------------------------------
    def canonical(self, ext: dict) -> dict[str, dict]:
        out = {}
        for kind, (_, word) in CONCEPT_KINDS.items():
            c = Counter()
            for p in ext.values():
                for x in p.get(kind) or []:
                    name = (x.get("name") if isinstance(x, dict) else x) or ""
                    name = name.strip()
                    if name:
                        c[name] += 1
            out[kind] = self._canon(kind, word, c)
            log(f"canonical {kind}: {len(c)} names -> {len(out[kind]['canonical'])} concepts")
        return out

    def _canon(self, kind: str, word: str, counts: Counter, chunk: int = 300) -> dict:
        names = sorted(counts, key=str.lower)
        chunks = [names[k:k + chunk] for k in range(0, len(names), chunk)]

        def run(args: tuple[int, list[str], str]) -> dict:
            i, ch, stage = args
            listing = "\n".join(f"- {n} ({counts.get(n, 1)})" for n in ch)
            return self.llm.json_call(stage, f"{kind}_{i}", P.CANONICALIZE.format(
                kind=word, domain=self.cfg.domain, names=listing),
                system=P.SYSTEM, effort="medium", max_tokens=64000)

        res = self.llm.pmap(run, [(i, ch, "canonical") for i, ch in enumerate(chunks)], f"canonical {kind}",
                            batchable=True)
        mapping: dict[str, str] = {}
        canon: dict[str, dict] = {}
        for ch, r in zip(chunks, res):
            r = r or {}
            m = r.get("map") or {}
            for n in ch:
                mapping[n] = m.get(n) or n
            for cc in r.get("canonical") or []:
                if cc.get("name"):
                    canon.setdefault(cc["name"], cc)
        if len(chunks) > 1:   # second pass: merge canonical names that different chunks produced
            ccount = Counter()
            for n, cn in mapping.items():
                ccount[cn] += counts.get(n, 1)
            # synonyms usually share a parent: pack parent groups into chunks of <= 800 names
            groups: dict[str, list[str]] = defaultdict(list)
            for cn in ccount:
                groups[fold((canon.get(cn) or {}).get("parent") or "~")].append(cn)
            packs, cur = [], []
            for par in sorted(groups):
                if cur and len(cur) + len(groups[par]) > 800:
                    packs.append(cur)
                    cur = []
                cur += groups[par]
            if cur:
                packs.append(cur)

            def merge_run(args: tuple[int, list[str]]) -> dict:
                i, names_ = args
                listing = "\n".join(f"- {n} ({ccount[n]})" for n in sorted(names_, key=str.lower))
                return self.llm.json_call("canonical", f"{kind}_merge_g{i}", P.CANON_MERGE.format(
                    kind=word, domain=self.cfg.domain, names=listing),
                    system=P.SYSTEM, effort="medium", max_tokens=32000).get("merge") or {}

            merge: dict[str, str] = {}
            for m in self.llm.pmap(merge_run, list(enumerate(packs)), f"canonical {kind} merge",
                                   batchable=True):
                merge.update({k: v for k, v in (m or {}).items() if v in ccount and k != v})
            for k in list(merge):     # collapse chains a -> b -> c
                seen = {k}
                while merge.get(merge[k]) and merge[k] not in seen:
                    seen.add(merge[k])
                    merge[k] = merge[merge[k]]
            mapping = {n: merge.get(cn, cn) for n, cn in mapping.items()}
            for gone in merge:
                canon.pop(gone, None)
        for cn in set(mapping.values()):
            canon.setdefault(cn, {"name": cn, "description": None, "parent": None})
        return {"map": mapping, "canonical": canon}

    # ---- 8 ideas ---------------------------------------------------------------
    def ideas(self, resolved: dict, profiles: dict, dom: dict, ext: dict, canon: dict, works: dict,
              cat: Any = None, catalog: dict | None = None) -> list[dict]:
        subj = self.preset["subject"]
        maps = {k: canon[k]["map"] for k in ("problems", "methods", subj)}

        def names(p: dict, kind: str) -> set[str]:
            out = set()
            for x in p.get(kind) or []:
                n = x.get("name") if isinstance(x, dict) else x
                if n:
                    out.add(maps[kind].get(n, n))
            return out

        # per-researcher expertise: concept counts over their papers + profile themes
        expertise, paper_lines = {}, []
        for key, r in resolved.items():
            cnt = {k: Counter() for k in maps}
            mine = [w for w in works.values() if key in w["seed_of"]]
            for w in mine:
                for k in maps:
                    cnt[k].update(names(ext.get(w["id"], {}), k))
            prof = profiles.get(key) or {}
            top_papers = sorted(mine, key=lambda w: -w["cited_by"])[:6]
            expertise[key] = (f"## {r['name']} ({r['institution']})\n"
                              f"themes: {'; '.join(t.get('name', '') for t in prof.get('research_themes') or [])}\n"
                              f"problems: {', '.join(f'{n} ({c})' for n, c in cnt['problems'].most_common(10))}\n"
                              f"methods: {', '.join(f'{n} ({c})' for n, c in cnt['methods'].most_common(10))}\n"
                              f"subjects: {', '.join(f'{n} ({c})' for n, c in cnt[subj].most_common(6))}\n"
                              f"top papers: {'; '.join(f'{w['id']} {w['title'][:80]}' for w in top_papers)}")
        for wid, p in ext.items():
            # extract.json is a durable per-paper cache: it can hold papers that are no
            # longer in the works set, because a new domain map pulls different landmarks.
            if (w := works.get(wid)) is None:
                continue
            if "seed" in w["tiers"]:
                res = "; ".join(r.get("statement", "") for r in (p.get("results") or [])[:1])
                paper_lines.append((names(p, "problems"),
                                    f"{wid} [{','.join(w['seed_of'])}] {w['year']}: P={sorted(names(p, 'problems'))} "
                                    f"M={sorted(names(p, 'methods'))[:4]} R={res[:200]}"))
        all_names = " , ".join(r["name"] for r in resolved.values())
        prof_text = "\n\n".join(expertise.values())
        dm_all = {k: dom.get(k) for k in ("open_problems", "trends")}
        subareas = dom.get("subareas") or [{"name": self.cfg.domain, "problems": []}]
        per = max(3, self.cfg.ideas // (len(subareas) + 1))
        jobs = [(sa["name"], f"the subarea '{sa['name']}': {sa.get('description', '')}", set(map(str.lower, sa.get("problems") or [])))
                for sa in subareas]
        jobs.append(("cross-cutting", "ideas that cross subareas and connect groups that have not worked together", set()))
        offered: dict[str, str] = {}
        if cat is not None and catalog:
            # V3: ideas target catalog problems that are open and have evidence. Jobs follow
            # the catalog's topics, the 12 with the most evidence, plus cross-cutting.
            from .catalog import OPEN, clean_md
            topics, topic_of = cat.by_label("Topic"), cat.out("IN_TOPIC")
            closing = cat.out("CLOSING_REQUIRES")
            ev, stat = catalog.get("evidence") or {}, catalog.get("status") or {}
            by_topic: dict[str, list[str]] = defaultdict(list)
            for pid, p in cat.by_label("Problem").items():
                st = stat.get(pid) or {}
                if p.get("status") in OPEN and ev.get(pid) and not any(
                        v["verdict"] == "solves" for v in st.get("papers") or []):
                    by_topic[(topic_of.get(pid) or ["?"])[0]].append(pid)

            def block(pids: list[str]) -> str:
                lines = []
                for pid in sorted(pids, key=lambda x: -len(ev[x]))[:15]:
                    p = cat.nodes[pid]
                    fut = "; ".join(clean_md(cat.nodes[f].get("text"), 120) for f in closing.get(pid, [])[:2]
                                    if f in cat.nodes)
                    adv = sum(1 for v in (stat.get(pid) or {}).get("papers") or [] if v["verdict"] == "advances")
                    lines.append(f"- {pid} | {p.get('title')} | {p.get('status')} | gap: "
                                 f"{clean_md(p.get('gap_text'), 220)} | closing requires: {fut} | "
                                 f"{len(ev[pid])} evidence papers, {adv} advancing")
                    offered[pid] = p.get("title") or pid
                return ("\nOpen catalog problems (id | title | status | gap | closing requires | evidence):\n"
                        + "\n".join(lines) + "\nEach idea must target one of these by id in catalog_problem.\n")

            ranked = sorted(by_topic, key=lambda t: -sum(len(ev[x]) for x in by_topic[t]))[:12]
            jobs = [(topics.get(t, {}).get("name", t), f"the catalog topic '{topics.get(t, {}).get('name', t)}'",
                     set(), block(by_topic[t])) for t in ranked]
            jobs.append(("cross-cutting", ("ideas that connect two catalog topics and groups that have "
                                           "not worked together"),
                         set(), block([x for t in ranked for x in by_topic[t][:2]])))
            per = max(3, self.cfg.ideas // len(jobs))
        jobs = [j if len(j) == 4 else (*j, "") for j in jobs]

        def run(job: tuple[str, str, set, str]) -> list[dict]:
            name, focus, probs, cat_block = job
            ev = [line for ps, line in paper_lines if not probs or {x.lower() for x in ps} & probs]
            ev = ev[:150] if ev else [line for _, line in paper_lines][:150]
            dm = json.dumps({**dm_all, "subarea": next((s for s in subareas if s["name"] == name), None)},
                            ensure_ascii=False)
            d = self.llm.json_call("ideas", slug(name), P.IDEAS.format(
                researchers=all_names, domain=self.cfg.domain, profiles=prof_text, domain_map=dm,
                evidence="\n".join(ev), n=per, focus=focus, catalog=cat_block),
                system=P.SYSTEM, deep=True, effort="high", max_tokens=48000)
            for idea in d.get("ideas", []):
                idea["subarea"] = name
                if idea.get("catalog_problem") and idea["catalog_problem"] not in offered:
                    # only a problem it was shown counts; anything else is dropped, not guessed
                    idea["catalog_problem_rejected"] = idea.pop("catalog_problem")
            return d.get("ideas", [])

        out = []
        for res in self.llm.pmap(run, jobs, "ideas", batchable=True):
            out += res or []
        return out

    # ---- run all ---------------------------------------------------------------
    # ---- 7b ground -------------------------------------------------------------
    def ground(self, canon: dict) -> dict:
        """Place canonical concepts in the vocabularies the catalogue holds for the
        domain. Unaligned concepts are kept and flagged; see research_kit.ground."""
        from . import ground as GR
        spec, vocabs = GR.locate(self.cfg.ontologies, self.cfg.ground_domain)
        if spec.get("_not_built"):
            log(f"ground: {', '.join(spec['_not_built'])} named for {self.cfg.ground_domain!r} "
                f"but not built; grounding against {', '.join(v.id for v in vocabs)} only")
        log("ground: " + ", ".join(f"{v['id']} ({v['classes']} classes)" for v in spec["_vocabularies"])
            + f"; merged into {len(vocabs[0].nodes)} classes")
        out = GR.ground(self.llm, canon, vocabs, self.cfg.domain,
                        {k: w for k, (_, w) in CONCEPT_KINDS.items()},
                        P.GROUND, P.SYSTEM)
        out["domain"] = self.cfg.ground_domain
        out["vocabularies"] = spec["_vocabularies"]
        out["gaps"] = spec.get("gaps") or []
        s = out["stats"]
        log(f"ground: {s['grounded']}/{s['concepts']} concepts placed ({s['grounded_pct']}%); "
            f"{s['rejected_out_of_list']} answers refused for naming a class not offered")
        for kind, ks in s["by_kind"].items():
            log(f"ground {kind}: {ks['same']} same, {ks['narrower']} narrower of "
                f"{ks['concepts']} ({ks['grounded_pct']}%)")
        return out

    # ---- V3 catalog -------------------------------------------------------------
    def catalog_bridge(self) -> tuple[Any, dict]:
        from . import catalog as CT
        cat = CT.Catalog.load(self.cfg.catalog)
        log(f"catalog: {cat.meta.get('name', cat.dir.name)} ({len(cat.nodes)} nodes, {len(cat.edges)} edges, "
            f"as of {cat.meta.get('as_of')})")
        br = self._load("catalog_bridge.json")
        if br is None:
            br = CT.bridge(self.oa, cat, log)
            self._save("catalog_bridge.json", br)
        if self.cfg.catalog_seed and not self.cfg.researchers:
            seed = self._load("catalog_seed.json")
            if seed is None:
                seed = CT.seed_researchers(cat, br, self.cfg.catalog_seed, self.cfg.catalog_since)
                self._save("catalog_seed.json", seed)
            self.cfg.researchers = [Researcher(r["name"], r["institution"], tuple(r["author_ids"])) for r in seed]
            log(f"catalog seed: {len(seed)} researchers, e.g. "
                + ", ".join(f"{r['name']} ({r['problems_recent']})" for r in seed[:5]))
        return cat, br

    def catalog_link(self, cat: Any, br: dict, works: dict, ext: dict, canon: dict) -> dict:
        from . import catalog as CT
        cg = self._load("catalog_ground.json")
        if cg is None:
            cg = CT.ground_problems(self.llm, cat, canon["problems"], self.cfg.domain,
                                    P.GROUND_CATALOG, P.SYSTEM)
            self._save("catalog_ground.json", cg)
        s = cg["stats"]
        log(f"catalog ground: {s['grounded']}/{s['concepts']} run problems placed on catalog problems "
            f"({s['grounded_pct']}%)")
        ev = CT.evidence(cg, canon["problems"], ext)
        st = self._load("catalog_status.json")
        if st is None:
            st = CT.status_check(self.llm, cat, ev, works, ext, P.STATUS, P.SYSTEM)
            self._save("catalog_status.json", st)
        sug = sum(1 for x in st.values() if x.get("suggested_status"))
        log(f"catalog status: {len(ev)} catalog problems have evidence; {len(st)} open ones checked; "
            f"{sug} status changes suggested")
        return {"dir": str(Path(cat.dir).resolve()), "meta": cat.meta, "bridge": br["papers"],
                "unresolved": br.get("unresolved", []),
                "people": CT.link_people(cat, br), "ground": cg, "evidence": ev, "status": st}

    def run(self) -> dict[str, Any]:
        cat = br = None
        if self.cfg.catalog:
            cat, br = self.catalog_bridge()
        resolved = self.resolve()
        works = self.works(resolved)
        if br and not any("catalog" in w["tiers"] for w in works.values()):
            # Catalog papers join the works set as their own tier, so they are extracted
            # and their problems grounded like any other paper.
            for wid, raw in br["works"].items():
                w = works.get(wid) or norm_work(raw)
                works[w["id"]] = w
                if "catalog" not in w["tiers"]:
                    w["tiers"].append("catalog")
            self._save("works.json", works)
            log(f"catalog: {len(br['works'])} bridged papers added as tier 'catalog'; works now {len(works)}")
        first = [w["id"] for w in works.values() if set(w["tiers"]) & {"seed", "reference", "citing"}]
        ext = self.extract(works, first)
        log(f"extracted {len(ext)}/{len(first)} papers")
        profiles = self.profiles(resolved, works, ext)
        dom = self.domain(resolved, profiles, ext)
        if not self._load("landmarks.json"):
            self._save("landmarks.json", self.landmarks(works, dom))
            self._save("works.json", works)
        works = self._load("works.json")
        ext = self.extract(works, list(works))
        stale = len(ext) - sum(1 for w in works if w in ext)
        log(f"extracted {sum(1 for w in works if w in ext)}/{len(works)} papers (with landmarks)"
            + (f"; {stale} cached extracts are for papers no longer in the works set" if stale else ""))
        canon = self._load("canonical.json") or self.canonical(ext)
        for kind in list(canon):
            canon[kind], fixed = repair_canonical(canon[kind])
            if any(fixed.values()):
                log(f"canonical {kind}: kept {fixed['alias_conflicts']} concepts that were also "
                    f"mapped as aliases of another; merged {fixed['duplicates_merged']} duplicates")
        self._save("canonical.json", canon)
        grounding = None
        if self.cfg.ground_domain:
            grounding = self._load("ground.json") or self.ground(canon)
            self._save("ground.json", grounding)
        catalog = self.catalog_link(cat, br, works, ext, canon) if cat else None
        ideas = self.ideas(resolved, profiles, dom, ext, canon, works, cat, catalog)
        state = {"config": {"domain": self.cfg.domain, "preset": self.cfg.preset,
                            "researchers": [r.__dict__ for r in self.cfg.researchers]},
                 "resolved": resolved, "works": works, "extract": ext, "profiles": profiles,
                 "domain": dom, "canonical": canon, "ideas": ideas, "ground": grounding,
                 "catalog": catalog}
        self._save("state.json", state)
        return state
