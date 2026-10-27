// AI scope questions from ai-research-kg benchmarks/queries.py (KG commit 4742747,
// catalog samyama-ai/ai_research @ a02e87b), one per query, in the bench format. Qn is the
// query id's number (AR14 -> Q14); the docs/scope.md question number(s) are given in brackets.
// {AUTHOR} (AR23) is resolved by TOP_AUTHOR, the full-name author with the most papers. It
// returns "Luke Zettlemoyer" (31 papers) on both V1 and V3, so the value is written in here.
// The scope questions no query answers (UNANSWERED) are listed at the end with V1's reason.
// Run with
//   research-kit bench benchmarks/ai_v1.cypher (--load-dir catalogs/ai | --url <V3 server>) --out runs/bench/ai-v1.json

// Q1 · What are the 35 AI research topics? [scope Q1]
MATCH (t:Topic) RETURN t.number AS number, t.name AS topic ORDER BY number

// Q2 · How many problems are there in total, and how many per status (open = status 'open')? [scope Q2]
MATCH (p:Problem) RETURN p.status AS status, count(p.id) AS problems ORDER BY problems DESC

// Q3 · How many problems are in each topic? [scope Q3]
MATCH (p:Problem)-[:IN_TOPIC]->(t:Topic) RETURN t.name AS topic, count(p.id) AS problems ORDER BY problems DESC

// Q4 · Which topics have the largest share of open problems? (open count and topic size; divide for the share) [scope Q4]
MATCH (p:Problem)-[:IN_TOPIC]->(t:Topic) WHERE p.status = 'open' RETURN t.name AS topic, count(p.id) AS open_problems ORDER BY open_problems DESC LIMIT 10

// Q5 · Topic sizes, to turn AR04's open counts into shares [no scope question]
MATCH (p:Problem)-[:IN_TOPIC]->(t:Topic) RETURN t.name AS topic, count(p.id) AS problems ORDER BY topic

// Q6 · How many gaps are theoretically open vs empirically open vs methodologically blocked? [scope Q5]
MATCH (p:Problem)-[:HAS_GAP]->(q:OpenQuestion) RETURN q.kind AS kind, count(q.id) AS gaps ORDER BY gaps DESC

// Q7 · Which problems are solved but impractical? [scope Q6]
MATCH (p:Problem)-[:IN_TOPIC]->(t:Topic) WHERE p.status = 'solved-but-impractical' RETURN t.name AS topic, p.title AS problem ORDER BY topic

// Q8 · What are the most common reasons these problems remain hard? [scope Q8]
MATCH (p:Problem)-[:BLOCKED_BY]->(o:Obstruction) RETURN o.name AS obstruction, count(p.id) AS problems ORDER BY problems DESC

// Q9 · Which open problems have a next experiment that fits on a single machine? [scope Q37]
MATCH (p:Problem)-[:HAS_NEXT_EXPERIMENT]->(f:FutureDirection) WHERE p.status = 'open' AND f.single_machine = true RETURN p.title AS problem, f.compute_budget_gpu_hours AS gpu_hours ORDER BY gpu_hours ASC LIMIT 10

// Q33 · Which problems, whatever their status, have a next experiment that fits on a single machine? [scope Q7]
MATCH (p:Problem)-[:HAS_NEXT_EXPERIMENT]->(f:FutureDirection) WHERE f.single_machine = true RETURN p.title AS problem, p.status AS status, f.compute_budget_gpu_hours AS gpu_hours ORDER BY gpu_hours ASC LIMIT 10

// Q10 · What does problem X state, and what is its status and topic? [scope Q9, Q10]
MATCH (p:Problem)-[:IN_TOPIC]->(t:Topic) WHERE p.slug = 'internals-based-safety-verification' RETURN p.title AS problem, p.status AS status, t.name AS topic, p.statement AS statement

// Q11 · Which papers does problem X cite, and in what role? [scope Q11]
MATCH (p:Problem)-[c:CITES]->(pa:Paper) WHERE p.slug = 'internals-based-safety-verification' RETURN c.role AS role, pa.title AS paper, pa.year AS year ORDER BY role

// Q12 · What is the proposed next experiment for problem X? [scope Q13]
MATCH (p:Problem)-[:HAS_NEXT_EXPERIMENT]->(f:FutureDirection) WHERE p.slug = 'internals-based-safety-verification' RETURN f.question AS question, f.compute_budget_gpu_hours AS gpu_hours, f.deciding_number AS deciding_number

// Q13 · Which labs are named as working on problem X? [scope Q23]
MATCH (i:Institution)-[a:ACTIVE_ON]->(p:Problem) WHERE p.slug = 'internals-based-safety-verification' RETURN i.name AS lab, a.direction AS direction

// Q14 · Which papers are cited by the most problems? [scope Q14]
MATCH (p:Problem)-[:CITES]->(pa:Paper) RETURN pa.title AS paper, pa.year AS year, count(p.id) AS citing_problems ORDER BY citing_problems DESC LIMIT 10

// Q15 · Which papers are cited across the most topics? [scope Q15]
MATCH (t:Topic)<-[:IN_TOPIC]-(p:Problem)-[:CITES]->(pa:Paper) RETURN pa.title AS paper, count(DISTINCT t.id) AS topics ORDER BY topics DESC LIMIT 10

// Q16 · Which surveys cover the most problems? [scope Q17]
MATCH (p:Problem)-[c:CITES]->(pa:Paper) WHERE c.role = 'survey' RETURN pa.title AS survey, count(p.id) AS problems ORDER BY problems DESC LIMIT 10

// Q17 · Which foundational papers underpin the most problems? [scope Q18]
MATCH (p:Problem)-[c:CITES]->(pa:Paper) WHERE c.role = 'foundational' RETURN pa.title AS paper, count(p.id) AS problems ORDER BY problems DESC LIMIT 10

// Q18 · Which papers are cited as cautions or negative results most often? [scope Q19]
MATCH (p:Problem)-[c:CITES]->(pa:Paper) WHERE c.role = 'caution' RETURN pa.title AS paper, count(p.id) AS problems ORDER BY problems DESC LIMIT 10

// Q19 · Which venues' papers are cited by the most problems? [no scope question]
MATCH (p:Problem)-[:CITES]->(pa:Paper)-[:APPEARED_AT]->(v:Venue) RETURN v.name AS venue, count(p.id) AS citations, count(DISTINCT pa.id) AS papers ORDER BY citations DESC LIMIT 10

// Q20 · Which researchers (full names) appear on papers cited by the most problems? [scope Q20]
MATCH (p:Problem)-[:CITES]->(pa:Paper)-[:AUTHORED_BY]->(per:Person) WHERE per.name_form = 'full' RETURN per.name AS author, count(DISTINCT p.id) AS problems ORDER BY problems DESC LIMIT 10

// Q21 · Which researchers are linked to problems in the most topics? [scope Q21]
MATCH (t:Topic)<-[:IN_TOPIC]-(p:Problem)-[:CITES]->(:Paper)-[:AUTHORED_BY]->(per:Person) WHERE per.name_form = 'full' RETURN per.name AS author, count(DISTINCT t.id) AS topics ORDER BY topics DESC LIMIT 10

// Q22 · Which labs are named as working on the most open problems? [scope Q22]
MATCH (i:Institution)-[:ACTIVE_ON]->(p:Problem) WHERE p.status = 'open' RETURN i.name AS lab, count(DISTINCT p.id) AS open_problems ORDER BY open_problems DESC LIMIT 10

// Q23 · Who does the most-cited full-name author co-author with most? [scope Q24]
MATCH (a:Person)<-[:AUTHORED_BY]-(pa:Paper)-[:AUTHORED_BY]->(b:Person) WHERE a.name = 'Luke Zettlemoyer' AND b.name_form = 'full' RETURN a.name AS author, b.name AS collaborator, count(pa.id) AS papers ORDER BY papers DESC LIMIT 10

// Q24 · Which problems are related to the most other problems (shared papers)? [scope Q29]
MATCH (p:Problem)-[:RELATED_TO]-(o:Problem) RETURN p.title AS problem, count(o.id) AS related ORDER BY related DESC LIMIT 10

// Q25 · Which pairs of topics are most strongly connected through related problems? [scope Q30]
MATCH (t1:Topic)<-[:IN_TOPIC]-(a:Problem)-[:RELATED_TO]-(b:Problem)-[:IN_TOPIC]->(t2:Topic) WHERE t1.name < t2.name RETURN t1.name AS topic_a, t2.name AS topic_b, count(a.id) AS links ORDER BY links DESC LIMIT 10

// Q26 · Which problems are most similar to problem X? [scope Q31]
MATCH (p:Problem)-[r:RELATED_TO]-(o:Problem) WHERE p.slug = 'internals-based-safety-verification' RETURN o.title AS problem, r.shared_papers AS shared_papers, r.score AS score ORDER BY score DESC

// Q27 · Which assumptions (by name) do the most problems rest on? [scope Q34]
MATCH (p:Problem)-[:RESTS_ON]->(a:Assumption) RETURN toLower(a.name) AS assumption, count(p.id) AS problems ORDER BY problems DESC LIMIT 10

// Q31 · Which pairs of problems share the most important papers? [scope Q16]
MATCH (a:Problem)-[r:RELATED_TO]->(b:Problem) RETURN a.title AS problem_a, b.title AS problem_b, r.shared_papers AS shared_papers, r.score AS score ORDER BY shared_papers DESC LIMIT 10

// Q32 · Which problems bridge the most other topics (related problems in many topics other than their own)? [scope Q32]
MATCH (own:Topic)<-[:IN_TOPIC]-(p:Problem)-[:RELATED_TO]-(o:Problem)-[:IN_TOPIC]->(t:Topic) WHERE t.id <> own.id RETURN p.title AS problem, own.name AS topic, count(DISTINCT t.id) AS other_topics ORDER BY other_topics DESC LIMIT 10

// Q28 · Which next experiments are cheapest to run (GPU-hours)? [scope Q36]
MATCH (p:Problem)-[:HAS_NEXT_EXPERIMENT]->(f:FutureDirection) WHERE f.compute_budget_gpu_hours > 0 RETURN p.title AS problem, f.compute_budget_gpu_hours AS gpu_hours ORDER BY gpu_hours ASC LIMIT 10

// Q29 · Which topics have the most experiments runnable on one machine? [scope Q38]
MATCH (t:Topic)<-[:IN_TOPIC]-(p:Problem)-[:HAS_NEXT_EXPERIMENT]->(f:FutureDirection) WHERE f.single_machine = true RETURN t.name AS topic, count(p.id) AS runnable ORDER BY runnable DESC LIMIT 10

// Q30 · Which open problems have no lab named as working on them? [scope Q39]
MATCH (p:Problem) WHERE p.status = 'open' AND NOT (p)<-[:ACTIVE_ON]-(:Institution) RETURN p.title AS problem LIMIT 20

// Q90 · How much funding has each problem received? (no such data) [scope Q40]
MATCH (p:Problem)-[:FUNDED_BY]->(f) RETURN p.title AS problem, f.amount AS amount

// Q91 · Which model tops a given benchmark leaderboard? (no such data) [scope Q41]
MATCH (m:Model)-[:TOPS]->(b:Benchmark) RETURN m.name AS model, b.name AS benchmark

// Not answered by V1 (UNANSWERED in queries.py):
//   scope Q12: methods: not extracted in v1 (the bold text in State of the Art is evidence labels, not method names)
//   scope Q25: methods: not extracted in v1
//   scope Q26: methods: not extracted in v1
//   scope Q27: methods: not extracted in v1
//   scope Q28: methods: not extracted in v1
//   scope Q33: stretch question: needs a directional 'enables' link between problems that the catalog never states
//   scope Q35: topic clusters need a community-detection step over RELATED_TO; not computed in v1
