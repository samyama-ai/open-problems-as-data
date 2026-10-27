# AI: V1 vs V3 on the ai-research-kg scope questions

- **V1:** `ai-research-kg` (catalog `samyama-ai/ai_research` @ `a02e87b`, KG `4742747`). Exported to `catalogs/ai/` (29,707 nodes, 62,842 edges).
- **V3:** `research-kit run` on the same catalog (2026-10-23). The catalog is carried in unchanged as the problem layer, under an evidence layer built from OpenAlex:
  - 40 seed researchers;
  - 4,630 of 4,932 catalog papers matched to OpenAlex works: 0 by DOI (1 catalog paper has a DOI), 3,026 by arXiv id, 1,604 by title + year;
  - 11,657 of 15,102 catalog people matched to 7,807 OpenAlex authors;
  - 7,877 works in the evidence layer.
- **Graph:** 120,972 nodes, 463,344 edges. Snapshot `runs/ai/ai.sgsnap` (16,826,558 bytes), uploaded to `s3://samyama-data/snapshots/research-kit-ai.sgsnap`.
- **Benchmark:** `research-kit bench` on both graphs.
  - `benchmarks/ai_v1.cypher`: the 35 queries of `benchmarks/queries.py` (AR01–AR33, AR90, AR91). Qn is the query id's number.
  - `{AUTHOR}` (AR23) is resolved by `TOP_AUTHOR`, the full-name author with the most papers. It returns Luke Zettlemoyer (31 papers) on both graphs, so the name is written into the file.
  - `runs/bench/ai-v1.json` (V1), `runs/bench/ai-v3.json` (V3, same queries)
  - `runs/bench/ai-v3-limited.json` (V3, `benchmarks/ai_v3_limited.cypher`), `runs/bench/ai-v1-limited.json` (the same file on V1, for the "before" column)
- Numbers: `benchmarks/results/ai-v1-vs-v3.json`.

## 1. The original 35 queries, unchanged

**34 of 35 queries return the same rows on V1 and V3; the 35th (AR14) differs only in which tied row its `LIMIT` keeps.** AR90 and AR91 return no rows on both, as required.

- 26 answers are identical row for row.
- 8 differ only in the order of rows that tie on the sort key (AR03, AR04, AR16, AR17, AR18, AR21, AR22, AR24).
- AR14 (papers cited by most problems) differs in one row. Three papers tie at 35 citing problems for the last 2 places under `LIMIT 10`; V1 and V3 pick a different pair. Without the limit both graphs return the same 11 papers.
- No label collision this time. The evidence layer uses `Work`, `Author`, `OpenAlexInstitution`, `OpenAlexSource` and `PaperQuestion`; every catalog label count in V3 equals V1.
- The relationship type `CITES` is shared: 12,615 Problem → Paper (catalog) and 50,445 Work → Work (evidence). The V1 queries always name both end labels, so they are not affected. A query with an unlabelled `CITES` pattern would count both.

## 2. Questions V1 answers in part, leaves unanswered, or lists as out of scope, rewritten for V3

- ai-research-kg grades no answer as "limited". The list below is mine, from `UNANSWERED` in `queries.py`, the notes in `docs/scope.md` and the README "Known limits" (no methods, people not resolved, no citation counts).
- Q numbers are scope.md numbers. Q42–Q48 are not numbered scope questions; they cover known limits.
- Same parameters as V1: problem X is `internals-based-safety-verification`, researcher X is Luke Zettlemoyer.
- Each query reaches the evidence layer through `SAME_AS` (catalog Paper → Work, catalog Person → Author) and `EVIDENCE_FOR` (Work → Problem). The verdicts are mine, read from the rows. No reference checker covers them.

| Q | Question (short) | V1 | V3 | Verdict |
|---|---|---|---|---|
| 9 | Status of problem X now | solved-but-impractical | Same status. 1 evidence work (Reluplex, 2017), no verdict. Solved-but-impractical problems are not status-checked. | **No change** |
| 12 | Methods tried on problem X | unanswered (no Method nodes) | 23 methods from 10 of X's 12 cited papers. Each method appears in 1 paper. | **Refused → answered** |
| 20 | Researchers linked to most problems | Zettlemoyer 169, Liang 144, Muennighoff 112, Mike Lewis 108 (full names only) | Zettlemoyer 179, Liang 157, Ré 119 (name variants merged). Mike Lewis is absent: his catalog node has no OpenAlex link. | **Mixed:** variants merge, unmatched people drop out |
| 23 | Researchers working on problem X | 3 labs, no researchers | No evidence work on X from 2022 on | **No change** |
| 24 | Zettlemoyer's top co-authors | Mike Lewis 10 shared catalog papers | Mike Lewis 32, Hajishirzi 26, Sewon Min 17 (OpenAlex co-authorship over the run's works) | **Better** |
| 25 | Methods used for the most problems | unanswered | literature review 125 problems, compute-optimal scaling analysis 111, supervised fine-tuning 88, LoRA 43 (methods used by ≥ 3 cited papers) | **Refused → partly answered.** "Used", not "state of the art". |
| 26 | Methods across most topics | unanswered | literature review 31 topics, compute-optimal scaling analysis 30, supervised fine-tuning 26 | **Refused → partly answered** |
| 27 | Problems mentioning method X (LoRA) | unanswered | 61 problems cite a paper that uses a LoRA method | **Refused → answered** |
| 28 | Methods claimed but not ablated | unanswered | not attempted: no ablation data | – |
| 39 | Understudied open problems (no lab, < 3 cited papers) | 0 | 0. No open problem without a lab cites fewer than 6 papers. | **Same** |
| 48 | Open problems with no lab (Q39 without the paper filter) | 54 | 54, of which 23 have no evidence work either | **Better** |
| 40 | Funding per problem (must return no data) | no data | Still no amounts. Funder names on 1,623 cited papers, reaching 951 problems (NSF on 775) | **Refused → partly answered** (names only) |
| 41 | Benchmark leaderboard (must return no data) | no data | no data; AR91 returns 0 rows on V3 | – (not attempted) |
| 42 | Citation counts (out of scope in V1) | none | OpenAlex `cited_by` on 4,630 matched papers (Adam 99,043) | **Refused → answered** |
| 43 | Catalog researchers with an ORCID | 0 | 7,320 (3,657 full names, 2,144 initials, 1,519 surnames) | **Better** |
| 44 | Name variants linked? | 3 nodes: Zettlemoyer / L. Zettlemoyer / Luke Zettlemoyer | All 3 resolve to one OpenAlex author. 2,732 authors link 6,582 catalog nodes. | **Better:** linked, not merged |
| 45 | Recent work on the problems | newest cited paper 2025; 0 from 2026 | 71 evidence works from 2026 (66 not catalog papers); 2024 on: 727 works, 147 not catalog papers | **Better:** work after the catalog |
| 47 | Has any problem been solved or refuted since? | refused | 3 "solves", 32 "refutes" on 26 problems; 2 suggested status changes. Catalog status unchanged. | **Refused → answered, pending a check.** LLM verdicts, not hand-checked. |

**Totals:**
- 18 rows; 16 attempted and graded (Q28 and Q41 not attempted): Better 5 (Q24, Q43, Q44, Q45, Q48), Refused → answered 4 (Q12, Q27, Q42, Q47), Refused → partly answered 3 (Q25, Q26, Q40), Mixed 1 (Q20), Same 1 (Q39), No change 2 (Q9, Q23).
- Not attempted: Q7/Q37 "has anyone tried this at scale" (no such data), Q28 (ablation), Q33 (needs an "enables" link), Q35 (needs community detection), Q41.
- Q47 is answered but unverified; it needs the same hand check as DBMS (#6, #8).

**Two data problems found while reading the rows:**
- **Wrong abstract from OpenAlex.** Work `W3001279689` ("Scaling Laws for Neural Language Models", arXiv 2001.08361) carries an abstract about "transport-validity theory for agentic AI interventions". The cached raw OpenAlex response has the same text, so the error is upstream (observed). Extraction gave this paper 6 unrelated methods, and 54 catalog problems cite it, so those 6 methods ranked 5th–10th in a first Q25 draft. Q25 and Q26 now require ≥ 3 papers per method. Heuristic scan: 266 of 7,040 works have an abstract that shares no content word with the title (author lists, placeholder text, wrong abstracts; derived, not checked one by one).
- **Unlinked seed researcher.** Catalog `Mike Lewis` (108 problems in V1) has no `SAME_AS`. OpenAlex splits him over several author ids (`A5004412943` on 7 of his catalog papers, `A5127780638` on 2), and `link_people` links only when exactly one candidate matches. So it is the designed precision rule, not a bug, but it drops a seed researcher from Q20. 3,445 of 15,102 catalog people are unlinked.

## 3. What else V3 adds

- **Evidence:** 592 of 1,000 catalog problems have papers linked by `EVIDENCE_FOR` (2,013 links, 1,969 works).
  - By status: open 229, empirically-open 161, partially-solved 130, methodologically-blocked 58, solved-but-impractical 14.
  - 187 problems have works that are not catalog papers at all (300 works). This is the definition behind the DBMS figure (336 problems, 770 works).
  - 360 problems have works they themselves do not cite (821 works).
- **Verdicts:** advances 1,062, unrelated 416, restates 235, refutes 32, solves 3. 265 links have no verdict.
- **Status check:** 578 problems checked (the 592 with evidence, less 14 solved-but-impractical); 2 status changes suggested.
- **Solves** (3):
  - `14-long-context/packed-sequence-cross-document-attention`: empirically-open → suggested partially-solved (Efficient Sequence Packing without Cross-contamination, 2021).
  - `23-privacy-memorization/hidden-state-privacy-accounting`: partially-solved, no change suggested (Privacy of Noisy SGD, 2022).
  - `24-multimodal/modality-gap-contrastive-embeddings`: partially-solved → suggested solved (It's Not a Modality Gap, 2024). The status note calls this a self-claim.
- **Refutes** (32 links, 26 problems): `01-tokenization/intrinsic-tokenizer-metrics`, `02-attention/attention-as-faithful-explanation`, `02-attention/icl-implicit-gradient-descent`, `03-training-dynamics/adam-vs-sgd-transformers`, `04-alignment/activation-steering-reliability` (3), `04-alignment/corrigibility-with-competent-agency`, `04-alignment/debate-truth-amplification`, `06-data-pipeline/influence-function-stability-at-scale`, `07-embeddings/cross-lingual-alignment-no-parallel-data`, `08-loss-and-heads/label-smoothing-distillation-interference`, `10-scaling-laws/chinchilla-coefficient-reproducibility`, `12-quantization-compression/calibration-set-sensitivity`, `12-quantization-compression/lottery-ticket-existence-at-initialization`, `12-quantization-compression/non-uniform-quantization-grid-optimality`, `12-quantization-compression/perplexity-sufficiency-compression-metric`, `20-interpretability/causal-faithfulness-metrics`, `22-safety-robustness/certified-robustness-beyond-smoothing-radii`, `22-safety-robustness/jailbreak-robustness-unbounded-prompt-space` (2), `22-safety-robustness/provable-unlearning-hazardous-capabilities`, `22-safety-robustness/robustness-accuracy-tradeoff-law-or-artifact`, `23-privacy-memorization/distillation-privacy-barrier`, `29-distillation/exposure-bias-sequence-distillation`, `30-synthetic-data/counterfactual-augmentation-spurious-removal`, `33-uncertainty-calibration/aleatoric-epistemic-identifiability` (2), `33-uncertainty-calibration/cold-posterior-effect` (3), `33-uncertainty-calibration/deep-ensembles-versus-bayesian-posteriors`. A "refutes" verdict means the paper contradicts a claim in the problem page; no status change follows from it.
- **Ideas:** 52 ideas from 13 subareas. All 52 target an offered open catalog problem (50 distinct): open 26, empirically-open 15, partially-solved 6, methodologically-blocked 5. 0 were rejected for naming a problem they were not offered.
- **Grounding to the catalog:** 1,311 of 6,885 per-paper problems (19.0%) map to a catalog problem: 145 as the same problem, 1,166 as narrower. They reach 592 catalog problems. (6,885 counts run problems after duplicates merge; the graph holds 7,144 `PaperProblem` nodes.)
- **Grounding to the ontology** (CSO + ACM CCS, 13,551 classes; `same` + `narrower` of total):

| Kind | Same | Narrower | Total | Placed |
|---|---:|---:|---:|---:|
| problems | 47 | 1,917 | 6,885 | 28.5% |
| methods | 255 | 3,352 | 14,198 | 25.4% |
| subjects | 651 | 1,742 | 7,564 | 31.6% |
| metrics | 156 | 514 | 5,198 | 12.9% |
| datasets_tools | 74 | 188 | 4,431 | 5.9% |
| applications | 489 | 1,313 | 4,665 | 38.6% |
| all | | | 42,941 | 24.9% (10,698) |

  9 answers were refused for naming a class not offered.

## 4. Cost

From `runs/ai/usage.json`:
- 3,698 LLM calls: 28,641,600 input and 9,643,523 output tokens; 417 web searches.
- 3,690 calls went through the Batch API; 8 were synchronous.
- By model: Sonnet 3,644 calls (21.6 M in, 9.1 M out); Opus 54 calls (7.0 M in, 0.54 M out).
- research-kit has no price table, so no dollar figure is computed here.
