"""Offline tests: JSON parsing, abstract rebuild, graph build from a tiny state."""

import pytest

from research_kit import pipeline as PL
from research_kit.graph import build as B
from research_kit.llm import parse_json
from research_kit.sources.openalex import abstract_text


def test_parse_json_fenced_and_bare():
    assert parse_json('note\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('here: [1, 2] done') == [1, 2]


def test_abstract_text():
    assert abstract_text({"hello": [0], "world": [1], "big": [2]}) == "hello world big"


def _state():
    work = lambda wid, authors, refs=(), seed_of=("alice",): {
        "id": wid, "doi": None, "title": f"Paper {wid}", "year": 2024, "type": "article", "cited_by": 3,
        "venue": "J", "venue_id": "S1", "venue_type": "journal", "oa_url": None, "abstract": "x",
        "authors": [{"id": a, "name": a, "orcid": None, "position": "first",
                     "institutions": [{"id": "I1", "name": "IISc", "country": "IN", "type": "education"}]}
                    for a in authors],
        "topics": [], "keywords": [], "refs": list(refs), "tiers": ["seed"], "seed_of": list(seed_of)}
    return {
        "config": {"domain": "materials", "researchers": [{"name": "Alice A", "institution": "IISc"}]},
        "resolved": {"alice": {"name": "Alice A", "institution": "IISc", "author_ids": ["A1", "A9"],
                               "openalex": [{"id": "A1", "works_count": 2, "cited_by_count": 5, "h_index": 1}]}},
        "works": {"W1": work("W1", ["A1", "A2"], refs=["W2"]), "W2": work("W2", ["A9", "A2"])},
        "extract": {"W1": {"summary": "s", "problems": [{"name": "dendrites"}], "methods": [{"name": "XRD", "kind": "characterization"}],
                           "materials": ["LLZO"], "properties": [], "datasets_tools": [], "applications": [],
                           "results": [{"statement": "1 mS/cm", "material": "LLZO", "value": "1"}], "future_work": ["why?"]},
                    "W2": {"problems": [{"name": "Li dendrite growth"}], "methods": [{"name": "X-ray diffraction"}]}},
        "canonical": {k: {"map": {}, "canonical": {}} for k in PL.PRESETS["materials"]["kinds"]} | {
            "problems": {"map": {"dendrites": "lithium dendrites", "Li dendrite growth": "lithium dendrites"},
                         "canonical": {"lithium dendrites": {"name": "lithium dendrites", "parent": "battery failure"}}},
            "methods": {"map": {"XRD": "X-ray diffraction", "X-ray diffraction": "X-ray diffraction"},
                        "canonical": {"X-ray diffraction": {"name": "X-ray diffraction"}}},
            "materials": {"map": {"LLZO": "LLZO"}, "canonical": {"LLZO": {"name": "LLZO"}}}},
        "profiles": {"alice": {"research_themes": [{"name": "SSB", "paper_ids": ["W1"]}]}},
        "domain": {"subareas": [{"name": "Batteries", "problems": ["lithium dendrites"]}],
                   "open_problems": [{"name": "interface stability", "subarea": "Batteries"}]},
        "ideas": [{"title": "Idea", "researchers": ["Alice A"], "problems": ["dendrites"], "supporting_papers": ["W1"]}],
    }


def test_build_merges_profiles_and_synonyms():
    g = B.build(_state())
    assert "A9" not in g.nodes and g.nodes["A1"]["seed"] is True          # split profile merged
    assert ("A1", "WORKS_ON", "problem:lithium-dendrites") in g.edges
    assert g.edges[("A1", "WORKS_ON", "problem:lithium-dendrites")]["papers"] == 2   # synonyms merged
    assert ("problem:lithium-dendrites", "BROADER", "problem:battery-failure") in g.edges
    assert ("W1", "CITES", "W2") in g.edges
    assert ("A1", "COAUTHOR", "A2") in g.edges and g.edges[("A1", "COAUTHOR", "A2")]["papers"] == 2
    assert ("idea:01", "TACKLES", "problem:lithium-dendrites") in g.edges
    assert g.nodes["problem:interface-stability"]["open"] is True
    assert ("result:W1:0", "ON_MATERIAL", "material:llzo") in g.edges


def test_fold_and_slug():
    assert PL.fold("M. Tamer Özsu") == "m. tamer ozsu"
    assert PL.slug("Aydın Buluç") == "aydin-buluc"
    assert PL.fold("Tina Eliassi\u2010Rad") == "tina eliassi-rad"


def test_cs_preset_labels():
    st = _state()
    st["config"]["preset"] = "cs"
    st["canonical"] = {k: {"map": {}, "canonical": {}} for k in PL.PRESETS["cs"]["kinds"]} | {
        "problems": st["canonical"]["problems"], "methods": st["canonical"]["methods"],
        "subjects": {"map": {"LLZO": "property graphs"}, "canonical": {"property graphs": {"name": "property graphs"}}}}
    st["extract"]["W1"]["subjects"] = st["extract"]["W1"].pop("materials")
    st["extract"]["W1"]["results"] = [{"statement": "2x faster", "subject": "LLZO"}]
    g = B.build(st)
    assert g.nodes["subject:property-graphs"]["label"] == "Subject"
    assert ("result:W1:0", "ON_SUBJECT", "subject:property-graphs") in g.edges
    assert ("A1", "WORKS_WITH", "subject:property-graphs") in g.edges
    PL.use_preset("materials")


def test_bio_preset_labels():
    st = _state()
    st["config"]["preset"] = "bio"
    st["canonical"] = {k: {"map": {}, "canonical": {}} for k in PL.PRESETS["bio"]["kinds"]} | {
        "problems": st["canonical"]["problems"], "methods": st["canonical"]["methods"],
        "targets": {"map": {"LLZO": "CD19"}, "canonical": {"CD19": {"name": "CD19"}}}}
    st["extract"]["W1"]["targets"] = st["extract"]["W1"].pop("materials")
    st["extract"]["W1"]["results"] = [{"statement": "90% CR", "target": "LLZO"}]
    g = B.build(st)
    assert g.nodes["target:cd19"]["label"] == "Target"
    assert ("result:W1:0", "ON_TARGET", "target:cd19") in g.edges
    assert ("A1", "WORKS_WITH", "target:cd19") in g.edges
    PL.use_preset("materials")


def test_media_preset_labels():
    st = _state()
    st["config"]["preset"] = "media"
    st["canonical"] = {k: {"map": {}, "canonical": {}} for k in PL.PRESETS["media"]["kinds"]} | {
        "problems": st["canonical"]["problems"], "methods": st["canonical"]["methods"],
        "subjects": {"map": {"LLZO": "connected TV"},
                     "canonical": {"connected TV": {"name": "connected TV"}}}}
    st["extract"]["W1"]["subjects"] = st["extract"]["W1"].pop("materials")
    st["extract"]["W1"]["results"] = [{"statement": "18% lift", "subject": "LLZO"}]
    g = B.build(st)
    assert g.nodes["subject:connected-tv"]["label"] == "Subject"
    assert ("result:W1:0", "ON_SUBJECT", "subject:connected-tv") in g.edges
    assert ("A1", "WORKS_WITH", "subject:connected-tv") in g.edges
    PL.use_preset("materials")


def test_check_port_rejects_a_busy_port():
    """The graph stage runs last; a clash must be named, not echoed as a docker command."""
    import socket as _s

    from research_kit.graph.samyama import check_port
    with _s.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        busy = srv.getsockname()[1]
        with pytest.raises(RuntimeError, match=f"port {busy} is in use"):
            check_port(busy, "research-kit-does-not-exist")


def test_check_port_allows_a_free_port():
    import socket as _s

    from research_kit.graph.samyama import check_port
    with _s.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    check_port(free, "research-kit-does-not-exist")


def test_repair_keeps_a_concept_that_was_also_an_alias():
    c = {"map": {"LLZO": "garnet solid electrolytes", "Li7La3Zr2O12": "garnet solid electrolytes",
                 "garnet": "garnet solid electrolytes"},
         "canonical": {"LLZO": {"name": "LLZO"},
                       "garnet solid electrolytes": {"name": "garnet solid electrolytes"}}}
    fixed, n = PL.repair_canonical(c)
    assert fixed["map"]["LLZO"] == "LLZO"                       # papers naming LLZO keep it
    assert fixed["map"]["Li7La3Zr2O12"] == "garnet solid electrolytes"
    assert fixed["canonical"]["LLZO"]["parent"] == "garnet solid electrolytes"
    assert n == {"alias_conflicts": 1, "duplicates_merged": 0}


def test_repair_merges_case_space_and_plural_duplicates():
    c = {"map": {"ceramic": "Ceramics", "ceramics": "ceramics", "CERAMICS": "ceramics",
                 "phase transitions": "phase transitions", "phase transition": "phase transition",
                 "PT": "phase transition"},
         "canonical": {"Ceramics": {"name": "Ceramics"}, "ceramics": {"name": "ceramics"},
                       "thin film ": {"name": "thin film ", "description": "d"},
                       "thin film": {"name": "thin film"},
                       "phase transitions": {"name": "phase transitions"},
                       "phase transition": {"name": "phase transition"}}}
    fixed, n = PL.repair_canonical(c)
    assert set(fixed["canonical"]) == {"ceramics", "thin film", "phase transition"}
    assert fixed["map"]["ceramic"] == "ceramics" and fixed["map"]["Ceramics"] == "ceramics"
    assert fixed["map"]["phase transitions"] == "phase transition"   # plural is a duplicate, not a child
    assert fixed["canonical"]["thin film"]["description"] == "d"    # nothing lost in the merge
    assert n["duplicates_merged"] == 3 and n["alias_conflicts"] == 0


def test_repair_is_idempotent():
    c = {"map": {"LLZO": "garnet", "x": "Ceramics"},
         "canonical": {"LLZO": {"name": "LLZO"}, "garnet": {"name": "garnet"},
                       "Ceramics": {"name": "Ceramics"}, "ceramics": {"name": "ceramics"}}}
    once, _ = PL.repair_canonical(c)
    twice, n = PL.repair_canonical(once)
    assert twice == once and n == {"alias_conflicts": 0, "duplicates_merged": 0}
