"""Turn a downloaded RDF vocabulary into nodes.jsonl / edges.jsonl.

    python scripts/vocab_to_graph.py <rdf-dir-or-file> --id emmo --out build/emmo
    python scripts/vocab_to_graph.py <dir> --id emmo-domain-battery --prefix emmo --out build/emmo-domain-battery

--prefix sets the node-id namespace (default: --id). Give vocabularies that share an
IRI family the same prefix -- EMMO's domain ontologies subclass EMMO core classes, so
with --prefix emmo their parent edges point at ids the core build also uses, and a
consumer that loads both gets one connected hierarchy. A BROADER edge to a parent this
build does not declare is kept and marked "external": true, rather than dropped.

Emits the same shape this repository's graph builder reads, so the existing
loader ingests it without a second format:

    nodes.jsonl  {"id", "label": "Concept", "name", ..., "source": "<id>"}
    edges.jsonl  {"src", "rel": "BROADER", "dst"}

Names come from skos:prefLabel, then rdfs:label, then the IRI fragment — EMMO uses
opaque IRIs and carries the human name in prefLabel, so a fragment-only reading
would produce an unusable graph. Hierarchy comes from rdfs:subClassOf and
skos:broader; anonymous (blank-node) parents are skipped, which is what restriction
axioms resolve to.

Two vocabularies need more than that:

- CSO (Computer Science Ontology) has its own schema: concepts are cso:Topic,
  hierarchy is cso:superTopicOf (parent -> child, the inverse of BROADER), and
  cso:preferentialEquivalent names the preferred topic of a synonym cluster. Each
  cluster becomes one node under the preferred topic; the others become its aliases
  and their edges move to it. cso:contributesTo and cso:relatedEquivalent are not
  hierarchy and are not emitted.
- ACM CCS 2012's SKOS file writes `lang="en"` where RDF/XML requires `xml:lang`, which
  rdflib reads as a property attribute and turns every prefLabel into a blank node. The
  attribute is repaired in memory before parsing; the file on disk is not touched.

The input is downloaded data: pass it as an argument and never run this from inside
the download directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

try:
    from rdflib import OWL, RDF, RDFS, SKOS, Graph, Namespace, URIRef
    from rdflib.namespace import DCTERMS
except ImportError:
    sys.exit("rdflib is needed: uv run --with rdflib python scripts/vocab_to_graph.py ...")

SUFFIXES = {".ttl", ".owl", ".rdf", ".nt", ".n3", ".jsonld", ".xml"}
CSO = Namespace("http://cso.kmi.open.ac.uk/schema/cso#")
ELUCIDATION = URIRef("https://w3id.org/emmo#EMMO_967080e5_2f42_4eb2_a3a9_c58143e835f9")


def parse_all(target: Path, base: str | None = None) -> Graph:
    files = sorted(p for p in ([target] if target.is_file() else target.rglob("*"))
                   if p.suffix.lower() in SUFFIXES)
    if not files:
        sys.exit(f"no RDF files under {target}")
    g = Graph()
    ok = 0
    for f in files:
        try:
            if f.suffix.lower() in (".xml", ".rdf"):
                src = f.read_text(encoding="utf-8")
                if ' lang="' in src:
                    src = src.replace(' lang="', ' xml:lang="').replace(' xml:xml:lang="', ' xml:lang="')
                g.parse(data=src, format="xml", publicID=base or f.resolve().as_uri())
            else:
                g.parse(f.as_posix(), publicID=base)
            ok += 1
        except Exception as e:                                  # noqa: BLE001
            print(f"  skipped {f.name}: {type(e).__name__}: {e}", file=sys.stderr)
    print(f"parsed {ok}/{len(files)} files, {len(g)} triples", file=sys.stderr)
    return g


def text(g: Graph, s, *preds) -> str | None:
    for p in preds:
        for o in g.objects(s, p):
            if str(o).strip():
                return str(o).strip()
    return None


def _segments(u) -> list[str]:
    return [x for x in str(u).replace("#", "/").split("/") if x]


def local_ids(iris, strip: list[str] | None = None) -> Callable[[object], str]:
    """Id suffix per IRI: the fragment, or more trailing path segments where fragments collide.

    NORIA-O's code lists reuse fragments across schemes (`.../PerceivedSeverity/minor`,
    `.../TroubleTicket/severity/minor`). Keying on the fragment alone kept the first and
    dropped the rest without a word, so a collision is resolved by taking the fewest trailing
    segments that make every colliding IRI unique. IRIs that do not collide keep the bare
    fragment, so existing builds keep their ids.

    `strip` gives namespaces whose IRIs take the whole path after the namespace instead, so a
    code list keeps one id shape (`Notification/Severity/PerceivedSeverity/minor` for every
    value, not a mix of one, two and three segments depending on what else collides).
    """
    out: dict[str, str] = {}
    rest = []
    for u in iris:
        base = max((b for b in strip or [] if str(u).startswith(b)), key=len, default=None)
        if base:
            out[str(u)] = str(u)[len(base):].replace("#", "/").strip("/")
        else:
            rest.append(u)
    dup = {v for v in out.values() if list(out.values()).count(v) > 1}
    if dup:
        sys.exit(f"--strip leaves {len(dup)} ids shared by different IRIs, e.g. {sorted(dup)[:3]}")
    by_frag: dict[str, list] = {}
    for u in rest:
        by_frag.setdefault(_segments(u)[-1], []).append(u)
    for f, us in by_frag.items():
        if len(us) == 1:
            out[str(us[0])] = f
            continue
        k = 2
        while k < max(len(_segments(u)) for u in us):
            keys = {"/".join(_segments(u)[-k:]) for u in us}
            if len(keys) == len(us):
                break
            k += 1
        for u in us:
            out[str(u)] = "/".join(_segments(u)[-k:])

    def frag(u) -> str:
        return out.get(str(u)) or _segments(u)[-1]
    return frag


def build(g: Graph, vocab_id: str, prefix: str | None = None,
          properties: bool = False, strip: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    prefix = prefix or vocab_id

    subjects = (set(g.subjects(RDF.type, OWL.Class)) | set(g.subjects(RDF.type, SKOS.Concept))
                | set(g.subjects(RDF.type, CSO.Topic)))
    props = set()
    if properties:
        props = {s for t in (OWL.ObjectProperty, OWL.DatatypeProperty)
                 for s in g.subjects(RDF.type, t) if isinstance(s, URIRef)}
    frag = local_ids([s for s in subjects | props if isinstance(s, URIRef)], strip)
    # CSO synonym clusters: every member points at the preferred topic (itself included).
    canon = {s: o for s, o in g.subject_objects(CSO.preferentialEquivalent)
             if isinstance(s, URIRef) and isinstance(o, URIRef)}
    merged: dict = {}
    for s, o in canon.items():
        if s != o and (name := text(g, s, RDFS.label)):
            merged.setdefault(o, set()).add(name)
    nodes, seen = [], set()
    for s in subjects:
        if not isinstance(s, URIRef) or canon.get(s, s) != s:
            continue                                            # blank node, or a non-preferred synonym
        name = text(g, s, SKOS.prefLabel, RDFS.label) or str(s).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        n = {"id": f"{prefix}:{frag(s)}",
             "label": "Concept", "name": name, "iri": str(s), "vocabulary": vocab_id,
             "source": vocab_id}
        if (d := text(g, s, ELUCIDATION, SKOS.definition, DCTERMS.description, RDFS.comment)):
            n["description"] = d[:2000]
        alts = sorted(({str(o).strip() for o in g.objects(s, SKOS.altLabel) if str(o).strip()}
                       | merged.get(s, set())) - {name})
        if alts:
            n["aliases"] = alts
        schemes = sorted(_segments(o)[-1] for o in g.objects(s, SKOS.inScheme))
        if schemes:
            n["scheme"] = schemes[0] if len(schemes) == 1 else schemes
            n["scheme_iri"] = str(next(iter(sorted(g.objects(s, SKOS.inScheme)))))
        if n["id"] in seen:
            continue
        seen.add(n["id"])
        nodes.append(n)

    skip = {str(OWL.Thing), str(RDFS.Resource)}
    edges, pairs = [], set()
    child_parent = [*g.subject_objects(RDFS.subClassOf), *g.subject_objects(SKOS.broader),
                    *((c, p) for p, c in g.subject_objects(CSO.superTopicOf))]
    for s, o in child_parent:
        if not isinstance(s, URIRef) or not isinstance(o, URIRef) or str(o) in skip:
            continue                                        # blank node: an axiom, not a parent
        s, o = canon.get(s, s), canon.get(o, o)
        a, b = f"{prefix}:{frag(s)}", f"{prefix}:{frag(o)}"
        if a not in seen or a == b or (a, b) in pairs:
            continue
        pairs.add((a, b))
        e = {"src": a, "rel": "BROADER", "dst": b}
        if b not in seen:
            e["external"] = True                        # declared in another vocabulary
        edges.append(e)
    for p in sorted(props, key=str):
        pid = f"{prefix}:{frag(p)}"
        if pid in seen:
            continue
        seen.add(pid)
        kind = "object" if (p, RDF.type, OWL.ObjectProperty) in g else "datatype"
        n = {"id": pid, "label": "Property", "name": text(g, p, SKOS.prefLabel, RDFS.label) or frag(p),
             "iri": str(p), "kind": kind, "vocabulary": vocab_id, "source": vocab_id}
        if (d := text(g, p, SKOS.definition, DCTERMS.description, RDFS.comment)):
            n["description"] = d[:2000]
        nodes.append(n)
        for rel, pred in (("DOMAIN", RDFS.domain), ("RANGE", RDFS.range)):
            for o in g.objects(p, pred):
                if not isinstance(o, URIRef):
                    continue                                # a union or restriction: not a single class
                dst = f"{prefix}:{frag(o)}"
                e = {"src": pid, "rel": rel, "dst": dst}
                if dst not in seen and not str(o).startswith(str(p).rsplit("/", 1)[0]):
                    e["external"] = True                    # an XSD datatype or a class from elsewhere
                    e["iri"] = str(o)
                edges.append(e)
    return nodes, edges


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", type=Path, help="RDF file, or a directory to walk")
    ap.add_argument("--id", required=True, help="vocabulary id, used as the node id prefix")
    ap.add_argument("--prefix", help="node-id namespace; default --id")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--base", help="base IRI for relative identifiers (ACM CCS uses bare ids); "
                                   "default: the file's own path, which no consumer can resolve")
    ap.add_argument("--properties", action="store_true",
                    help="also emit owl:ObjectProperty/DatatypeProperty as Property nodes with "
                         "DOMAIN and RANGE edges (a KG schema needs them; a topic hierarchy does not)")
    ap.add_argument("--strip", action="append", default=[],
                    help="namespace IRI whose members take their full path after it as id "
                         "(repeatable; e.g. NORIA-O's ontology/ and kos/ namespaces)")
    a = ap.parse_args()

    nodes, edges = build(parse_all(a.target, a.base), a.id, a.prefix, a.properties, a.strip)
    a.out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("nodes.jsonl", nodes), ("edges.jsonl", edges)):
        with (a.out / name).open("w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    named = sum(1 for n in nodes if not n["name"].startswith("EMMO_"))
    ext = sum(1 for e in edges if e.get("external"))
    nprop = sum(1 for n in nodes if n["label"] == "Property")
    nb = sum(1 for e in edges if e["rel"] == "BROADER")
    print(f"{a.id}: {len(nodes) - nprop} concepts ({named - nprop} with a human name), {nprop} properties, "
          f"{nb} BROADER edges, {len(edges) - nb} DOMAIN/RANGE edges ({ext} edges to things declared "
          f"elsewhere) -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
