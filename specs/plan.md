# Research Radar -- Implementation Plan

## Context
The specs in `specs/` are final after the review on 2026-10-11 (21 decisions plus 9 follow-up fixes). This plan builds
them in seven phases. Each phase: tests first, then code, then `pytest -q`. Commit only if every test passes, using the
message `P<n>: <short description>`. Show `git log -1 --format=full` before pushing, then stop until the user says go.

## Ground rules for every phase
- **Environment:** `.venv` created with local Python 3.13 (user decision). Packages are installed only into `.venv`.
  Production runs Python 3.12 in Docker, and there is no local Docker, so the 3.12 image is only checked by Render.
  Every phase report states this.
- **No network in tests:** the arXiv client always takes an injected `httpx.AsyncClient`. Tests pass one built on
  `httpx.MockTransport` that serves files from `tests/fixtures/` and logs every request, so tests can count calls.
- **Determinism:** "today" (UTC date) and the limiter's clock and sleep are parameters with real defaults. Tests inject
  fixed values, so query dates, recency, from_year limits and limiter timing are exact without real sleeping.
- **Async tests:** use the anyio pytest plugin (bundled with anyio, already a dependency of httpx and starlette).
  `tests/conftest.py` defines `anyio_backend = "asyncio"` so the plugin does not need trio. API tests use FastAPI's
  `TestClient`.
- **One shared limiter:** a module-level instance in `app/arxiv_client.py`, used by both the app and the eval script.
- **Dependencies:** only fastapi, uvicorn, httpx, scikit-learn, numpy, pytest. Exact pins go in one
  `requirements.txt`. Anything else needs the user's approval first.

## P1 -- Project skeleton, /api/health, Dockerfile, requirements.txt, .gitignore
**Files**
- `app/__init__.py`.
- `app/main.py`: FastAPI app, `GET /api/health`, `/static` mount, `GET /` serving `app/static/index.html`.
- `app/static/index.html`: placeholder page (header text only; P6 replaces it).
- `requirements.txt`: the 6 packages pinned with `==`, using the newest releases that install on both 3.12 and 3.13 at
  build time.
- `Dockerfile`: `python:3.12-slim`, install requirements, `CMD` running uvicorn on `${PORT:-8000}` (shell form so
  `$PORT` expands).
- `.gitignore`: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.env`, `PROMPTS.md`, `START_HERE.md`.
- `tests/conftest.py`: the anyio backend.

**Tests:** `tests/test_health.py`
- `GET /api/health` returns 200 `{"status": "ok"}`.
- `GET /` returns 200 HTML.

**Acceptance criteria:** none directly. This is the base for AC10 (deployment).

**Verify**
- `pytest -q`.
- `uvicorn app.main:app --port 8000`, then open http://localhost:8000/api/health.
- After the commit: deploy on Render (START_HERE step 4) and open `/api/health` on the public URL.

## P2 -- arXiv client, Atom parser, test fixtures
**Files**
- `app/arxiv_client.py`:
  - `ArxivUnavailable(reason)`.
  - `ArxivEntry` dataclass: arxiv_id, title, abstract, authors, published, updated, primary_category, abs_url,
    pdf_url.
  - `parse_feed(xml) -> (total_results, entries)`.
  - `ArxivClient.fetch(search_query)`: endpoint, params, 10 s timeout, User-Agent with or without `CONTACT_EMAIL`.
  - Error mapping: timeout, connection error, non-200, bad XML and error feed all raise `ArxivUnavailable`.
  - Rules: version suffix stripped (old-style IDs kept whole), https pdf_url, `YYYY-MM-DD` dates, whitespace collapsed,
    duplicates dropped.
- `tests/fixtures/`, hand-written to match real arXiv Atom:
  - `normal.xml`: 12 entries, totalResults 245.
  - `broad.xml`: 12 entries, totalResults 54000.
  - `small.xml`: 3 entries, totalResults 3.
  - `empty.xml`.
  - `error.xml`: arXiv error feed.
  - `malformed.xml`.
  - `old_style_id.xml`: includes a duplicate entry and an http pdf link.
- `tests/conftest.py`: `load_fixture()` and a `mock_arxiv(routes)` helper returning `(client, request_log)`.

**Tests:** `tests/test_arxiv_client.py`
- Every parsed field, using normal.xml.
- Old-style ID kept whole; duplicate removed; http changed to https.
- `total_results` read from broad.xml.
- Empty feed gives 0 entries.
- Each of these raises `ArxivUnavailable`: error feed, malformed XML, HTTP 500, `httpx.TimeoutException`,
  `httpx.ConnectError`.
- Request carries the right params and User-Agent, with and without `CONTACT_EMAIL`.

**Acceptance criteria:** groundwork for 4 (failures become one exception) and 8 (fields BibTeX needs).

**Verify:** `pytest -q`. Open a fixture next to a real arXiv response in the browser
(`https://export.arxiv.org/api/query?search_query=all:electron&max_results=2`) and compare the structure. That is a
manual check; tests never call arXiv.

## P3 -- Search loop, shared 3-second limiter, cache
**Files**
- `app/topic.py`:
  - `normalise(topic) -> terms`: trim, lowercase, collapse whitespace, 3-100 chars, split, stop words, at most 6 terms;
    raises `InvalidTopic`.
  - `build_query(strategy, terms, category, from_year, today, narrowed=False)`: the three strategies, cat and date
    filters, last-5-years narrowing.
- `app/arxiv_client.py`:
  - `RateLimiter(min_interval=3.0, clock, sleep)`: `asyncio.Lock` held for the whole request; starts at least 3.0 s
    apart.
  - Module-level `SHARED_LIMITER`. `fetch()` always goes through a limiter.
- `app/search_loop.py`, `run_loop(terms, category, from_year, client, today) -> LoopResult(entries, trace, status,
  message)`:
  - Rules 1-5; narrowing once.
  - Rule 3 note: two wordings, and the cap counts as "narrowing not available".
  - 3-request cap; best round so far.
  - Failure handling, trace last-row rules, status with `target = min(10, max_papers)`, message template with correct
    plurals.
  - One log line per round, with no IP address.
- `app/cache.py`: `TTLCache(ttl=24h, max_entries=200, clock)` with LRU eviction, `get` and `set`; refuses `failed`.
  P4 adds `cached_search()`.

**Tests**
- `tests/test_topic.py`: trimming and length limits, splitting on punctuation (hyphens kept), stop words, 6-term cap,
  "no meaningful word", exact query strings for each strategy and filter, date bounds from an injected `today`.
- `tests/test_rate_limit.py` (AC7):
  - With a fake clock, consecutive starts are at least 3.0 s apart.
  - No wait once 3 s have already passed.
  - A second request does not start until the first finishes.
  - The interval is measured from the previous start.
- `tests/test_search_loop.py`:
  - First round below 10 broadens; the trace shows both rounds and the reason (AC2).
  - At most 3 requests in every path, including exact<10 then all_words>1000 then narrowed (AC3).
  - `zxqv`-style topic: 0 results through all rounds gives `empty` with the rephrase message (AC5).
  - Rule 1 accepts.
  - Rule 2: narrowed total of 10 or more is accepted; below 10 falls back, with the narrowed row `accept` and the
    round-K reason.
  - Rule 3 with and without a category.
  - Cap reached gives the rule-3 note.
  - One-term topic skips `any_word`.
  - First request fails gives `failed`. Round 1 with 0 results then round 2 fails gives `failed`.
  - Round 1 with 3 papers then a failure gives `partial`, with the failed row's reason.
  - Message plurals.
- `tests/test_cache.py` (unit): hit before 24 h; miss after 24 h (fake clock); LRU eviction at 201 entries; `failed`
  never stored.

**Acceptance criteria:** 2, 3, 5, 7. AC6 is completed in P4.

**Verify:** `pytest -q`. Read `test_search_loop.py` against the decision rules in backend-spec "Search loop".

## P4 -- Ranking, grouping, BibTeX
**Files**
- `app/ranking.py`:
  - `rank(entries, query_terms, max_papers, today)`: document text with the title twice, TF-IDF settings as specified,
    relevance against `" ".join(query_terms)`, recency, score rounded to 3 decimals, 3-key sort, top `max_papers`.
  - `group(...)`: KMeans when there are 8 or more papers, otherwise one "All results" group; labels from the top 3
    centroid terms; ids ordered by size. Ties in size are broken by lowest original cluster index (not in the spec;
    needed for determinism).
- `app/bibtex.py`: `make_key()` and `make_entries(papers)`, with the key rules (NFKD, `anon`, title-word rule,
  first-bare suffixes) and the `@misc` entry format, curly braces removed from titles.
- `app/models.py`: Pydantic response models `Paper`, `Group`, `TraceEntry`, `SearchResponse`, field for field from
  api-contract-spec.
- `app/search_loop.py`: `run_search(topic_terms, category, from_year, max_papers, client, today) -> SearchResponse`.
  It chains loop, rank, group and BibTeX; status is computed from the kept papers.
- `app/cache.py`: `cached_search(...)`, keyed by (terms tuple, category, from_year, max_papers). A hit returns a copy
  with `cached: true` and the stored message and trace.

**Tests**
- `tests/test_ranking.py`:
  - Papers sorted by score descending, with the published and arxiv_id tie-breaks.
  - At most `max_papers` kept.
  - The recency formula gives 0 for papers 10 or more years old.
  - The same terms with different raw phrasing rank the same.
  - 8 or more papers give k = min(4, n // 4) groups, sizes summing to n, group 0 the largest.
  - Fewer than 8 give one "All results" group.
  - Same output on repeated runs.
- `tests/test_bibtex.py` (AC8):
  - Every entry contains its arXiv ID, title, all authors and year.
  - `vaswani2017attention`; `Müller` gives `muller`; a non-Latin name gives `anon`; no title word longer than 3
    letters omits that part.
  - Repeats give bare, then `a`, then `b`.
  - Braces stripped from titles.
- `tests/test_cache.py` (AC6): a second identical `cached_search` within 24 h returns `cached: true` and the
  MockTransport log shows no new request. `failed` is not cached, so a retry calls arXiv again.

**Acceptance criteria:** 6, 8. Groundwork for 1 (sorting and the `max_papers` cap).

**Verify:** `pytest -q`. Print one `run_search` result from fixtures in a REPL if you want to inspect group labels.

## P5 -- POST /api/search and inbound limit
**Files**
- `app/models.py`: `SearchRequest`.
  - topic stripped to 3-100 chars.
  - category as a `Literal` of the 12 codes, or null.
  - from_year 2000 to the current UTC year (validator), or null.
  - max_papers 5-30, default 20.
- `app/main.py`:
  - `POST /api/search`: validate, normalise (422 "Topic needs at least one meaningful word."), call `cached_search`.
    The response always returns 200 for completed, partial, empty and failed.
  - Inbound limiter: 10 per minute per client, a sliding window keyed by the first `X-Forwarded-For` address or the
    socket address. It runs as middleware on `POST /api/search`, so it counts every request (including 422s and cache
    hits) and runs before validation.
  - The arXiv client and `today` live on `app.state` so tests can swap them.

**Tests:** `tests/test_api.py`
- A normal fixture gives `completed`, at most `max_papers` papers, scores descending, and every contract field
  present (AC1).
- Timeout, HTTP 500 and error feed give 200 `failed`, the readable message, empty papers and groups, and no traceback
  text (AC4).
- Topic under 3 chars, unknown category, from_year 1999 or next year, max_papers 4 or 31, and a stop-words-only topic
  each give 422 with an empty request log (AC9).
- 11th request in a minute gives 429 with the exact detail; an invalid 11th request also gives 429.
- Separate `X-Forwarded-For` values are counted separately.

**Acceptance criteria:** 1, 4 (API part), 9.

**Verify**
- `pytest -q`.
- One live search, run by me only with your go-ahead since it calls arXiv:
  `curl -X POST localhost:8000/api/search -H "Content-Type: application/json" -d '{"topic":"graph neural networks"}'`.
  I show the status and trace.
- After pushing: the same curl against the Render URL.

## P6 -- Frontend page
**Files:** `app/static/index.html`, `app/static/app.js`, `app/static/styles.css`, following frontend-spec exactly.
- **Form:** 12 category labels; no `max_papers` sent; browser checks (UTC year).
- **States:**
  - Idle example topics.
  - Loading clears the old results.
  - Completed and partial (two notices).
  - Cached suffix, including on empty.
  - Empty, failed, Unreachable (60 s timeout with `AbortController`; any status other than 200, 422 or 429; non-JSON).
  - 422 mapped by `loc`.
  - 429.
- **Trace panel:** collapsed by default; shown whenever there is a trace; times in seconds.
- **Paper cards:** "score 0.73", 3 authors then "et al.", abstract toggle, PDF link, copy buttons with the
  "Copy failed" fallback textarea.
- **Export:** group-filtered list; slug rule; "et al." only with 2+ authors.
- **Behaviour:** blocking while loading; request counter; "Try again" re-sends the same inputs; all API text escaped;
  `REPO_URL` placeholder.
- **Layout:** works at 360 px; arXiv acknowledgement in the footer.

**Tests:** `tests/test_static.py`
- `/` serves the page with the form, trace panel and footer acknowledgement.
- `/static/app.js` and `/static/styles.css` return 200.

There is no JavaScript test runner (it would be a new dependency), so page behaviour is checked by hand.

**Acceptance criteria:** 4 (page part: message shown, no stack trace).

**Verify:** `pytest -q`, then a manual browser checklist delivered with the phase:
- Every state, including a 429 burst.
- Stopping the server to see Unreachable.
- `zxqv blorptastic` for the empty state.
- A 422 for year 1999.
- A title containing `<` or `&`.
- 360 px width in devtools.
- Copy buttons and the .bib download.
- Clicking an example while loading.

## P7 -- Evaluation script and README
**Files**
- `eval/golden_topics.json`: the 10 topics, plus the 2 loop-behaviour cases flagged as such.
- `eval/run_eval.py`:
  - Calls the uncached `run_search()` with the shared limiter: no filters, `max_papers=20`.
  - Records status, round count, final strategy (last trace row) with its decision and reason, and expected-ID hits in
    the top 20.
  - Writes `eval/results.md`: UTC date and time, commit (`--short` hash, "-dirty", or "unknown"), a table per topic,
    and totals worded "on these 10 topics", with misses listed.
- `README.md`:
  - What the app does.
  - Public URL placeholder.
  - Run locally, tests, evaluation.
  - Architecture in a few lines.
  - Known limits: `X-Forwarded-For` can be faked; in-memory cache lost on restart; free instance sleeps; tests run on
    3.13 while the image uses 3.12; eval hit rate covers only these 10 topics.
  - A section for the AC10 manual check, with date and time left for the user to fill in.

**Tests:** `tests/test_eval.py`
- The results-table and totals formatting, using a fake `run_search` (no network).
- Commit-hash fallback to "unknown" when git fails.

**Acceptance criteria:** 10 (README record; the check itself is manual by the user). Supports the "Requiring Our
Review" criterion (`eval/results.md`).

**Verify:** `pytest -q`. Then you verify the golden IDs on arxiv.org and run `python eval/run_eval.py` yourself
(several minutes, live). I do not run the live evaluation in P7.

## Acceptance criteria coverage
| AC | What | Phase | Decided by |
|---|---|---|---|
| 1 | completed, at most max_papers, sorted | P5 (ranking from P4) | tests/test_api.py |
| 2 | fewer than 10 broadens, trace shows both rounds | P3 | tests/test_search_loop.py |
| 3 | at most 3 arXiv requests | P3 | tests/test_search_loop.py |
| 4 | failure gives 200 `failed`, readable message, page shows it | P5 (API), P6 (page, manual) | tests/test_api.py + manual |
| 5 | zero matches gives `empty` with rephrase text | P3 | tests/test_search_loop.py |
| 6 | identical search within 24 h served from cache, no request | P3 (cache), P4 (`cached_search`) | tests/test_cache.py |
| 7 | requests at least 3 s apart | P3 | tests/test_rate_limit.py |
| 8 | BibTeX has ID, title, authors, year | P4 | tests/test_bibtex.py |
| 9 | invalid input gives 422, no request | P5 | tests/test_api.py |
| 10 | deployed live search for "graph neural networks" | P7 (README), user manual check | README |

## Not covered by automated tests
- The 3.12 Docker image (no local Docker; Render builds it).
- Real arXiv response format drift (fixtures are hand-written).
- Frontend behaviour (manual checklist in P6).
- Live evaluation results.
