// V3 versions of the AI scope questions that V1 (ai-research-kg) answers only in part, leaves
// unanswered (UNANSWERED in benchmarks/queries.py), or lists as out of scope. Qn is the
// docs/scope.md question number; Q42-Q48 are not numbered scope questions but V1 known limits
// (README "Known limits", scope.md "Out of scope"). Same parameters as ai_v1.cypher: problem X is
// internals-based-safety-verification, researcher X is Luke Zettlemoyer (TOP_AUTHOR).
// Each query reaches V3's evidence layer through SAME_AS (catalog Paper -> Work, catalog Person ->
// Author) and EVIDENCE_FOR (Work -> Problem). Run with
//   research-kit bench benchmarks/ai_v3_limited.cypher --url <V3 server> --out runs/bench/ai-v3-limited.json
// and against V1 (--load-dir catalogs/ai) for the "before" column: on V1 the evidence labels do
// not exist, so these queries return no rows or zero counts there.

// Q9 · What is problem X's status now? (catalog status, evidence works and verdicts, suggested status)
MATCH (p:Problem {slug: "internals-based-safety-verification"}) OPTIONAL MATCH (p)<-[e:EVIDENCE_FOR]-(w:Work) RETURN p.status AS catalog_status, p.status_suggested AS suggested, p.status_checked AS checked, count(w) AS evidence_works, collect(e.verdict) AS verdicts

// Q12 · What methods have been tried on problem X? (methods extracted from the matched cited papers)
MATCH (p:Problem {slug: "internals-based-safety-verification"})-[:CITES]->(:Paper)-[:SAME_AS]->(w:Work)-[:USES_METHOD]->(m:Method) RETURN m.name AS method, count(DISTINCT w.id) AS papers ORDER BY papers DESC, method

// Q20 · Which researchers are linked to the most problems? (catalog authors resolved to OpenAlex authors, so name variants count once)
MATCH (p:Problem)-[:CITES]->(:Paper)-[:AUTHORED_BY]->(:Person)-[:SAME_AS]->(o:Author) RETURN o.name AS author, count(DISTINCT p.id) AS problems ORDER BY problems DESC, author LIMIT 10

// Q23 · Which researchers are working on problem X now? (authors of evidence works from 2022 on)
MATCH (p:Problem {slug: "internals-based-safety-verification"})<-[:EVIDENCE_FOR]-(w:Work)<-[:AUTHORED]-(a:Author) WHERE w.year >= 2022 RETURN a.name AS researcher, w.year AS year, w.title AS paper ORDER BY researcher

// Q24 · Who does researcher X co-author with most? (OpenAlex co-authorship, all works in the run)
MATCH (a:Author {name: "Luke Zettlemoyer"})-[c:COAUTHOR]-(b:Author) RETURN b.name AS collaborator, c.papers AS papers ORDER BY papers DESC, collaborator LIMIT 10

// Q25 · Which methods are used for the most problems? (methods of the matched cited papers, used by at least 3 of them; "used", not "state of the art")
MATCH (p:Problem)-[:CITES]->(:Paper)-[:SAME_AS]->(w:Work)-[:USES_METHOD]->(m:Method) WITH m, count(DISTINCT p.id) AS problems, count(DISTINCT w.id) AS papers WHERE papers >= 3 RETURN m.name AS method, problems, papers ORDER BY problems DESC, method LIMIT 10

// Q26 · Which methods appear across the most topics? (used by at least 3 matched cited papers)
MATCH (t:Topic)<-[:IN_TOPIC]-(p:Problem)-[:CITES]->(:Paper)-[:SAME_AS]->(w:Work)-[:USES_METHOD]->(m:Method) WITH m, count(DISTINCT t.id) AS topics, count(DISTINCT w.id) AS papers WHERE papers >= 3 RETURN m.name AS method, topics, papers ORDER BY topics DESC, method LIMIT 10

// Q27 · Which problems mention method X (LoRA)? (a cited paper or evidence work uses a method whose name contains "LoRA")
MATCH (m:Method)<-[:USES_METHOD]-(w:Work) WHERE m.name CONTAINS "LoRA" MATCH (p:Problem)-[:CITES]->(:Paper)-[:SAME_AS]->(w) RETURN p.title AS problem, count(DISTINCT w.id) AS papers ORDER BY papers DESC, problem

// Q39 · Which open problems are understudied: no lab active, fewer than 3 cited papers, and (V3) no evidence work?
MATCH (p:Problem {status: "open"}) WHERE NOT (p)<-[:ACTIVE_ON]-(:Institution) OPTIONAL MATCH (p)-[:CITES]->(x:Paper) WITH p, count(x) AS cited WHERE cited < 3 OPTIONAL MATCH (p)<-[:EVIDENCE_FOR]-(w:Work) WITH p, count(w) AS ev RETURN count(p) AS understudied_catalog_only, sum(CASE WHEN ev = 0 THEN 1 ELSE 0 END) AS understudied_with_evidence

// Q48 · Which open problems have no lab active, and how many of those have no evidence work either? (Q39 without the paper-count filter, which no open problem meets)
MATCH (p:Problem {status: "open"}) WHERE NOT (p)<-[:ACTIVE_ON]-(:Institution) OPTIONAL MATCH (p)<-[:EVIDENCE_FOR]-(w:Work) WITH p, count(w) AS ev RETURN count(p) AS no_lab, sum(CASE WHEN ev = 0 THEN 1 ELSE 0 END) AS no_lab_no_evidence

// Q40 · How much funding has each problem received? (OpenAlex funders of the cited papers; names only, no amounts)
MATCH (p:Problem)-[:CITES]->(x:Paper) WHERE x.oa_funders IS NOT NULL UNWIND x.oa_funders AS funder RETURN funder, count(DISTINCT p.id) AS problems ORDER BY problems DESC, funder LIMIT 10

// Q42 · How many citations do the catalog's papers have? (OpenAlex cited_by on matched catalog papers; out of scope in V1)
MATCH (x:Paper) WHERE x.oa_cited_by IS NOT NULL RETURN x.title AS paper, x.year AS year, x.oa_cited_by AS citations ORDER BY citations DESC LIMIT 5

// Q43 · Which catalog researchers have an ORCID? (through their OpenAlex author)
MATCH (a:Person)-[:SAME_AS]->(o:Author) WHERE o.orcid IS NOT NULL RETURN a.name_form AS written_as, count(DISTINCT a.id) AS people ORDER BY people DESC

// Q44 · Are name variants of the same person linked? (catalog Person nodes that resolve to one OpenAlex author)
MATCH (a:Person)-[:SAME_AS]->(o:Author) WHERE a.name ENDS WITH "Zettlemoyer" RETURN o.name AS author, collect(a.name) AS written_as ORDER BY author

// Q45 · In which years did the evidence works on the catalog's problems appear? (most recent 8 years)
MATCH (p:Problem)<-[:EVIDENCE_FOR]-(w:Work) WHERE w.year IS NOT NULL WITH DISTINCT w RETURN w.year AS year, count(w) AS evidence_works ORDER BY year DESC LIMIT 8

// Q46 · How many catalog-cited papers appeared in each recent year? (the V1 baseline for Q45)
MATCH (p:Problem)-[:CITES]->(x:Paper) WHERE x.year >= 2019 WITH DISTINCT x RETURN x.year AS year, count(x) AS catalog_papers ORDER BY year DESC

// Q47 · Has any problem been solved or refuted since the catalog was written? (evidence verdicts; the catalog status is left unchanged)
MATCH (p:Problem)<-[e:EVIDENCE_FOR]-(w:Work) WHERE e.verdict IN ["solves", "refutes"] RETURN e.verdict AS verdict, p.id AS problem, p.status AS catalog_status, p.status_suggested AS suggested, w.title AS paper, w.year AS year ORDER BY verdict DESC, problem, year
