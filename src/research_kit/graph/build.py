"""Turn pipeline state into typed nodes and edges.

Node ids are stable: OpenAlex ids for Person/Institution/Paper/Venue/Topic, and
`<kind>:<slug>` for concepts. Every node carries `id`, `name` and `source`.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .. import pipeline as PL
from ..pipeline import slug


class G:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def node(self, nid: str, label: str, **props: Any) -> str:
        n = self.nodes.get(nid)
        clean = {k: v for k, v in props.items() if v not in (None, "", [], {})}
        if n is None:
            self.nodes[nid] = {"id": nid, "label": label, **clean}
        else:
            for k, v in clean.items():
                n.setdefault(k, v)
        return nid

    def edge(self, src: str, rel: str, dst: str, **props: Any) -> None:
        if src == dst or src not in self.nodes or dst not in self.nodes:
            return
        e = self.edges.setdefault((src, rel, dst), {})
        for k, v in props.items():
            if v not in (None, "", [], {}):
                e[k] = v

    def bump(self, src: str, rel: str, dst: str, key: str = "weight", by: int = 1) -> None:
        if src == dst or src not in self.nodes or dst not in self.nodes:
            return
        e = self.edges.setdefault((src, rel, dst), {})
        e[key] = e.get(key, 0) + by


def concept_id(kind: str, name: str) -> str:
    return f"{PL.CONCEPT_KINDS[kind][0].lower()}:{slug(name)}"


def build(state: dict[str, Any], max_lit_authors: int = 6) -> G:
    g = G()
    pr = PL.use_preset(state["config"].get("preset", "materials"))
    CONCEPT_KINDS = pr["kinds"]
    subj, metric = pr["subject"], pr["metric"]
    works, ext, canon = state["works"], state["extract"], state["canonical"]
    resolved, profiles, dom, ideas = state["resolved"], state["profiles"], state["domain"], state["ideas"]
    domain_name = state["config"]["domain"]
    root = g.node(f"domain:{slug(domain_name)}", "ResearchDomain", name=domain_name,
                  description=dom.get("definition"), source="synthesis")

    # seed researchers: all their OpenAlex profiles map to one Person
    alias: dict[str, str] = {}
    seed_people: dict[str, str] = {}
    for key, r in resolved.items():
        primary = r["author_ids"][0]
        for a in r["author_ids"]:
            alias[a] = primary
        oa = r["openalex"][0]
        prof = profiles.get(key) or {}
        seed_people[key] = g.node(primary, "Person", name=r["name"], seed=True,
                                  institution=r["institution"], openalex_ids=r["author_ids"],
                                  orcid=prof.get("orcid") or oa.get("orcid"),
                                  works_count=sum(x.get("works_count") or 0 for x in r["openalex"]),
                                  cited_by=sum(x.get("cited_by_count") or 0 for x in r["openalex"]),
                                  h_index=oa.get("h_index"), title=prof.get("title"),
                                  department=prof.get("department"), homepage=prof.get("homepage"),
                                  lab=prof.get("lab"), bio=prof.get("bio"),
                                  awards=prof.get("awards"), funding=prof.get("funding"),
                                  techniques=prof.get("techniques_and_facilities"),
                                  informatics_angle=prof.get("informatics_angle"), source="openalex+web")
        g.edge(seed_people[key], "RESEARCHES_IN", root)

    # papers, venues, topics, people, institutions
    for w in works.values():
        p = ext.get(w["id"], {})
        g.node(w["id"], "Paper", name=w["title"], title=w["title"], year=w["year"], doi=w["doi"],
               type=w["type"], cited_by=w["cited_by"], venue=w["venue"], abstract=w["abstract"][:4000],
               tiers=w["tiers"], seed_of=w["seed_of"], oa_url=w["oa_url"], keywords=w["keywords"],
               summary=p.get("summary"), contribution_type=p.get("contribution_type"),
               ref_count_from_seed=w.get("ref_count_from_seed"), funders=w.get("funders"),
               source="openalex")
        if w["venue_id"]:
            g.node(w["venue_id"], "Venue", name=w["venue"], type=w["venue_type"], source="openalex")
            g.edge(w["id"], "PUBLISHED_IN", w["venue_id"])
        for t in w["topics"]:
            g.node(t["id"], "Topic", name=t["name"], source="openalex")
            g.edge(w["id"], "HAS_TOPIC", t["id"], score=t["score"])
            if t["subfield_id"]:
                g.node(t["subfield_id"], "Field", name=t["subfield"], level="subfield", source="openalex")
                g.node(t["field_id"], "Field", name=t["field"], level="field", source="openalex")
                g.node(t["domain_id"], "Field", name=t["domain"], level="domain", source="openalex")
                g.edge(t["id"], "IN_FIELD", t["subfield_id"])
                g.edge(t["subfield_id"], "IN_FIELD", t["field_id"])
                g.edge(t["field_id"], "IN_FIELD", t["domain_id"])
        is_seed = "seed" in w["tiers"]
        authors = w["authors"] if is_seed or len(w["authors"]) <= max_lit_authors else \
            w["authors"][:max_lit_authors - 1] + w["authors"][-1:]
        pids = []
        for a in authors:
            if not a["id"]:
                continue
            pid = alias.get(a["id"], a["id"])
            g.node(pid, "Person", name=a["name"], orcid=a["orcid"], seed=False, source="openalex")
            g.edge(pid, "AUTHORED", w["id"], position=a["position"], year=w["year"])
            pids.append(pid)
            for inst in a["institutions"]:
                g.node(inst["id"], "Institution", name=inst["name"], country=inst["country"],
                       type=inst["type"], source="openalex")
                e = g.edges.setdefault((pid, "AFFILIATED_WITH", inst["id"]), {})
                if w["year"]:
                    e["first_year"] = min(e.get("first_year", w["year"]), w["year"])
                    e["last_year"] = max(e.get("last_year", w["year"]), w["year"])
                e["papers"] = e.get("papers", 0) + 1
        if is_seed and len(pids) <= 40:
            for i, a in enumerate(pids):
                for b in pids[i + 1:]:
                    x, y = sorted((a, b))
                    g.bump(x, "COAUTHOR", y, key="papers")
    for w in works.values():
        for ref in w["refs"]:
            if ref in works:
                g.edge(w["id"], "CITES", ref)

    # concepts
    rel = {"problems": "ADDRESSES", "methods": "USES_METHOD", subj: "STUDIES",
           metric: "MEASURES", "datasets_tools": "USES_TOOL", "applications": "APPLIES_TO"}
    lookup: dict[str, dict[str, str]] = {}
    for kind, (label, _) in CONCEPT_KINDS.items():
        c = canon[kind]
        lookup[kind] = {k.lower(): v for k, v in c["map"].items()}
        for cn, info in c["canonical"].items():
            g.node(concept_id(kind, cn), label, name=cn, description=info.get("description"), source="extraction")
        for cn, info in c["canonical"].items():
            par = info.get("parent")
            if par and slug(par) != slug(cn):
                g.node(concept_id(kind, par), label, name=par, source="extraction", generalised=True)
                g.edge(concept_id(kind, cn), "BROADER", concept_id(kind, par))

    def cid(kind: str, name: str | None, create: str | None = None) -> str | None:
        if not name:
            return None
        cn = lookup[kind].get(name.lower()) or name
        nid = concept_id(kind, cn)
        if nid not in g.nodes and create:
            g.node(nid, CONCEPT_KINDS[kind][0], name=cn, source=create)
        return nid if nid in g.nodes else None

    seed_of_paper = {w["id"]: [seed_people[k] for k in w["seed_of"]] for w in works.values()}
    expert_rel = {"problems": "WORKS_ON", "methods": "EXPERT_IN", subj: "WORKS_WITH"}
    for wid, p in ext.items():
        if wid not in g.nodes:
            continue
        for kind in CONCEPT_KINDS:
            for x in p.get(kind) or []:
                name = x.get("name") if isinstance(x, dict) else x
                nid = cid(kind, name)
                if not nid:
                    continue
                props = {}
                if kind == "problems" and isinstance(x, dict):
                    props["context"] = x.get("description")
                    props["status_in_paper"] = x.get("status_in_paper")
                    props["evidence"] = x.get("evidence")
                if kind == "methods":
                    props["kind"] = x.get("kind")
                    g.nodes[nid].setdefault("kind", x.get("kind"))
                g.edge(wid, rel[kind], nid, **props)
                if kind in expert_rel:
                    for sp in seed_of_paper.get(wid, []):
                        g.bump(sp, expert_rel[kind], nid, key="papers")
        for i, r in enumerate(p.get("results") or []):
            if not r.get("statement"):
                continue
            rid = g.node(f"result:{wid}:{i}", "Result", name=r["statement"][:160], statement=r["statement"],
                         value=r.get("value"), unit=r.get("unit"), year=g.nodes[wid].get("year"),
                         source="extraction")
            g.edge(wid, "REPORTS", rid)
            if (m := cid(subj, r.get(pr["result_subject"]))):
                g.edge(rid, pr["on_subject"], m)
            if (mt := cid(metric, r.get(pr["result_metric"]))):
                g.edge(rid, pr["of_metric"], mt)
        for i, q in enumerate(p.get("future_work") or []):
            # Older extractions are plain strings; newer ones carry a kind, and engineering
            # next steps ("more experiments", "deploy it") are not open questions.
            text, kind = (q.get("text"), q.get("kind")) if isinstance(q, dict) else (q, None)
            if not text or kind == "engineering":
                continue
            qid = g.node(f"question:{wid}:{i}", "OpenQuestion", name=text[:160], text=text, kind=kind,
                         year=g.nodes[wid].get("year"), source="extraction")
            g.edge(wid, "RAISES", qid)

    # grounding in a catalogued vocabulary (optional stage)
    grounding = state.get("ground") or {}
    if grounding:
        for nid, c in grounding.get("classes", {}).items():
            g.node(nid, "OntologyClass", name=c["name"], vocabulary=c["vocabulary"],
                   iri=c.get("iri"), description=c.get("description"), source=c["vocabulary"])
        for nid, c in grounding.get("classes", {}).items():
            for par in c.get("parents") or []:
                g.edge(nid, "SUBCLASS_OF", par)
        rel = {"same": "SAME_AS", "narrower": "KIND_OF"}
        for kind, m in (grounding.get("concepts") or {}).items():
            if kind not in CONCEPT_KINDS:
                continue
            for name, x in m.items():
                # Grounding is keyed by canonical name, so attach to that concept's own node.
                # Routing through the alias map is wrong here: canonical.json can list a name
                # as a concept AND as an alias of another ('3D printing' -> 'additive
                # manufacturing'), and the verdict would land on the other node.
                nid = concept_id(kind, name)
                if nid not in g.nodes:
                    nid = concept_id(kind, lookup[kind].get(name.lower()) or name)
                if nid not in g.nodes:
                    continue
                # every concept carries the flag, grounded or not: the guardrail is that an
                # unaligned concept stays visible rather than silently missing
                g.nodes[nid]["grounded"] = bool(x.get("grounded"))
                if x.get("grounded"):
                    g.nodes[nid]["grounding"] = x["relation"]
                    g.edge(nid, rel[x["relation"]], x["target"],
                           confidence=x.get("confidence"), vocabulary=x.get("vocabulary"))
                else:
                    g.nodes[nid]["grounding_gap"] = x.get("reason")
    # profiles
    inst_by_name = {n["name"].lower(): nid for nid, n in g.nodes.items() if n["label"] == "Institution" and n.get("name")}

    def inst(name: str | None) -> str | None:
        if not name:
            return None
        return inst_by_name.get(name.lower()) or g.node(f"inst:{slug(name)}", "Institution", name=name, source="web")

    person_by_name = {PL.fold(n.get("name") or ""): nid for nid, n in g.nodes.items() if n["label"] == "Person"}
    for nid in seed_people.values():   # seed researchers win name collisions
        person_by_name[PL.fold(g.nodes[nid]["name"])] = nid

    def ext_person(name: str, **props: Any) -> str:
        nid = person_by_name.get(PL.fold(name))   # reuse an OpenAlex Person with the same name
        if nid:
            return nid
        nid = g.node(f"person:{slug(name)}", "Person", name=name, seed=False, source="web", **props)
        person_by_name[PL.fold(name)] = nid
        return nid

    for key, prof in profiles.items():
        if not prof:
            continue
        me = seed_people[key]
        for e in prof.get("education") or []:
            if (i := inst(e.get("institution"))):
                g.edge(me, "EDUCATED_AT", i, degree=e.get("degree"), year=str(e.get("year") or ""))
        for e in prof.get("positions") or []:
            if (i := inst(e.get("institution"))):
                g.edge(me, "HELD_POSITION", i, role=e.get("role"), years=str(e.get("years") or ""))
        for t in prof.get("research_themes") or []:
            tid = g.node(f"theme:{key}:{slug(t['name'])}", "Theme", name=t["name"],
                         description=t.get("description"), source="web+papers")
            g.edge(me, "HAS_THEME", tid)
            for pid in t.get("paper_ids") or []:
                g.edge(tid, "EVIDENCED_BY", pid)
        for m in prof.get("lab_members") or []:
            if m.get("name"):
                g.edge(ext_person(m["name"]), "MEMBER_OF_LAB", me, role=m.get("role"))
        for c in prof.get("external_collaborators") or []:
            if c.get("name"):
                pid = ext_person(c["name"], institution=c.get("institution"))
                g.edge(me, "COLLABORATES_WITH", pid, basis=c.get("basis"))

    # domain map
    for sa in dom.get("subareas") or []:
        sid = g.node(f"subarea:{slug(sa['name'])}", "Subarea", name=sa["name"],
                     description=sa.get("description"), source="synthesis")
        g.edge(root, "HAS_SUBAREA", sid)
        for pn in sa.get("problems") or []:
            if (nid := cid("problems", pn, create="synthesis")):
                g.edge(nid, "IN_SUBAREA", sid)
        for mn in sa.get("methods") or []:
            if (nid := cid("methods", mn, create="synthesis")):
                g.edge(nid, "USED_IN", sid)
    for w in works.values():
        for sa in w.get("subareas") or []:
            g.edge(w["id"], "LANDMARK_OF", f"subarea:{slug(sa)}")
    for op in dom.get("open_problems") or []:
        nid = cid("problems", op["name"], create="synthesis")
        g.nodes[nid].update({"open": True, "why_open": op.get("description"), "evidence": op.get("evidence")})
        if op.get("subarea"):
            g.edge(nid, "IN_SUBAREA", f"subarea:{slug(op['subarea'])}")
        g.edge(root, "HAS_OPEN_PROBLEM", nid)
    for t in dom.get("trends") or []:
        tid = g.node(f"trend:{slug(t['name'])}", "Trend", name=t["name"], description=t.get("description"),
                     since=str(t.get("since") or ""), source="synthesis")
        g.edge(root, "HAS_TREND", tid)
    for kp in dom.get("key_people") or []:
        pid = ext_person(kp["name"], institution=kp.get("institution"))
        g.nodes[pid].setdefault("known_for", kp.get("known_for"))
        if kp.get("subarea"):
            g.edge(pid, "KEY_FIGURE_IN", f"subarea:{slug(kp['subarea'])}")
        g.edge(pid, "KEY_FIGURE_IN", root)
    for kr in dom.get("key_resources") or []:
        nid = cid("datasets_tools", kr["name"], create="synthesis")
        g.nodes[nid].update({"kind": kr.get("kind"), "description": g.nodes[nid].get("description") or kr.get("description")})
        g.edge(root, "HAS_RESOURCE", nid)

    # ideas
    by_name = {r["name"].lower(): seed_people[k] for k, r in resolved.items()}
    for i, idea in enumerate(ideas):
        iid = g.node(f"idea:{i + 1:02d}", "Idea", name=idea["title"], hypothesis=idea.get("hypothesis"),
                     rationale=idea.get("rationale"), first_experiment=idea.get("first_experiment"),
                     data_needed=idea.get("data_needed"), expected_result=idea.get("expected_result"),
                     novelty=idea.get("novelty"), feasibility=idea.get("feasibility"),
                     impact=idea.get("impact"), risks=idea.get("risks"), subarea=idea.get("subarea"),
                     catalog_problem=idea.get("catalog_problem"), addresses_gap=idea.get("addresses_gap"),
                     source="synthesis")
        g.edge(root, "HAS_IDEA", iid)
        for n in idea.get("researchers") or []:
            pid = by_name.get(n.lower()) or next((v for k, v in by_name.items() if k.split()[-1] in n.lower()), None)
            if pid:
                g.edge(iid, "INVOLVES", pid)
        for pn in idea.get("problems") or []:
            g.edge(iid, "TACKLES", cid("problems", pn, create="synthesis"))
        for mn in idea.get("methods") or []:
            g.edge(iid, "USES_METHOD", cid("methods", mn, create="synthesis"))
        for mn in (idea.get("subjects") or []) + (idea.get("materials") or []):
            g.edge(iid, "STUDIES", cid(subj, mn, create="synthesis"))
        for wid in idea.get("supporting_papers") or []:
            g.edge(iid, "GROUNDED_IN", wid)
        if idea.get("open_problem"):
            g.edge(iid, "TARGETS", cid("problems", idea["open_problem"], create="synthesis"))
    if grounding:
        # Runs last, after the domain, ideas and profile sections have added their own
        # concept nodes. Flags every concept grounding never saw -- model-generated
        # BROADER parents, synthesised open problems, names outside the canonical set.
        # A missing flag reads as "unknown", which is worse than "not evaluated, and why".
        concept_labels = {lab for lab, _ in CONCEPT_KINDS.values()}
        for n in g.nodes.values():
            if n["label"] in concept_labels and "grounded" not in n:
                n["grounded"] = False
                n["grounding_gap"] = ("not evaluated: model-generated parent"
                                      if n.get("generalised") else
                                      f"not evaluated: source={n.get('source')}")
    if state.get("catalog"):
        add_catalog(g, state["catalog"], CONCEPT_KINDS)
    return g


# V3: labels the evidence layer shares with a problem catalog but means something else by.
# Where both layers use a label, the catalog keeps it and the evidence layer is renamed, so
# a catalog question ("how many cited papers per decade") counts catalog nodes only. A
# catalog Problem is a curated research question with a status; the kit's is a phrase from
# one paper. A catalog Topic is one of its ~35 topics; the kit's is OpenAlex's. Paper,
# Person, Institution and Venue take OpenAlex's own names (work, author, source). Leaving
# them shared made the DBMS scope benchmark count 8,769 "cited papers" instead of 2,679.
# ai_research's OpenQuestion is a gap the catalog page names; the kit's is one a paper states.
EVIDENCE_RELABEL = {"Problem": "PaperProblem", "Topic": "OpenAlexTopic", "Paper": "Work",
                    "Person": "Author", "Institution": "OpenAlexInstitution", "Venue": "OpenAlexSource",
                    "OpenQuestion": "PaperQuestion"}


def add_catalog(g: G, cat: dict[str, Any], kinds: dict) -> None:
    """Carry the catalog layer in unchanged and link it to the evidence layer."""
    for n in g.nodes.values():
        n["label"] = EVIDENCE_RELABEL.get(n["label"], n["label"])
        n.setdefault("layer", "evidence")
    d = Path(cat["dir"])
    shared = set(json.loads((d / "meta.json").read_text()).get("labels", {})) & {
        n["label"] for n in g.nodes.values()}
    if shared:
        raise ValueError(f"labels used by both layers with no evidence-layer name: {sorted(shared)}; "
                         f"add them to EVIDENCE_RELABEL")
    for line in (d / "nodes.jsonl").open():
        n = json.loads(line)
        if n["id"] in g.nodes:
            raise ValueError(f"catalog node id {n['id']!r} collides with an evidence-layer node")
        g.nodes[n["id"]] = {**n, "layer": "catalog"}
    for line in (d / "edges.jsonl").open():
        e = json.loads(line)
        g.edge(e.pop("src"), e.pop("rel"), e.pop("dst"), **e)

    # papers: the catalog node gains what OpenAlex knows; SAME_AS joins the two layers
    for pid, m in (cat.get("bridge") or {}).items():
        if pid not in g.nodes:
            continue
        w = g.nodes.get(m["work"])
        if w is not None:
            g.nodes[pid].update({"oa_id": m["work"], "oa_cited_by": w.get("cited_by"),
                                 "oa_year": w.get("year"), "oa_match": m["method"]})
            if w.get("funders"):
                g.nodes[pid]["oa_funders"] = w["funders"]
            g.edge(pid, "SAME_AS", m["work"], method=m["method"], score=m.get("score"))
    for pid, m in (cat.get("people") or {}).items():
        if pid in g.nodes and m["author"] in g.nodes:
            g.nodes[pid]["oa_author"] = m["author"]
            g.edge(pid, "SAME_AS", m["author"], method=m["method"])

    # run problems placed on catalog problems
    rel = {"same": "INSTANCE_OF", "narrower": "SUBPROBLEM_OF"}
    for name, x in ((cat.get("ground") or {}).get("concepts", {}).get("problems") or {}).items():
        nid = concept_id("problems", name)
        if nid in g.nodes:
            g.nodes[nid]["catalog_grounded"] = bool(x.get("grounded"))
            if x.get("grounded") and x["target"] in g.nodes:
                g.edge(nid, rel[x["relation"]], x["target"], confidence=x.get("confidence"))

    for n in list(g.nodes.values()):
        if n["label"] == "Idea" and n.get("catalog_problem") in g.nodes:
            g.edge(n["id"], "TACKLES", n["catalog_problem"], gap=n.get("addresses_gap"))

    # status from evidence: never overwrites the catalog's own status
    for pid, papers in (cat.get("evidence") or {}).items():
        if pid in g.nodes:
            g.nodes[pid]["evidence_papers"] = len(papers)
            for wid in papers:
                g.edge(wid, "EVIDENCE_FOR", pid)
    for pid, st in (cat.get("status") or {}).items():
        if pid not in g.nodes:
            continue
        g.nodes[pid].update({"status_checked": st["checked"],
                             "status_suggested": st.get("suggested_status"),
                             "status_rationale": st.get("rationale")})
        for v in st.get("papers") or []:
            g.edge(v["work"], "EVIDENCE_FOR", pid, verdict=v["verdict"], quote=v.get("quote"),
                   confidence=v.get("confidence"), checked=st["checked"])


def write(g: G, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    nf, ef = out_dir / "nodes.jsonl", out_dir / "edges.jsonl"
    with nf.open("w") as f:
        for n in g.nodes.values():
            f.write(json.dumps(n, ensure_ascii=False) + "\n")
    with ef.open("w") as f:
        for (s, r, d), p in g.edges.items():
            f.write(json.dumps({"src": s, "rel": r, "dst": d, **p}, ensure_ascii=False) + "\n")
    return nf, ef


def stats(g: G) -> dict[str, Any]:
    return {"nodes": len(g.nodes), "edges": len(g.edges),
            "labels": dict(Counter(n["label"] for n in g.nodes.values()).most_common()),
            "relations": dict(Counter(r for (_, r, _) in g.edges).most_common())}
