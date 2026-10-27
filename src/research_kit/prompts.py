"""Prompt templates. Each asks for one JSON value and nothing else."""

SYSTEM = (
    "You are a meticulous research analyst building a knowledge graph of a scientific field. "
    "Be specific and technical. Never invent papers, numbers, people or affiliations: if the "
    "input or a web source does not support a fact, leave it out. Reply with JSON only."
)

DISAMBIGUATE = """Decide which OpenAlex author profiles belong to ONE real researcher.

Target: {name}, {institution}. Domain context: {domain}.
OpenAlex often splits one person into several profiles, and lists namesakes.

Candidates (id, name, works, citations, institutions, sample titles):
{candidates}

Use web search (the researcher's faculty page, Google Scholar, ORCID) if needed.
Return JSON: {{"keep": ["A123", ...], "reason": "one sentence"}}"""

PROFILE = """Write a deep, factual profile of the researcher {name} ({institution}).
Domain of interest: {domain}.

Their publications (id | year | title | one-line summary):
{works}

Search the web for their faculty/lab page, CV, Google Scholar, ORCID, news, talks.
Return JSON:
{{
 "name": "...", "title": "e.g. Associate Professor", "department": "...", "institution": "...",
 "homepage": "url or null", "lab": "lab/group name or null", "orcid": "or null",
 "education": [{{"degree": "...", "institution": "...", "year": "..."}}],
 "positions": [{{"role": "...", "institution": "...", "years": "..."}}],
 "bio": "4-6 sentences",
 "research_themes": [{{"name": "...", "description": "2 sentences", "paper_ids": ["W..."]}}],
 "key_contributions": ["specific contribution with the paper id(s) in brackets"],
 "techniques_and_facilities": ["experimental/computational capabilities"],
 "lab_members": [{{"name": "...", "role": "PhD student/postdoc/alumnus"}}],
 "awards": ["..."], "funding": ["agency/program"],
 "external_collaborators": [{{"name": "...", "institution": "...", "basis": "..."}}],
 "informatics_angle": "how their work does or could use data, ML, simulation or informatics"
}}"""

EXTRACT = """Extract structured research content from each paper below.
Domain: {domain}. Use only what the title/abstract states or directly implies.
Names must be short canonical noun phrases (e.g. {examples}), not sentences.

Papers:
{papers}

Return JSON: {{"papers": [ {{
 "id": "W...",
 "summary": "2-3 sentence technical summary",
 "contribution_type": "experimental | computational | theoretical | systems | algorithmic | data/ML | benchmark | survey | mixed",
 "problems": [{{"name": "...", "description": "one sentence: the gap or challenge",
               "status_in_paper": "solved-here | advanced-here | motivates-only",
               "evidence": "the phrase from the abstract that shows it, or null"}}],
 "methods": [{{"name": "{methods_desc}", "kind": "algorithm | system | theory | ML/data | experimental | measurement | synthesis | characterization | simulation | other"}}],
 "{subject_key}": ["{subject_desc}"],
 "{metric_key}": ["{metric_desc}"],
 "results": [{{"statement": "specific finding, with numbers if given", "{rs}": "or null",
               "{rm}": "or null", "value": "or null", "unit": "or null"}}],
 "datasets_tools": ["named datasets, benchmarks, codes, instruments, software systems"],
 "applications": ["..."],
 "future_work": [{{"text": "open question or next step the paper names or implies",
                  "kind": "open-problem | extension | engineering"}}]
}} ]}}
status_in_paper: "solved-here" only if the abstract claims to resolve the problem as stated;
"advanced-here" for a new result that does not close it; "motivates-only" when the paper
uses the problem as motivation. future_work kind: "open-problem" names a technical gap the
field has not closed; "extension" is a next step on this paper's own approach;
"engineering" is deployment, tuning or more experiments. Omit generic statements."""

CANONICALIZE = """Merge synonyms and near-duplicates in this list of {kind} names from {domain}
papers, and place each canonical term under a broader parent term.

Names (with counts):
{names}

Rules: merge only true synonyms/spelling variants/abbreviations (e.g. "XRD" and
"X-ray diffraction"); keep distinct concepts apart. Every input name must appear once
in "map". Parents are broader {kind} terms (they may be new terms), max 2 levels deep.
Return JSON: {{"map": {{"input name": "canonical name"}},
 "canonical": [{{"name": "...", "description": "one sentence", "parent": "broader term or null"}}]}}"""

DOMAIN = """Map the research domain "{domain}" as it relates to these researchers:
{researchers}

Main problems found in their papers (canonical, with counts): {problems}
Main methods: {methods}
Main objects of study: {materials}

Search the web for recent reviews, roadmaps and perspectives (2022-2026) on this domain.
Return JSON:
{{
 "definition": "3-4 sentences",
 "subareas": [{{"name": "...", "description": "2 sentences", "problems": ["canonical problem names from the list or new ones"],
                "methods": ["..."], "search_queries": ["2-3 OpenAlex search strings for landmark papers"]}}],
 "open_problems": [{{"name": "...", "description": "why it is open, 2 sentences", "subarea": "...",
                     "evidence": "review/roadmap that names it"}}],
 "trends": [{{"name": "...", "description": "...", "since": "year"}}],
 "key_people": [{{"name": "...", "institution": "...", "known_for": "...", "subarea": "..."}}],
 "key_resources": [{{"name": "major databases, software, benchmarks or facilities of the field", "kind": "database | software | facility | benchmark", "description": "..."}}]
}}"""

IDEAS = """You are proposing new research for {researchers} in "{domain}".

Researcher expertise (from their papers and profiles):
{profiles}

Domain map (subareas, open problems, trends):
{domain_map}

Problems, methods and results from their papers (canonical names, paper ids):
{evidence}

Focus: {focus}
{catalog}
Propose {n} concrete, non-obvious research ideas. Most should combine the strengths of
two or more of the groups (joint work); some may extend one group's line.
Ground each idea in specific papers (ids from the evidence) and open problems.
Return JSON: {{"ideas": [ {{
 "title": "...", "hypothesis": "testable statement", "rationale": "3-4 sentences",
 "researchers": ["names"], "problems": ["canonical problem names"], "methods": ["canonical method names"],
 "subjects": ["objects of study"], "supporting_papers": ["W..."], "open_problem": "name from the domain map or null",
 "catalog_problem": "id of a listed catalog problem, or null if no catalog problems are listed",
 "addresses_gap": "which part of that problem's gap or future work the idea closes, or null",
 "first_experiment": "what to do in the first 3 months", "data_needed": "...",
 "expected_result": "...", "novelty": 1-5, "feasibility": 1-5, "impact": 1-5, "risks": "..."
}} ]}}"""

CANON_MERGE = """These canonical {kind} names from {domain} papers were merged in separate
batches, so synonyms across batches may remain. Find them.

Names (with counts):
{names}

Merge only true synonyms, spelling variants and abbreviations; keep distinct concepts apart.
Return ONLY the names that change, mapped to the name they merge into (which must be one
of the listed names). Names not listed stay as they are.
Return JSON: {{"merge": {{"name": "surviving name"}}}}"""


GROUND = """You are placing research concepts from {domain} papers into an established ontology.

Each concept below is followed by numbered candidate ontology classes. For each concept decide:
- "same": the concept means exactly this class.
- "narrower": the concept is a specific kind, instance or case of this class. Choose the MOST
  specific candidate that is still correct.
- "none": no candidate is correct.

Rules:
- Choose only from the candidates listed under that concept, by number.
- Prefer "none" to a loose fit. A wrong placement is worse than no placement: it will be
  read as an authority's statement about the concept.
- Respect the kind. A software tool is not a unit; a property is not a process; a material
  is not a measurement.
- A shared word is not evidence. "Maxwell" the simulation software is not "Maxwell" the unit
  of magnetic flux; "grain" in grain boundary is not a unit of mass.

Concepts:
{items}

Return JSON only, one entry per concept:
{{"results": [{{"i": <concept number>, "relation": "same" | "narrower" | "none",
"candidate": <candidate number, or null for none>, "confidence": <0 to 1>}}]}}
"""


GROUND_CATALOG = """You are linking research problems extracted from {domain} papers to a curated
catalog of open and solved research problems.

Each extracted problem below is followed by numbered candidate catalog problems (status and topic in
brackets). For each extracted problem decide:
- "same": the paper works on exactly this catalog problem.
- "narrower": the paper works on a specific case, variant or sub-question of this catalog problem.
  Choose the MOST specific candidate that is still correct.
- "none": no candidate is correct.

Rules:
- Choose only from the candidates listed under that problem, by number.
- Prefer "none" to a loose fit. A wrong link will be read as evidence about the catalog problem's
  status, so it is worse than no link.
- Shared vocabulary is not evidence: "join ordering" is not "join dependency recognition".

Problems:
{items}

Return JSON only, one entry per problem:
{{"results": [{{"i": <problem number>, "relation": "same" | "narrower" | "none",
"candidate": <candidate number, or null for none>, "confidence": <0 to 1>}}]}}
"""

STATUS = """A curated catalog of research problems recorded this problem as of {as_of}:

Title: {title}
Catalog status: {status}
Statement: {statement}
Best known upper bounds: {upper}
Best known lower bounds: {lower}
Gap: {gap}

The papers below were linked to this problem because they work on it. For each paper, judge from its
summary and results only what it claims about THIS problem:
- "solves": it claims to close the problem as stated (e.g. matching bounds, a full resolution).
- "advances": it improves a bound, an algorithm or the evidence without closing the problem.
- "refutes": it contradicts a claim in the statement or bounds above.
- "restates": it works on the problem without a new result on it.
- "unrelated": the link was wrong.

Papers:
{papers}

Rules:
- Quote the sentence from the summary or results that supports each verdict.
- Claims in an abstract are claims, not verified facts: do not upgrade "advances" to "solves" on
  enthusiasm.
- Suggest a new status only if some paper claims to solve the problem; otherwise null.

Return JSON only:
{{"papers": [{{"i": <paper number>, "verdict": "solves" | "advances" | "refutes" | "restates" | "unrelated",
"quote": "<supporting sentence>", "confidence": <0 to 1>}}],
"suggested_status": "solved" | "partially-solved" | null, "rationale": "<one or two sentences>"}}
"""
