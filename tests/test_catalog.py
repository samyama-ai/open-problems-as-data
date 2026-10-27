"""V3 catalog layer: bridge, seeding, people links, evidence, and the graph merge."""

import json

import pytest
from types import SimpleNamespace as NS

from research_kit import catalog as CT
from research_kit.graph import build as B


def _cat(tmp_path):
    nodes = [
        {"id": "t1", "label": "Topic", "name": "Query Processing"},
        {"id": "t1/joins", "label": "Problem", "title": "Worst-case optimal joins", "status": "open",
         "statement": "Evaluate cyclic joins in time bounded by the AGM bound."},
        {"id": "paper:a", "label": "Paper", "title": "Worst-case optimal join algorithms", "year": 2012,
         "doi": "https://doi.org/10.1145/X1"},
        {"id": "paper:b", "label": "Paper", "title": "Leapfrog Triejoin: a simple join", "year": 2014, "doi": ""},
        {"id": "person:n", "label": "Person", "name": "Ngo"},
    ]
    edges = [{"src": "t1/joins", "rel": "IN_TOPIC", "dst": "t1"},
             {"src": "t1/joins", "rel": "CITES", "dst": "paper:a"},
             {"src": "t1/joins", "rel": "CITES", "dst": "paper:b"},
             {"src": "person:n", "rel": "ACTIVE_ON", "dst": "t1/joins"}]
    (tmp_path / "nodes.jsonl").write_text("\n".join(json.dumps(n) for n in nodes) + "\n")
    (tmp_path / "edges.jsonl").write_text("\n".join(json.dumps(e) for e in edges) + "\n")
    labels = {}
    for n in nodes:
        labels[n["label"]] = labels.get(n["label"], 0) + 1
    (tmp_path / "meta.json").write_text(json.dumps({"as_of": "2026-09-09", "labels": labels}))
    return CT.Catalog.load(tmp_path)


def _work(wid, title, year, authors, doi=None):
    return {"id": f"https://openalex.org/{wid}", "doi": doi, "title": title, "publication_year": year,
            "authorships": [{"author": {"id": f"https://openalex.org/{a}", "display_name": n},
                             "institutions": [{"display_name": "Uni"}]} for a, n in authors]}


class FakeOA:
    def __init__(self):
        self.calls = []

    def get(self, path, **p):
        self.calls.append(p)
        if "filter" in p:
            return {"results": [_work("W1", "Worst-case optimal join algorithms", 2012,
                                      [("A1", "Hung Q. Ngo"), ("A2", "Ely Porat")], doi="https://doi.org/10.1145/x1")]}
        return {"results": [_work("W9", "Leapfrog triejoin: a simple, worst-case optimal join", 2014,
                                  [("A3", "Todd Veldhuizen")]),
                            _work("W2", "Leapfrog Triejoin: A Simple Join", 2014, [("A3", "Todd L. Veldhuizen")])]}


def test_bridge_by_doi_then_title_and_year(tmp_path):
    cat = _cat(tmp_path)
    br = CT.bridge(FakeOA(), cat, lambda m: None)
    assert br["papers"]["paper:a"] == {"work": "W1", "method": "doi", "score": 1.0}   # DOI case-folded
    assert br["papers"]["paper:b"]["work"] == "W2" and br["papers"]["paper:b"]["method"] == "title+year"
    assert br["unresolved"] == []


def test_seed_and_people_links(tmp_path):
    cat = _cat(tmp_path)
    br = CT.bridge(FakeOA(), cat, lambda m: None)
    assert CT.seed_researchers(cat, br, n=2, since=2013) == []          # nobody has 2 catalog papers
    seed = CT.seed_researchers(cat, br, n=2, since=2013, min_papers=1)
    assert seed[0]["author_ids"] == ["A3"] and seed[0]["topic"] == "t1"  # recent paper ranks first
    assert CT.link_people(cat, br) == {"person:n": {"author": "A1", "name": "Hung Q. Ngo", "method": "active_on"}}


def test_evidence_follows_the_alias_map():
    cg = {"concepts": {"problems": {"wcoj": {"grounded": True, "target": "t1/joins", "relation": "same"}}}}
    canon = {"map": {"Worst-case optimal join": "wcoj"}}
    ext = {"W5": {"problems": [{"name": "worst-case optimal join"}]}, "W6": {"problems": ["other"]}}
    assert CT.evidence(cg, canon, ext) == {"t1/joins": ["W5"]}


def test_add_catalog_relabels_evidence_and_links_layers(tmp_path):
    _cat(tmp_path)
    g = B.G()
    g.node("W1", "Paper", title="x", cited_by=900, year=2012, funders=["NSF"])
    g.node("problem:wcoj", "Problem", name="wcoj")
    g.node("T55", "Topic", name="Database Systems")
    state = {"dir": str(tmp_path), "bridge": {"paper:a": {"work": "W1", "method": "doi", "score": 1.0}},
             "people": {}, "ground": {"concepts": {"problems": {"wcoj": {"grounded": True, "relation": "same",
                                                                          "target": "t1/joins"}}}},
             "evidence": {"t1/joins": ["W1"]},
             "status": {"t1/joins": {"checked": "2026-10-19", "suggested_status": None, "papers": [
                 {"work": "W1", "verdict": "advances", "quote": "q", "confidence": 0.8}]}}}
    B.add_catalog(g, state, {})
    assert g.nodes["problem:wcoj"]["label"] == "PaperProblem" and g.nodes["T55"]["label"] == "OpenAlexTopic"
    assert g.nodes["W1"]["label"] == "Work" and g.nodes["paper:a"]["label"] == "Paper"   # catalog keeps Paper
    assert g.nodes["t1/joins"]["label"] == "Problem" and g.nodes["t1/joins"]["status"] == "open"
    assert g.nodes["paper:a"]["oa_cited_by"] == 900 and g.nodes["paper:a"]["oa_funders"] == ["NSF"]
    assert ("paper:a", "SAME_AS", "W1") in g.edges
    assert ("problem:wcoj", "INSTANCE_OF", "t1/joins") in g.edges
    assert g.edges[("W1", "EVIDENCE_FOR", "t1/joins")]["verdict"] == "advances"
    assert ("t1/joins", "IN_TOPIC", "t1") in g.edges                 # catalog edges carried in


def test_a_label_both_layers_use_without_a_rename_stops_the_build(tmp_path):
    _cat(tmp_path)
    g = B.G()
    g.node("x1", "Gap", name="an evidence-layer node under a catalog label")
    labels = json.loads((tmp_path / "meta.json").read_text())
    labels["labels"]["Gap"] = 1
    (tmp_path / "meta.json").write_text(json.dumps(labels))
    with pytest.raises(ValueError, match="Gap"):
        B.add_catalog(g, {"dir": str(tmp_path)}, {})


def test_status_never_suggests_without_a_solving_paper(tmp_path):
    cat = _cat(tmp_path)
    llm = NS(json_call=lambda *a, **k: {"papers": [{"i": 0, "verdict": "advances", "quote": "q"}],
                                        "suggested_status": "solved"},
             pmap=lambda fn, items, label, batchable=False: [fn(i) for i in items])
    works = {"W1": {"title": "t", "year": 2025}}
    st = CT.status_check(llm, cat, {"t1/joins": ["W1"]}, works, {}, "{title}{status}{as_of}{statement}"
                         "{upper}{lower}{gap}{papers}", "s")
    assert st["t1/joins"]["suggested_status"] is None
    assert st["t1/joins"]["papers"][0]["verdict"] == "advances"


def test_idea_targets_and_engineering_future_work(tmp_path):
    _cat(tmp_path)
    g = B.G()
    g.node("idea:01", "Idea", name="i", catalog_problem="t1/joins", addresses_gap="cyclic case")
    B.add_catalog(g, {"dir": str(tmp_path)}, {})
    assert g.edges[("idea:01", "TACKLES", "t1/joins")]["gap"] == "cyclic case"


def test_bridge_by_arxiv_id_maps_back_through_locations(tmp_path):
    nodes = [{"id": "paper:arxiv:1508.07909", "label": "Paper", "title": "Neural Machine Translation of Rare Words",
              "year": 2016, "arxiv_id": "1508.07909", "doi": None}]
    (tmp_path / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    (tmp_path / "edges.jsonl").write_text("")
    cat = CT.Catalog.load(tmp_path)

    class OA:
        def get(self, path, **p):
            assert "10.48550/arxiv.1508.07909" in p["filter"] and "locations" in p["select"]
            w = _work("W7", "Neural Machine Translation of Rare Words with Subword Units", 2016, [],
                      doi="https://doi.org/10.18653/v1/p16-1162")      # the publisher's DOI, not arXiv's
            w["locations"] = [{"landing_page_url": "http://arxiv.org/abs/1508.07909v5"}]
            return {"results": [w]}

    br = CT.bridge(OA(), cat, lambda m: None)
    assert br["papers"]["paper:arxiv:1508.07909"] == {"work": "W7", "method": "arxiv", "score": 1.0}
    assert "locations" not in br["works"]["W7"]
    assert CT.arxiv_key("arXiv:1706.03762v5") == "1706.03762" and CT.arxiv_key("cs/0101001") == "cs/0101001"


def test_bridge_stops_on_openalex_budget(tmp_path):
    from research_kit.sources.openalex import BudgetExhausted
    cat = _cat(tmp_path)

    class OA(FakeOA):
        def get(self, path, **p):
            if "search" in p:
                raise BudgetExhausted("used up")
            return super().get(path, **p)

    with pytest.raises(BudgetExhausted):          # a swallowed error would checkpoint a partial bridge
        CT.bridge(OA(), cat, lambda m: None)
