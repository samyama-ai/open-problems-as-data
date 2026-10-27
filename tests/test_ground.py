"""Offline tests for the ground stage: retrieval, the refusal guardrail, and the graph."""

import json

from test_build import _state

from research_kit import ground as GR
from research_kit import pipeline as PL
from research_kit.graph import build as B


def _vocab(tmp_path):
    d = tmp_path / "build" / "emmo"
    d.mkdir(parents=True)
    nodes = [
        {"id": "emmo:Mat", "name": "Material"},
        {"id": "emmo:Proc", "name": "ManufacturingProcess"},
        {"id": "emmo:Diff", "name": "Diffraction", "description": "a characterisation technique"},
        {"id": "emmo:XRD", "name": "XRayDiffraction"},
        {"id": "emmo:Ox", "name": "OxideMaterial"},
        {"id": "emmo:Maxwell", "name": "Maxwell", "description": "unit of magnetic flux"},
    ]
    edges = [{"src": "emmo:XRD", "rel": "BROADER", "dst": "emmo:Diff"},
             {"src": "emmo:Ox", "rel": "BROADER", "dst": "emmo:Mat"}]
    (d / "nodes.jsonl").write_text("\n".join(json.dumps(n) for n in nodes))
    (d / "edges.jsonl").write_text("\n".join(json.dumps(e) for e in edges))
    exp = tmp_path / "catalog" / "export"
    exp.mkdir(parents=True)
    (exp / "materials.json").write_text(json.dumps(
        {"domain": "materials", "grounded_by": [], "candidates": ["emmo"], "gaps": ["g"]}))
    return tmp_path


def test_words_split_camel_case():
    assert GR.words("ElectricConductivity") == ["electric", "conductivity"]
    assert GR.words("X-ray diffraction") == ["ray", "diffraction"]


def test_candidates_rank_by_shared_rare_words(tmp_path):
    _, vocabs = GR.locate(_vocab(tmp_path), "materials")
    v = vocabs[0]
    assert v.candidates("X-ray diffraction")[0] == "emmo:XRD"
    assert v.ancestors("emmo:XRD") == ["emmo:Diff"]


def test_locate_explains_an_unbuilt_vocabulary(tmp_path):
    root = _vocab(tmp_path)
    (root / "catalog" / "export" / "cs.json").write_text(json.dumps({"candidates": ["cso"]}))
    try:
        GR.locate(root, "cs")
    except GR.GroundingUnavailable as e:
        assert "fetch_vocab.py" in str(e)
    else:
        raise AssertionError("expected GroundingUnavailable")


class FakeLLM:
    """Answers by looking at what it was shown, the way the real prompt does."""
    def __init__(self, picks):
        self.picks = picks                     # concept name -> (relation, candidate number)

    def json_call(self, stage, key, prompt, **kw):
        out = []
        for line in prompt.splitlines():
            if line.startswith("[") and '"' in line:
                i = int(line[1:line.index("]")])
                name = line.split('"')[1]
                rel, cand = self.picks.get(name, ("none", None))
                out.append({"i": i, "relation": rel, "candidate": cand, "confidence": 0.9})
        return {"results": out}

    def pmap(self, fn, items, label, batchable=False):
        return [fn(x) for x in items]


def _canon():
    return {"methods": {"canonical": {"X-ray diffraction": {}, "Maxwell": {}}},
            "materials": {"canonical": {"LLZO garnet": {}, "zzqx": {}}}}


def test_ground_places_refuses_and_flags(tmp_path):
    _, vocabs = GR.locate(_vocab(tmp_path), "materials")
    llm = FakeLLM({"X-ray diffraction": ("same", 1),        # XRD is candidate 1
                   "Maxwell": ("narrower", 99)})            # a number it was never shown
    out = GR.ground(llm, _canon(), vocabs, "materials", {}, "{domain}\n{items}", "sys")
    m = out["concepts"]
    assert m["methods"]["X-ray diffraction"]["target"] == "emmo:XRD"
    assert m["methods"]["X-ray diffraction"]["relation"] == "same"
    # guardrail 1: an answer outside the offered list is refused, not trusted
    assert m["methods"]["Maxwell"]["grounded"] is False
    assert out["stats"]["rejected_out_of_list"] == 1
    # guardrail 2: no shared word means no call and an explicit flag, not a drop
    assert m["materials"]["zzqx"] == {"grounded": False, "reason": "no candidate shares a word"}
    # ancestors travel with the target so the build never needs the ontologies repo
    assert set(out["classes"]) == {"emmo:XRD", "emmo:Diff"}


def test_build_adds_classes_and_keeps_unaligned_concepts():
    st = _state()
    st["ground"] = {
        "classes": {"emmo:XRD": {"name": "XRayDiffraction", "vocabulary": "emmo",
                                 "parents": ["emmo:Diff"]},
                    "emmo:Diff": {"name": "Diffraction", "vocabulary": "emmo", "parents": []}},
        "concepts": {"methods": {"X-ray diffraction": {"grounded": True, "relation": "narrower",
                                                       "target": "emmo:XRD", "vocabulary": "emmo",
                                                       "confidence": 0.8}},
                     "materials": {"LLZO": {"grounded": False, "reason": "model chose none"}}}}
    g = B.build(st)
    m = "method:x-ray-diffraction"
    assert (m, "KIND_OF", "emmo:XRD") in g.edges
    assert ("emmo:XRD", "SUBCLASS_OF", "emmo:Diff") in g.edges
    assert g.nodes["emmo:XRD"]["label"] == "OntologyClass"
    assert g.nodes[m]["grounded"] is True
    llzo = g.nodes["material:llzo"]
    assert llzo["grounded"] is False and llzo["grounding_gap"] == "model chose none"
    # the model-invented parent is untouched: grounding adds authority, it does not delete
    assert ("problem:lithium-dendrites", "BROADER", "problem:battery-failure") in g.edges


def test_ground_is_off_by_default():
    assert PL.Config(domain="d", researchers=[], run_dir=None).ground_domain is None


def test_a_failed_call_is_not_recorded_as_a_verdict(tmp_path):
    """pmap returns None for a call that failed every retry; that is not 'model chose none'."""
    _, vocabs = GR.locate(_vocab(tmp_path), "materials")

    class Broken(FakeLLM):
        def pmap(self, fn, items, label, batchable=False):
            return [None for _ in items]

    out = GR.ground(Broken({}), _canon(), vocabs, "materials", {}, "{domain}\n{items}", "sys")
    assert out["concepts"]["methods"]["X-ray diffraction"]["reason"] == "grounding call failed"
    assert out["stats"]["not_evaluated"] >= 1


def test_case_duplicates_are_judged_once_and_counted_once(tmp_path):
    _, vocabs = GR.locate(_vocab(tmp_path), "materials")
    canon = {"methods": {"canonical": {"X-ray diffraction": {}, "x-ray diffraction ": {}}}}
    calls = []

    class Counting(FakeLLM):
        def json_call(self, stage, key, prompt, **kw):
            calls.append(prompt.count('"x-ray diffraction'.lower()) + prompt.count('"X-ray'))
            return super().json_call(stage, key, prompt, **kw)

    out = GR.ground(Counting({"X-ray diffraction": ("same", 1)}), canon, vocabs,
                    "materials", {}, "{domain}\n{items}", "sys")
    assert sum(calls) == 1                                   # judged once
    dup = out["concepts"]["methods"]["x-ray diffraction "]
    assert dup["target"] == "emmo:XRD" and dup["duplicate_of"] == "X-ray diffraction"
    assert out["stats"]["concepts"] == 1 and out["stats"]["grounded"] == 1
    assert out["stats"]["duplicates"] == 1


def test_every_concept_node_carries_a_flag_when_grounding_ran():
    st = _state()
    st["ground"] = {"classes": {}, "concepts": {"methods": {}}}
    g = B.build(st)
    labels = {lab for lab, _ in PL.PRESETS["materials"]["kinds"].values()}
    concepts = [n for n in g.nodes.values() if n["label"] in labels]
    assert concepts and all("grounded" in n for n in concepts)
    parent = g.nodes["problem:battery-failure"]                # model-generated BROADER parent
    assert parent["grounding_gap"] == "not evaluated: model-generated parent"


def test_grounding_attaches_to_the_concepts_own_node():
    """canonical.json may list a name as a concept and as an alias of another."""
    st = _state()
    st["canonical"]["methods"]["canonical"]["XRD"] = {"name": "XRD"}   # also an alias above
    st["ground"] = {
        "classes": {"emmo:A": {"name": "A", "vocabulary": "emmo", "parents": []},
                    "emmo:B": {"name": "B", "vocabulary": "emmo", "parents": []}},
        "concepts": {"methods": {
            "X-ray diffraction": {"grounded": True, "relation": "same", "target": "emmo:A"},
            "XRD": {"grounded": True, "relation": "same", "target": "emmo:B"}}}}
    g = B.build(st)
    assert ("method:x-ray-diffraction", "SAME_AS", "emmo:A") in g.edges
    assert ("method:xrd", "SAME_AS", "emmo:B") in g.edges
    assert ("method:x-ray-diffraction", "SAME_AS", "emmo:B") not in g.edges


def test_merged_vocabularies_walk_ancestors_across_builds(tmp_path):
    """A battery class whose parent lives in EMMO core must reach core through the merge."""
    root = _vocab(tmp_path)
    d = root / "build" / "emmo-domain-battery"
    d.mkdir(parents=True)
    (d / "nodes.jsonl").write_text(json.dumps(
        {"id": "emmo:SolidElectrolyte", "name": "SolidElectrolyte", "vocabulary": "emmo-domain-battery"}))
    (d / "edges.jsonl").write_text(json.dumps(
        {"src": "emmo:SolidElectrolyte", "rel": "BROADER", "dst": "emmo:Ox", "external": True}))
    spec = json.loads((root / "catalog" / "export" / "materials.json").read_text())
    spec["candidates"] = ["emmo", "emmo-domain-battery"]
    (root / "catalog" / "export" / "materials.json").write_text(json.dumps(spec))

    spec, vocabs = GR.locate(root, "materials")
    assert len(vocabs) == 1 and len(spec["_vocabularies"]) == 2
    v = vocabs[0]
    assert v.ancestors("emmo:SolidElectrolyte") == ["emmo:Ox", "emmo:Mat"]   # battery -> core
    assert v.nodes["emmo:SolidElectrolyte"]["vocabulary"] == "emmo-domain-battery"
    assert v.candidates("solid electrolyte")[0] == "emmo:SolidElectrolyte"
