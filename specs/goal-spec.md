# Research Radar -- Goal Specification

## Goal
Let a student or researcher type a research topic and, usually within 20 seconds (at most about 40), get a ranked, grouped reading list of relevant arXiv papers with abstract links, PDF links and ready-to-use BibTeX, plus a plain explanation of how the search was carried out.

## Users
Students, researchers and engineers who want a quick starting reading list for an unfamiliar topic. No sign-in.

## Core journey
1. The user enters a topic (for example "diffusion models for time series"), and optionally an arXiv category and a "from year".
2. The app searches arXiv. If the first search is too narrow it broadens; if it is far too broad it narrows by date. At most 3 searches.
3. The user sees up to 20 papers, ranked, grouped into themes, each with title, authors, date, category, abstract, links and BibTeX.
4. The user sees a "How Research Radar searched" panel listing each search round, its query, result count and the decision taken.
5. The user downloads a `.bib` file or copies a Markdown reading list.

## Technology
- Chosen: FastAPI backend serving a single static HTML/JS page; arXiv public API; scikit-learn for ranking (TF-IDF) and grouping (KMeans); one Docker container on Render.
- Weighed against: React frontend on a separate host. Rejected: two deployments and a build step are not justified for one page in a one-day build.
- Weighed against: an LLM to summarise papers. Rejected for this version: needs a paid or rate-limited key; ranking and grouping can be done deterministically and tested.
- Would revisit if: users need saved searches across devices (needs a database and accounts), or plain-language summaries (needs a model, its own AI spec and evaluation).

## Constraints
- No API keys or secrets of any kind.
- Respect arXiv's usage guidance: at least 3 seconds between outbound requests; cache identical searches for 24 hours.
- Show the arXiv acknowledgement in the page footer.
- Works on a phone-width screen.

## Inputs and Outputs
- Inputs: topic (3 to 100 characters after trimming), optional category (from a fixed list), optional from_year (2000 to current year), optional max_papers (5 to 30, default 20).
- Outputs: status (completed, partial, empty, failed), ranked papers, theme groups, search trace, message.

## Acceptance Criteria
Each criterion is decided by the named test file; exact test names are recorded by the implementation.
1. A topic with enough matches returns status `completed` with at most `max_papers` papers, sorted by score descending. -- decided by: tests/test_api.py
2. A topic whose first round returns fewer than 10 results triggers a broader second round; the trace shows both rounds and the reason. -- decided by: tests/test_search_loop.py
3. The loop never makes more than 3 arXiv requests for one search. -- decided by: tests/test_search_loop.py
4. If arXiv times out or returns an error, the API returns 200 with status `failed` and a readable message; the page shows that message and no stack trace. -- decided by: tests/test_api.py
5. Zero matches after all rounds returns status `empty` with a suggestion to rephrase. -- decided by: tests/test_search_loop.py
6. An identical search within 24 hours is served from cache and makes no arXiv request. -- decided by: tests/test_cache.py
7. Two outbound arXiv requests are never less than 3 seconds apart. -- decided by: tests/test_rate_limit.py
8. Every paper has a BibTeX entry containing its arXiv ID, title, authors and year. -- decided by: tests/test_bibtex.py
9. Invalid input (topic under 3 characters, unknown category, from_year out of range) returns 422 and makes no arXiv request. -- decided by: tests/test_api.py
10. The deployed app at its public URL completes a live search for "graph neural networks". -- decided by: manual check, recorded in README with date and time.

## Acceptance Criteria Requiring Our Review
- On the 10 evaluation topics in `specs/evaluation-spec.md`, I (the architect) review whether the top 20 lists look relevant, and record hit rates and misses in `eval/results.md`.

## Output Files
- `app/` (backend code and `app/static/` page), `tests/`, `tests/fixtures/`, `eval/`, `Dockerfile`, `requirements.txt`, `README.md`.
- Do not modify `specs/` without my approval.

## Out of Scope
User accounts, saved searches, database, LLM summaries, full-text PDF reading, citation counts, other paper sources (Semantic Scholar, OpenAlex), email alerts.

## Known limits
- For broad topics, date narrowing keeps only the last 5 years, so the list is recent-only and classic papers may be absent. Research Radar has no citation data to tell which older papers matter most.
- TF-IDF relevance favours papers with short titles that repeat the topic words, so a narrow paper can outrank a broad survey.
- Identical searches running at the same time both call arXiv; the cache only helps once the first one has finished.
