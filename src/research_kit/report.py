"""Deterministic markdown report: profiles, domain map, ideas, graph stats, showcase queries."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

def queries(preset: dict, relabel: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """The report's queries. With a catalog in the graph the evidence layer is renamed
    (graph.build.EVIDENCE_RELABEL); `relabel` rewrites `:Label` so these still read it."""
    S, ON = preset["kinds"][preset["subject"]][0], preset["on_subject"]
    qs = [
    ("Node counts by label",
     "MATCH (n) RETURN labels(n) AS label, count(n) AS n ORDER BY n DESC"),
    ("Seed researchers: papers authored",
     "MATCH (p:Person {seed: true})-[:AUTHORED]->(w:Paper) RETURN p.name, count(w) AS papers, p.h_index"),
    ("Top problems per seed researcher",
     "MATCH (p:Person {seed: true})-[e:WORKS_ON]->(x:Problem) RETURN p.name, x.name, e.papers "
     "ORDER BY e.papers DESC LIMIT 20"),
    ("Methods both seed researchers use",
     "MATCH (a:Person {seed: true})-[:EXPERT_IN]->(m:Method)<-[:EXPERT_IN]-(b:Person {seed: true}) "
     "WHERE a.name < b.name RETURN a.name, b.name, m.name LIMIT 25"),
    (f"{S} nodes shared by seed researchers",
     f"MATCH (a:Person {{seed: true}})-[:WORKS_WITH]->(m:{S})<-[:WORKS_WITH]-(b:Person {{seed: true}}) "
     "WHERE a.name < b.name RETURN a.name, b.name, m.name LIMIT 25"),
    ("Researcher pairs sharing the most problems (collaboration candidates)",
     "MATCH (a:Person {seed: true})-[:WORKS_ON]->(x:Problem)<-[:WORKS_ON]-(b:Person {seed: true}) "
     "WHERE a.name < b.name AND NOT (a)-[:COAUTHOR]-(b) RETURN a.name, b.name, count(x) AS shared "
     "ORDER BY shared DESC LIMIT 20"),
    ("Ideas per subarea",
     "MATCH (i:Idea) RETURN i.subarea, count(i) AS ideas ORDER BY ideas DESC"),
    ("Most-referenced literature (by seed papers)",
     "MATCH (w:Paper) WHERE w.ref_count_from_seed > 1 RETURN w.title, w.year, w.ref_count_from_seed "
     "ORDER BY w.ref_count_from_seed DESC LIMIT 12"),
    ("Top co-authors per seed researcher",
     "MATCH (p:Person {seed: true})-[e:COAUTHOR]-(c:Person) RETURN p.name, c.name, e.papers "
     "ORDER BY e.papers DESC LIMIT 20"),
    ("Open problems by subarea",
     "MATCH (x:Problem {open: true})-[:IN_SUBAREA]->(s:Subarea) RETURN s.name, x.name LIMIT 30"),
    ("Joint ideas (involve more than one seed researcher)",
     "MATCH (i:Idea)-[:INVOLVES]->(p:Person) WITH i, count(p) AS n WHERE n > 1 "
     "RETURN i.name, i.novelty, i.feasibility, i.impact ORDER BY i.impact DESC"),
    ("Idea -> grounding paper -> seed author",
     "MATCH (i:Idea)-[:GROUNDED_IN]->(w:Paper)<-[:AUTHORED]-(p:Person {seed: true}) "
     "RETURN i.name, w.title, p.name LIMIT 20"),
    ("Quantitative results by seed papers",
     f"MATCH (p:Person {{seed: true}})-[:AUTHORED]->(w:Paper)-[:REPORTS]->(r:Result)-[:{ON}]->(m:{S}) "
     "WHERE r.value IS NOT NULL RETURN p.name, m.name, r.statement LIMIT 15"),
    ]
    if not relabel:
        return qs
    pat = re.compile(r":(" + "|".join(map(re.escape, relabel)) + r")\b")
    return [(t, pat.sub(lambda m: ":" + relabel[m.group(1)], q)) for t, q in qs]


def _table(cols: list[str], rows: list[list[Any]], max_rows: int = 30) -> str:
    def cell(v: Any) -> str:
        s = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)
        return s.replace("|", "\\|").replace("\n", " ")[:160]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows[:max_rows]]
    return "\n".join(out)


def write_report(run_dir: Path, state: dict, stats: dict, loaded: dict, snap: Path, size: int,
                 version: str, results: list[tuple[str, str, dict]]) -> Path:
    cfg, works, dom = state["config"], state["works"], state["domain"]
    tiers: dict[str, int] = {}
    for w in works.values():
        for t in w["tiers"]:
            tiers[t] = tiers.get(t, 0) + 1
    L = [f"# Research graph: {', '.join(r['name'] for r in cfg['researchers'])}",
         f"Domain: **{cfg['domain']}** · samyama-graph **{version}** · snapshot `{snap.name}` ({size:,} bytes)",
         "",
         "## Build",
         f"- Graph: {stats['nodes']:,} nodes, {stats['edges']:,} edges (server after load: "
         f"{loaded['nodes']:,} nodes, {loaded['edges']:,} edges)",
         f"- Papers: {len(works)} ({', '.join(f'{k} {v}' for k, v in tiers.items())}); "
         f"extracted {len(state['extract'])}",
         "- Labels: " + ", ".join(f"{k} {v}" for k, v in stats["labels"].items()),
         "- Relations: " + ", ".join(f"{k} {v}" for k, v in stats["relations"].items()),
         ""]
    usage = run_dir / "usage.json"
    if usage.exists():
        u = json.loads(usage.read_text())
        L += [f"- Model calls: {u['calls']} · input {u['input_tokens']:,} · output {u['output_tokens']:,} "
              f"· web searches {u['web_search_requests']}",
              "  " + "; ".join(f"{m}: {v['calls']} calls" for m, v in u["by_model"].items()), ""]
    missing = [r["name"] for k, r in state["resolved"].items() if not state["profiles"].get(k)]
    if missing:
        L += [f"> **Incomplete:** the profile stage returned nothing for {', '.join(missing)}. "
              "Their bio, themes, education, positions and collaborators are absent here and absent "
              "from the graph (no EDUCATED_AT, HELD_POSITION, HAS_THEME or COLLABORATES_WITH edges). "
              "The domain map and the ideas below were written without their profiles, so they lean on "
              "the researchers whose profiles did arrive. Their paper-derived edges are unaffected. "
              "See the run log for the stage error.", ""]
    gr = state.get("ground")
    if gr:
        s = gr["stats"]
        voc = ", ".join(f"{v['id']} ({v['classes']:,} classes)" for v in gr.get("vocabularies", []))
        L += ["## Grounding",
              f"Concepts placed in the vocabularies the catalogue holds for the "
              f"**{gr.get('domain')}** domain: {voc}.", "",
              f"- **{s['grounded']:,} of {s['concepts']:,} distinct concepts placed "
              f"({s['grounded_pct']}%)**. The rest stay in the graph with grounded=false and a "
              f"grounding_gap reason; nothing was dropped or forced onto a near miss.",
              f"- {s.get('duplicates', 0)} case or whitespace duplicates judged once and counted once; "
              f"{s.get('rejected_out_of_list', 0)} answers refused for naming a class not offered; "
              f"{s.get('not_evaluated', 0)} concepts not evaluated because the call failed.", "",
              _table(["kind", "same", "narrower", "concepts", "placed %"],
                     [[k, v["same"], v["narrower"], v["concepts"], v["grounded_pct"]]
                      for k, v in s["by_kind"].items()]), ""]
        if gr.get("gaps"):
            L += ["Gaps the vocabulary catalogue recorded for this domain when the run was grounded "
                  "(snapshotted in ground.json; the catalog may have moved on since):", ""] + \
                 [f"- {g}" for g in gr["gaps"]] + [""]
    L += ["## Researchers", ""]
    for key, r in state["resolved"].items():
        p = state["profiles"].get(key) or {}
        L += [f"### {r['name']} — {p.get('title') or ''} {p.get('department') or ''}, {r['institution']}",
              f"- OpenAlex: {', '.join(r['author_ids'])} ({r.get('reason') or ''})"]
        if not p:
            L += ["- **No profile: the profile stage failed for this researcher.** Everything below "
                  "this line comes from their papers alone.", ""]
        elif p.get("profile_source"):
            L += [f"- **Partial profile** ({p['profile_source']}): no faculty page, CV, ORCID or news "
                  "went into it, so education, positions, awards and funding may be thin or absent.", ""]
        L += [f"- Homepage: {p.get('homepage')}; lab: {p.get('lab')}",
              f"- {p.get('bio') or ''}", "", "**Themes**"]
        L += [f"- **{t['name']}**: {t.get('description', '')}" for t in p.get("research_themes") or []]
        L += ["", "**Key contributions**"] + [f"- {c}" for c in p.get("key_contributions") or []]
        L += ["", f"**Informatics angle:** {p.get('informatics_angle') or ''}", ""]
    L += ["## Domain map", "", dom.get("definition") or "", ""]
    for sa in dom.get("subareas") or []:
        L.append(f"- **{sa['name']}**: {sa.get('description', '')}")
    L += ["", "### Open problems"] + [f"- **{o['name']}** ({o.get('subarea', '')}): {o.get('description', '')}"
                                      for o in dom.get("open_problems") or []]
    L += ["", "### Trends"] + [f"- **{t['name']}** (since {t.get('since', '?')}): {t.get('description', '')}"
                               for t in dom.get("trends") or []]
    L += ["", "## Research ideas", "",
          _table(["#", "Idea", "Researchers", "N", "F", "I", "Hypothesis"],
                 [[i + 1, x["title"], ", ".join(x.get("researchers") or []), x.get("novelty"),
                   x.get("feasibility"), x.get("impact"), x.get("hypothesis")]
                  for i, x in enumerate(state["ideas"])], 50), ""]
    for i, x in enumerate(state["ideas"]):
        L += [f"### {i + 1}. {x['title']}", f"- Hypothesis: {x.get('hypothesis')}",
              f"- Rationale: {x.get('rationale')}", f"- First experiment: {x.get('first_experiment')}",
              f"- Grounded in: {', '.join(x.get('supporting_papers') or [])}; risks: {x.get('risks')}", ""]
    L += ["## Showcase queries", ""]
    for title, q, res in results:
        L += [f"### {title}", "```cypher", q, "```"]
        if res.get("error"):
            L += [f"ERROR: {res['error'][:300]}", ""]
        else:
            L += [f"{len(res.get('records', []))} rows", "", _table(res.get("columns", []), res.get("records", [])), ""]
    f = run_dir / "REPORT.md"
    f.write_text("\n".join(L))
    return f
