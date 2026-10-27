# Open problems as data

A research field records its open problems in surveys and community reports. Those are prose,
written every few years, and nobody can ask them who works on a problem now or whether it was
settled last year.

This is the pipeline that makes them queryable: a hand-curated **problem layer** carried in
unchanged, under an **evidence layer** rebuilt from OpenAlex, joined by typed,
provenance-carrying links, with both layers in one graph database and reachable from one query
language. A language model does four jobs inside it — per-paper extraction, grounding to the
catalog, a per-paper status verdict, and idea generation — and each is constrained to a set the
system offers it, so an answer naming anything outside that set is refused rather than stored.

**This repository is a frozen artifact**, not a product. It is the code and the measurements
behind two papers, cut from an internal repository at one commit and left alone. See
*Provenance* at the end.

## The result you should look at first

The component the whole idea depends on — deciding whether a paper settles an open problem —
**fails its own audit**, and the audit is in `benchmarks/verdict-handcheck.md`.

Every `solves` and `refutes` verdict both runs produced was hand-checked against the papers.
Not a sample: all 41.

| | n | correct | partly | wrong |
|---|---:|---:|---:|---:|
| AI `solves` | 3 | 0 | 3 | 0 |
| AI `refutes` | 32 | 8 | 23 | 1 |
| DBMS `solves` | 4 | 1 | 3 | 0 |
| DBMS `refutes` | 2 | 0 | 1 | 1 |
| **All** | **41** | **9** | **30** | **2** |

- **No `refutes` verdict (0 of 34) disproves an open problem.**
- **Only 1 of 7 `solves` closes the question the problem statement calls central.**
- The dominant failure, 9 of 41, is one logic error: a paper showing that current methods fail,
  read as refuting an open "can it be done?" question.

Which is why a status change here is **proposed with its evidence and never applied**. That is
not caution; it is the finding.

A second result, and it is a requirement on the curator rather than the model: 5 of the 8
correct AI `refutes` are on the minority of problems whose statement *names the claim under
examination*. Writing the claim down is what makes it refutable.

## What is measured, and where

| File | What |
|---|---|
| `benchmarks/dbms-v1-vs-v3.md` | Database field: 48 scope questions, catalog-only graph vs rebuilt graph |
| `benchmarks/ai-v1-vs-v3.md` | AI field: the same comparison over 35 queries, plus ontology grounding |
| `benchmarks/verdict-handcheck.md` | All 41 `solves`/`refutes` verdicts, judged one by one |
| `benchmarks/results/*.json` | The machine-readable summaries every number resolves to |
| `benchmarks/*.cypher` | The benchmark queries themselves |

Headline figures: the rebuilt graph answers **47 of 47** answerable database questions identically
and **34 of 35** AI queries, so nothing the catalog-only graph answered broke; and **336 database
problems have 770 papers bearing on them that the catalog's curators never cited**.

## Run it

```bash
uv sync
export OPENALEX_MAILTO=you@example.com          # OpenAlex asks for a contact address
export ENV_FILE=.env                            # ANTHROPIC_API_KEY, OPENALEX_API_KEY

python scripts/catalog_from_dbms_kg.py ...      # build the catalog export (see below)
./scripts/run-dbms.sh                           # full build: graph, snapshot, report
uv run research-kit serve runs/dbms/dbms.sgsnap --graph-version 1.11.0 --port 18088
```

Every stage caches in the run directory, so a re-run pays only for what did not finish; delete
one file to redo one stage. The model stages go through a batch API at half price where they can
— on the AI run, 3,690 of 3,698 calls did.

### What you need

| | |
|---|---|
| `ANTHROPIC_API_KEY` | for `--backend api` |
| `OPENALEX_API_KEY` | free. Without it you share a per-IP budget of $0.10/day, which a 40-researcher run spends in minutes. The run then stops with `BudgetExhausted` rather than returning partial data. |
| Docker | the loader starts `ghcr.io/samyama-ai/samyama-graph:<version>`, which pulls anonymously. Or pass `--url` to an engine you already run. |

`SNAPSHOT_S3_PREFIX` is optional and unset: the `.sgsnap` is written under `runs/`.

### The two catalogs

Both are public, and the exact commits the papers used are recorded in
`benchmarks/results/*.json`:

| Field | Catalog | Catalog-only graph (V1) |
|---|---|---|
| Databases | [`samyama-ai/dbms_research`](https://github.com/samyama-ai/dbms_research) @ `5fff7f7` | [`samyama-ai/dbms-research-kg`](https://github.com/samyama-ai/dbms-research-kg) @ `78c1486` |
| AI | [`samyama-ai/ai_research`](https://github.com/samyama-ai/ai_research) @ `a02e87b` | [`samyama-ai/ai-research-kg`](https://github.com/samyama-ai/ai-research-kg) @ `4742747` |

`scripts/catalog_from_dbms_kg.py` and `scripts/catalog_from_ai_kg.py` turn a checkout of those
into the `catalogs/` export this pipeline reads. The export is ~80 MB and is not committed.

### Vocabularies

`vocab/` is the vocabulary catalogue, and it ships with this repository so the grounding stage
runs standalone — `vocab/catalog/export/cs.json` names what grounds the `cs` domain, and
`--ground-domain cs` reads it.

It holds the two vocabularies the papers' ontology-grounding table used, CSO 3.5 and ACM CCS 2012.
**No vocabulary data is redistributed**: `vocab/resources.yaml` carries each publisher's own URL
with a sha256, and `vocab/fetch_vocab.py` downloads and verifies against it.

```bash
python vocab/fetch_vocab.py --list
python vocab/fetch_vocab.py acm-ccs
uv run --with rdflib python -I vocab/vocab_to_graph.py vocab/data/acm-ccs-2012 \
    --id acm-ccs --base https://dl.acm.org/ccs2012/ --out vocab/build/acm-ccs
```

Read `DATA-LICENSES.md` before reusing ACM CCS — its licence is unstated.

## How it works

Nine stages. Five are deterministic (bibliographic harvest, bridge, graph build, snapshot export,
benchmark); four use a model, each constrained to an offered set.

| Stage | Offered set |
|---|---|
| extract per paper | free text, canonicalised afterwards |
| canonicalise | only the names already extracted |
| ground + status | only the catalog's own problems |
| generate ideas | only the open problems offered |

Across both runs, 104 ideas were generated and 0 were rejected for naming a problem they were not
offered — which says the constraint is satisfiable, not that it is unnecessary.

**No node label is shared between the two layers.** The catalog keeps `Paper`, `Person`,
`Institution`, `Venue`; the evidence layer uses `Work`, `Author`, `OpenAlexInstitution`,
`OpenAlexSource`. A shared label is a build-time error, because the first build did share them,
nothing errored, and a query counting "papers the catalog cites" returned 8,769 where the catalog
has 2,679.

Every node carries a `source`: `openalex` for a bibliographic fact, `extraction` for something a
model read out of an abstract, `web` for something it found by searching, `synthesis` for
something it wrote. Without that field you cannot tell a citation from a guess.

## What is not here, and why

- **`runs/`** — per-call model logs and cached OpenAlex responses. Large, and they hold
  third-party abstracts. The published numbers all resolve to `benchmarks/results/*.json`; the
  raw logs do not come with them, and the papers say so in their limitations.
- **`catalogs/`** — ~80 MB, regenerated from the public repos above.
- **Vocabulary files** — fetched from their publishers, never vendored.
- **Anything operational** — this is a cut of a working repository, with the parts that were
  about running a business rather than running the pipeline left behind.

Two S3 URLs survive in `benchmarks/dbms-v1-vs-v3.md` and `benchmarks/ai-v1-vs-v3.md`. They record
where each snapshot was written on the day of the run. They are left verbatim because those files
are a record of a measurement, and editing a record to tidy it is a worse habit than naming a
bucket nobody can read.

## Limitations

- Facts come from titles, abstracts and metadata, **not full text**.
- Model-written nodes (`source=synthesis|web`) are not verified claims.
- The verdict audit had **one LLM-assisted reviewer**, not independent domain experts, and no
  ground truth exists for "which problems changed status", so it measures precision and cannot
  measure recall.
- Two fields, both curated by the same group.
- The improvement grades in the benchmark write-ups are ours, read from the returned rows. No
  automatic checker covers them.

## Papers

- *Open Problems as Data: Toward Living, Queryable Knowledge Graphs of a Research Field* —
  ICDE 2027, Data Engineering Future Technologies track (vision).
- *Rebuilding a Field's Open-Problem Catalog from the Literature: A Two-Layer Knowledge Graph,
  and Why Status Must Stay Proposed* — the full version, with the study and the audit.

`CITATION.cff` carries the citation metadata.

## Provenance

Cut from an internal repository at commit `92d2f02` on 2026-10-27, as a fresh repository with one
initial commit rather than a fork — the internal history contains unrelated material and is not
published. The internal repository keeps developing; **this one does not**, so it cannot carry
fixes for defects these papers report. That is the point of a frozen artifact: it is what produced
the numbers.

Code is Apache-2.0, measurements are CC BY 4.0. See `DATA-LICENSES.md`.
