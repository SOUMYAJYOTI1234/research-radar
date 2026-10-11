# Research Radar

Research Radar turns a research topic into a starting reading list. You type a topic such as "diffusion models for time series", optionally pick an arXiv category and a "from year", and within about 20 seconds (at most about 40) you get up to 20 arXiv papers, ranked and grouped into themes. Each paper has its abstract, links to the arXiv page and PDF, and a ready-to-use BibTeX entry. The page also shows how the search was carried out, round by round, and lets you download a `.bib` file or copy a Markdown reading list. It uses the free public arXiv API: no API keys, no accounts, no database and no language model.

**Live app:** https://research-radar-cyju.onrender.com

The app runs on a free Render instance that sleeps when idle, so the first request after a quiet spell can take about a minute.

## How it works

- **Bounded search loop.** The topic is normalised into at most 6 terms. Research Radar then searches arXiv from narrow to broad: the exact phrase in title or abstract, then all the words, then any of the words. It stops as soon as a round returns between 10 and 1,000 matches, and never makes more than 3 arXiv requests for one search.
- **Date narrowing.** If a round finds more than 1,000 matches and no "from year" was given, the same round is repeated for the last 5 years only. A too-broad topic therefore gives a recent list.
- **Ranking.** Each paper is scored with TF-IDF cosine similarity between the topic and the paper's title (counted twice) plus abstract. Relevance is min-max normalised within the round to 0–1, then combined with recency: `score = 0.8 × relevance + 0.2 × recency`, where recency falls to 0 for papers 10 or more years old.
- **Grouping.** With 8 or more papers, KMeans groups them into up to 4 themes. Each theme is labelled with its strongest terms, leaving out the topic's own words.
- **BibTeX.** Each paper gets an `@misc` entry with a stable key such as `vaswani2017attention`, its arXiv ID, title, authors and year. LaTeX special characters in titles are escaped, and `$...$` maths is left unchanged.
- **24-hour cache.** An identical search within 24 hours is answered from memory without calling arXiv. Failed searches are never cached.
- **3-second arXiv spacing.** One process-wide limiter keeps outbound arXiv requests at least 3 seconds apart, one at a time, as arXiv asks. Inbound, each client can make at most 10 searches per minute.
- **Visible trace.** Every response includes a trace of each round: its query, result count, the decision taken and why. The page shows it in the "How Research Radar searched" panel.

The backend is FastAPI with httpx, scikit-learn and numpy. The frontend is one static page in plain HTML, CSS and JavaScript, with no framework and no build step. Everything runs in one Docker container.

## Run locally

You need Python 3.12 (the Docker image uses 3.12; development used 3.13).

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. To include a contact address in the User-Agent sent to arXiv, set the optional `CONTACT_EMAIL` environment variable.

The API is small: `GET /api/health` returns `{"status": "ok"}`, and `POST /api/search` takes `{"topic": "...", "category": null, "from_year": null, "max_papers": 20}`. The full contract is in [specs/api-contract-spec.md](specs/api-contract-spec.md).

## Tests

```bash
pytest -q
```

The tests never call arXiv. The arXiv client always receives an injected `httpx.AsyncClient`; tests use one built on `httpx.MockTransport` that serves hand-written Atom files from `tests/fixtures/` and logs every request, so a test can count arXiv calls. The 3-second limiter and the inbound limit are tested with fake clocks, so nothing really sleeps.

## Evaluation

```bash
python eval/run_eval.py
```

This is a live run against arXiv and takes several minutes, because of the 3-second spacing. For each topic in [eval/golden_topics.json](eval/golden_topics.json) it calls the uncached search with no filters and `max_papers=20`, and checks whether the well-known paper for that topic appears in the top 20. The topics are 10 golden topics, each naming one well-known paper, plus 2 loop-behaviour cases. It writes [eval/results.md](eval/results.md) with the run time, the commit, a table per topic with its trace, and the totals. Results change as arXiv adds papers, so the date matters.

## Specs and process

Research Radar was built spec-first. The specs in [specs/](specs/) are the source of truth:

- [goal-spec.md](specs/goal-spec.md): the goal, users, journey, constraints, acceptance criteria and known limits.
- [backend-spec.md](specs/backend-spec.md): topic normalisation, the arXiv request, the search loop, ranking, grouping, BibTeX, cache, inbound limit and logging.
- [api-contract-spec.md](specs/api-contract-spec.md): the HTTP API, field by field.
- [frontend-spec.md](specs/frontend-spec.md): the page, its states and behaviour rules.
- [evaluation-spec.md](specs/evaluation-spec.md): the automated tests and the live evaluation.
- [plan.md](specs/plan.md): the phased implementation plan.

The process:

1. The specs were written and reviewed before any code. Contradictions and gaps were resolved as explicit decisions.
2. A phased plan (P1–P7) was agreed, listing for each phase its files, tests, the acceptance criteria it covers and how to verify it.
3. Each phase was built tests first, then code. It was committed only when every test passed.
4. When a behaviour change was approved during the build (for example normalising relevance, or the label and BibTeX rules), the spec was updated first, then the tests and the code. Ideas outside the specs were recorded as open questions instead of being built.

## Acceptance criterion 10: live check on the deployed app

| Date | Time (UTC) | URL | Search | Result |
|---|---|---|---|---|
| 11 Oct 2026 | _not recorded_ | https://research-radar-cyju.onrender.com | "graph neural networks" | `status: completed`, message "Found 20 papers in 2 searches."; a repeated identical search returned `cached: true` |

## Known limits

From [specs/goal-spec.md](specs/goal-spec.md):

- For broad topics, date narrowing keeps only the last 5 years, so the list is recent-only and classic papers may be absent. Research Radar has no citation data to tell which older papers matter most.
- TF-IDF relevance favours papers with short titles that repeat the topic words, so a narrow paper can outrank a broad survey.
- Identical searches running at the same time both call arXiv; the cache only helps once the first one has finished.
- BibTeX output does not specially handle display math (`$$...$$`), escaped braces (`\{ \}`), or a stray unpaired `$` before a math segment. It has been checked as text only, not compiled with LaTeX.

Deployment and testing:

- The inbound limit identifies a client by the first `X-Forwarded-For` address, which a client can fake.
- The cache is in memory, so it is lost whenever the app restarts or the free instance sleeps.
- The free Render instance sleeps when idle; the first request after that is slow.
- Tests run on Python 3.13 locally, while the Docker image uses Python 3.12.
- The evaluation hit rate covers only the 10 hand-picked topics in `eval/golden_topics.json`. It is not a measure of quality for all topics.

## Acknowledgement

Data from the arXiv API. Thank you to arXiv for use of its open access interoperability.
