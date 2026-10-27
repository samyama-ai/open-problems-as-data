// V3 versions of the DBMS scope questions that V1 answered "limited" or "refused"
// (dbms-research-kg benchmarks/scope_questions.md). Same question, same parameters where the
// question has one; the query reaches V3's evidence layer through SAME_AS (catalog Paper ->
// Work, catalog Person -> Author) and EVIDENCE_FOR (Work -> Problem). Run with
//   research-kit bench benchmarks/dbms_v3_limited.cypher --url <V3 server> --out runs/bench/dbms-v3-limited.json
// and against V1 for the "before" column.

// Q12 · Which researchers are named as working on problem X right now? (authors of evidence published 2022 or later)
MATCH (p:Problem {id: "01-relational-theory/acyclic-join-dependencies"})<-[:EVIDENCE_FOR]-(w:Work)<-[:AUTHORED]-(a:Author) WHERE w.year >= 2022 RETURN a.name AS researcher, count(DISTINCT w) AS recent_papers ORDER BY recent_papers DESC, researcher LIMIT 15

// Q19 · How many papers on the catalog's problems appeared after 2015? (catalog citations plus evidence works)
MATCH (p:Problem)<-[:EVIDENCE_FOR]-(w:Work) WHERE w.year IS NOT NULL WITH DISTINCT w RETURN (w.year / 10) * 10 AS decade, count(w) AS evidence_papers, sum(CASE WHEN w.year > 2015 THEN 1 ELSE 0 END) AS after_2015 ORDER BY decade

// Q21 · Which catalog papers have a DOI, an arXiv id, or only a DBLP record, and how many matched OpenAlex?
MATCH (x:Paper) RETURN sum(CASE WHEN x.doi <> "" THEN 1 ELSE 0 END) AS doi, sum(CASE WHEN x.oa_id IS NOT NULL THEN 1 ELSE 0 END) AS in_openalex, sum(CASE WHEN x.oa_id IS NULL AND x.doi = "" THEN 1 ELSE 0 END) AS neither, count(x) AS papers

// Q22 · Which references could not be verified against any bibliographic source? (unverified in the catalog and not found in OpenAlex)
MATCH (p:Problem)-[c:CITES {verification_status: "unverified"}]->(x:Paper) WHERE x.oa_id IS NULL RETURN p.title AS problem, x.title AS paper ORDER BY problem

// Q26 · Which researchers have a DBLP or ORCID profile?
MATCH (a:Person)-[:SAME_AS]->(o:Author) WHERE o.orcid IS NOT NULL RETURN a.name AS researcher, o.orcid AS orcid ORDER BY researcher LIMIT 10

// Q28 · Are name variants of the same person merged into one node? (variants that resolve to one OpenAlex author)
MATCH (a:Person)-[:SAME_AS]->(o:Author) WHERE a.name ENDS WITH "Neumann" RETURN o.name AS author, collect(a.name) AS written_as ORDER BY author

// Q42 · Which open problems have no researcher named as working on them? (no ACTIVE_ON and no evidence author)
MATCH (p:Problem {status: "open"}) WHERE NOT (:Person)-[:ACTIVE_ON]->(p) AND NOT (:Work)-[:EVIDENCE_FOR]->(p) RETURN count(p) AS problems

// Q45 · Which open problems cite nothing published after 2015, counting evidence works too?
MATCH (p:Problem {status: "open"}) OPTIONAL MATCH (p)-[:CITES]->(x:Paper) WHERE x.year > 2015 OPTIONAL MATCH (p)<-[:EVIDENCE_FOR]-(w:Work) WHERE w.year > 2015 WITH p, count(x) + count(w) AS recent WHERE recent = 0 RETURN count(p) AS problems

// Q46 · How many citations does paper X have in total? (OpenAlex cited_by on the matched catalog paper)
MATCH (x:Paper) WHERE x.oa_cited_by IS NOT NULL RETURN x.title AS paper, x.oa_cited_by AS citations ORDER BY citations DESC LIMIT 5

// Q47 · Has problem X been solved since the catalog was written? (evidence verdicts and the suggested status; the catalog status is left unchanged)
MATCH (p:Problem)<-[e:EVIDENCE_FOR {verdict: "solves"}]-(w:Work) RETURN p.title AS problem, p.status AS catalog_status, p.status_suggested AS suggested, w.title AS paper, w.year AS year ORDER BY year DESC LIMIT 10

// Q48 · Who funds the work on problem X? (funders on the problem's cited papers and evidence works)
MATCH (p:Problem {id: "01-relational-theory/acyclic-join-dependencies"})-[:CITES]->(x:Paper) WHERE x.oa_funders IS NOT NULL UNWIND x.oa_funders AS funder RETURN funder, count(*) AS papers ORDER BY papers DESC LIMIT 10
