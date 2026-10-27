# What is licensed how

Two licences apply in this repository, and one third-party question is open.

| Path | Content | Licence |
|---|---|---|
| `src/`, `tests/`, `scripts/`, `vocab/*.py`, `queries/` | code | Apache-2.0 (`LICENSE`) |
| `benchmarks/**` | measurements and write-ups produced by this work | CC BY 4.0 |

## `benchmarks/` in detail

`benchmarks/results/*.json` and the three `.md` write-ups are the evidence behind every number
in the papers. They are our measurements over third-party bibliographic records, not copies of
those records.

- **Bibliographic facts** (work ids, titles, years, DOIs, citation counts, author ids) come from
  OpenAlex, which publishes under CC0.
- **The 41 `llm_quote` fields** in `verdict-handcheck.json` are *model-written one-line summaries
  of what a paper does*, not quotations from its abstract. Median 114 characters, longest 204.
  No third-party text is reproduced here.
- **No abstracts, full texts or PDFs** are included. The pipeline reads abstracts at run time
  from OpenAlex and caches them under `runs/`, which is not published.

## The vocabularies are fetched, never redistributed

`vocab/resources.yaml` carries only acquisition blocks — the publisher's own URL, the file name,
the version, the byte count and a sha256. `vocab/fetch_vocab.py` downloads from the publisher and
verifies the hash. `vocab/data/` is gitignored.

| Vocabulary | Publisher | Licence as recorded |
|---|---|---|
| Computer Science Ontology 3.5 | Open University (KMi) | CC BY 4.0. The download needs a signed-in CSO portal account, so it is a manual step. |
| ACM CCS 2012 | ACM | **Unstated (ACM copyright).** |

On ACM CCS, the note from our internal catalogue is reproduced unchanged: *"No licence is stated
in the file or on dl.acm.org/ccs, whose page answers 403 to non-browser clients; the file itself
downloads directly. Treat as internal use until the terms are confirmed with ACM."* Shipping a
fetcher that points at ACM's own public URL is not redistribution, but anyone reusing that
vocabulary should settle the terms themselves first.

## The engine

`samyama-graph` is a separate project under Apache-2.0. This repository starts it from the public
container image `ghcr.io/samyama-ai/samyama-graph` and does not vendor it.

## The vendored LLM backend

`src/research_kit/llm_backend/` is vendored from an internal sibling package so this repository
installs standalone. Same authors, same Apache-2.0 licence. It is not a third-party dependency.
