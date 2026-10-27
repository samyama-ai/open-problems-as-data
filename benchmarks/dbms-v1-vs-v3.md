# DBMS: V1 vs V3 on the 48 scope questions

- **V1:** `dbms-research-kg` (catalog `samyama-ai/dbms_research` @ `5fff7f7`, KG `78c1486`).
- **V3:** `research-kit run` on the same catalog (`scripts/run-dbms.sh`, 2026-10-20). The catalog is carried in unchanged as the problem layer, under an evidence layer built from OpenAlex:
  - 40 seed researchers;
  - 2,278 of 2,679 catalog papers matched to OpenAlex;
  - 3,087 of 4,454 catalog people matched to OpenAlex authors.
- **Graph:** 78,475 nodes, 313,878 edges. Snapshot `s3://samyama-data/snapshots/research-kit-dbms.sgsnap` (16.9 MB).
- **Benchmark:** `research-kit bench` on both graphs.
  - `runs/bench/dbms-v1.json` (V1)
  - `runs/bench/dbms-v3.json` (V3, original queries)
  - `runs/bench/dbms-v3-limited.json` (V3, `benchmarks/dbms_v3_limited.cypher`)

## 1. The original 48 queries, unchanged

**47 of 47 answerable questions return identical answers on V1 and V3.** Q39 needs vector search and has no Cypher.

- The first V3 build differed on 4 questions. The evidence layer reused the catalog labels `Paper`, `Person`, `Institution` and `Venue`, so:
  - Q19 counted 8,769 "cited papers" instead of 2,679;
  - Q28 showed a duplicate Thomas Neumann and a Person node named with a five-author list.
- That was a bug in V3. The evidence layer now uses `Work`, `Author`, `OpenAlexInstitution` and `OpenAlexSource`. A label shared by both layers without a rename now stops the build.
- After the fix, V3 does not regress on any V1 answer. The original queries only read the catalog layer, so they cannot show what V3 adds.

## 2. The questions V1 answered "limited" or "refused", rewritten for V3

The same question with the same parameters. Each query reaches the evidence layer through `SAME_AS` (catalog Paper → Work, catalog Person → Author) and `EVIDENCE_FOR` (Work → Problem). The verdicts are mine, read from the answers. No reference checker covers them.

| Q | Question (short) | V1 | V3 | Verdict |
|---|---|---|---|---|
| 12 | Who works on problem X (acyclic join dependencies) now? | 11 names, no dates | No evidence work after 1983 for this problem | **No change.** The question's X has no recent evidence. 336 other problems gained new works. |
| 19 | Papers after 2015 | 787 catalog papers after 2015 | 873 evidence works after 2015, 480 of them new to the catalog | **Better:** recent work the catalog does not cite |
| 21 | DOI / arXiv / DBLP-only | DOI 1,800 of 2,679 | 2,278 of 2,679 matched to OpenAlex; 386 have neither a DOI nor a match | **Better** |
| 22 | References no bibliographic source verifies | 15 | The same 15. OpenAlex does not find them either. | **Same answer, now corroborated** |
| 26 | Researchers with an ORCID | 0 rows | 2,181 catalog researchers, via their OpenAlex author | **Better** (limited → answered) |
| 28 | Name variants merged? | 3 separate nodes (Neumann / T. Neumann / Thomas Neumann) | All three resolve to one OpenAlex author | **Better:** the variants are linked, not merged |
| 42 | Open problems nobody works on | 72 | 38 with no named researcher and no evidence work | **Better** |
| 45 | Open problems citing nothing after 2015 | 86 | 70 counting evidence works | **Better** |
| 46 | Total citations of paper X | refused | OpenAlex `cited_by` on 2,278 matched papers | **Refused → answered** |
| 47 | Has problem X been solved since 2026-09? | refused | 4 "solves" verdicts. 2 suggested status changes (order-dependency implication → solved; query determinacy → partially solved). The catalog status is unchanged. | **Refused → answered, pending a check.** The verdicts are an LLM's and need the 30-item hand check (#6, #8). |
| 48 | Who funds work on problem X? | refused | 3 funders for X; 567 catalog papers carry funders | **Refused → partly answered.** OpenAlex funder data is sparse. |

**Totals:**
- Of V1's 20 limited and 3 refused questions, 11 were attempted. 8 got better answers, 1 had the same answer corroborated, 1 had no change. Q47 is answered but unverified.
- The other 12 limited questions concern content inside the catalog (bounds, concepts, surveys, SOTA systems), which the evidence layer does not add to. Q39 needs vector search.

## 3. What else V3 adds

- **Evidence:** 579 of 1,053 catalog problems have papers linked by `EVIDENCE_FOR`. 336 of them have papers from outside the catalog (770 works).
- **Verdicts:** advances 893, restates 403, unrelated 351, solves 4, refutes 2. Another 190 links have no verdict, because the status check reads 8 papers per problem.
- **Ideas:** all 52 target an offered open catalog problem (16 open, 16 partially-solved, 20 empirically-open). 0 were rejected for naming a problem they were not offered.
- **Grounding:** 1,265 of 5,058 per-paper problems (25%) map to a catalog problem: 138 as the same problem, 1,127 as narrower.

## 4. Cost

- 2,808 LLM calls: 23.6 M input and 6.5 M output tokens; 431 web searches.
- 2,799 calls went through the Batch API.
- research-kit has no price table, so no dollar figure is computed here.
