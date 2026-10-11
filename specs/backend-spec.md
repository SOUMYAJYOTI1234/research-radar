# Research Radar -- Backend Specification

## Responsibilities
The backend validates input, runs the bounded arXiv search loop, parses results, ranks and groups papers, builds BibTeX, caches results, and serves the static page. It is the only component that talks to arXiv.

## Modules (one FastAPI app, separate modules)
- `app/main.py`: FastAPI app, routes, static files, inbound rate limit.
- `app/models.py`: Pydantic request and response models (match `api-contract-spec.md` exactly).
- `app/topic.py`: topic normalisation and query building.
- `app/arxiv_client.py`: outbound HTTP to arXiv, shared 3-second limiter, Atom parsing.
- `app/search_loop.py`: the bounded loop and its trace.
- `app/ranking.py`: scoring and theme grouping.
- `app/bibtex.py`: BibTeX generation.
- `app/cache.py`: 24-hour in-memory cache.

## Topic normalisation (`app/topic.py`)
1. Trim, lowercase, collapse whitespace. Length after trimming must be 3 to 100 characters, else 422.
2. Split into terms on any character that is not a letter, digit or hyphen.
3. Drop terms shorter than 2 characters and terms in a fixed English stop-word list (for, of, the, and, in, on, a, an, to, with, using, via, by, from, at, is, are).
4. Keep at most the first 6 terms. If no terms remain, return 422 with "Topic needs at least one meaningful word."

## arXiv request (`app/arxiv_client.py`)
- Endpoint: `https://export.arxiv.org/api/query`, GET, parameters `search_query`, `start=0`, `max_results=50`, `sortBy=relevance`, `sortOrder=descending`.
- Timeout: 10 seconds per request. No automatic retries.
- The 10 seconds cap the whole request from start to full response, not only each phase (connect, send, read) separately.
- Header `User-Agent: ResearchRadar/1.0 (course project; contact: <CONTACT_EMAIL env var, optional>)`. When `CONTACT_EMAIL` is not set, the header is `ResearchRadar/1.0 (course project)`.
- A `CONTACT_EMAIL` that is empty or only whitespace counts as not set.
- Shared limiter: one process-wide `asyncio.Lock` plus the time of the last request; wait until at least 3.0 seconds have passed since the previous request started. The lock is held until the response (or error) arrives, so only one arXiv request is in flight at a time.
- Upstream errors: timeout, connection error, non-200 status, unparseable XML, or an arXiv error feed (a single entry whose `id` contains `api/errors`) all raise one `ArxivUnavailable` exception carrying a short reason.
- A well-formed XML document that is not an Atom feed (for example an HTML maintenance page) also raises `ArxivUnavailable`.
- Parse with `xml.etree.ElementTree` using the Atom, OpenSearch and arXiv namespaces. Per entry:
  - `arxiv_id`: from the `<id>` URL, with the version suffix removed (`2301.01234v2` becomes `2301.01234`; old-style IDs such as `hep-th/9901001` are kept whole).
  - `title`, `abstract` (from `summary`): whitespace collapsed to single spaces.
  - `authors`: list of names in order.
  - `published`, `updated`: `YYYY-MM-DD`.
  - `primary_category`: `term` attribute of `arxiv:primary_category`.
  - `abs_url`: `https://arxiv.org/abs/<arxiv_id>`. `pdf_url`: the link with `title="pdf"` (with `http://` changed to `https://`), else `https://arxiv.org/pdf/<arxiv_id>`.
- `total_results`: integer from `opensearch:totalResults`.
- Remove duplicate `arxiv_id`s, keeping the first.
- An entry that is missing a required field is skipped, and the rest of the feed is still used. Required fields: an `<id>` containing `/abs/<arxiv_id>`, `title`, `summary`, `published`, `updated` (each a readable date) and `arxiv:primary_category` with a `term`. Each skipped entry produces one log line saying an entry was skipped and why. `total_results` is still the value arXiv reported.

## Search loop (`app/search_loop.py`)
Rounds, from narrow to broad (`P` = terms joined by single spaces, `t1..tn` = terms):
- `exact`: `(ti:"P" OR abs:"P")`
- `all_words`: `(all:t1 AND all:t2 ... AND all:tn)`
- `any_word`: `(all:t1 OR all:t2 ... OR all:tn)`; only exists when there are at least 2 terms.

Filters appended to every round: `AND cat:<category>` when a category is given; `AND submittedDate:[<from_year>01010000 TO <current UTC date>2359]` when from_year is given.

Decision after each round, where `total` is `total_results`:
1. `10 <= total <= 1000`: accept this round. Stop.
2. `total > 1000`, no from_year given, and narrowing not yet used: re-run the same round with the date filter for the last 5 years (from 1 January of current year minus 4). This counts as a round. If the narrowed total is at least 10, accept it; otherwise accept the un-narrowed results. Stop.
3. `total > 1000` and narrowing not available (from_year given, narrowing already used, or the 3-request limit would be exceeded): accept, with the accepting round's `reason` set to "Broad topic; adding a category may help." when no category is given, or "Broad topic; adding more specific words or a from year may help." when a category is given. Stop.
4. `total < 10` and a broader round exists: go to the next broader round.
5. `total < 10` and no broader round exists: accept what this round returned. Stop.
- Hard limit: 3 arXiv requests per search. If the limit is reached, accept the best round so far (the one with the most results).
- "Best round so far" means the round with the most returned papers; ties go to the later round. When the third request is not a narrowed one and its total is below 10, the best round so far is accepted instead of applying rule 5. Rules 1, 2 and 3 still decide a third request whose total is 10 or more, and rule 2 decides a narrowed one.
- If a request raises `ArxivUnavailable`: if an earlier round returned at least 1 paper, accept the best earlier round (same definition) and record the failure in the trace; otherwise the search fails.

Trace entry per round: `round` (1-3), `strategy` (exact, all_words, any_word, plus `+date_narrowed` when used), `query` (the exact search_query string), `total_results`, `returned`, `decision` (accept, broaden, narrow, failed), `reason` (one plain sentence), `duration_ms`.
- The trace contains every request made, including a failed one. Earlier rows keep the decision taken after them (`narrow` or `broaden`); the last row records how the search ended.
- Narrowed total below 10: the narrowed row has decision `accept` and reason "Only N matches in the last 5 years, so I kept the round-K results." (with the actual N, and K the un-narrowed round, usually 1).
- A later request fails after an earlier round returned at least 1 paper: the failed row has decision `failed` and reason "arXiv did not respond, so I kept the results from round K." (with the actual K).
- The hard limit keeps an earlier round K: the third row has decision `accept` and reason "Only N matches, so I kept the round-K results." (with N the third round's total).

Status, with `target = min(10, max_papers)`:
- `completed`: at least `target` papers returned.
- `partial`: 1 to `target - 1` papers returned, or an accepted earlier round after a later failure.
- `empty`: 0 papers. Message: "No arXiv papers matched. Try fewer or more general words."
- `failed`: a request failed and no earlier round returned any paper. Message: "arXiv could not be reached just now. Please try again in a minute."
- Message for `completed` and `partial`: "Found {n} paper(s) in {r} search(es)." with correct singular or plural, where `n` is the number of papers returned and `r` is the number of arXiv requests made (equal to the number of trace rows, including a failed one).

## Ranking and grouping (`app/ranking.py`)
- Document text = title + " " + title + " " + abstract (title counted twice).
- Fit `TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)` on the documents from the accepted round. Relevance = cosine similarity between the vectorised topic string and each document, where the topic string is the normalised terms joined by single spaces (`" ".join(query_terms)`), so that a cache hit always matches what a fresh search would return.
- Recency = `max(0, 1 - (current_year - published_year) / 10)`.
- Normalised relevance: min-max normalise relevance over all papers of the accepted round (before the `max_papers` cut) to 0-1, `(relevance - min) / (max - min)`. If all relevances are equal, every paper gets 1.
- Score = `0.8 * normalised relevance + 0.2 * recency`, rounded to 3 decimals. Sort by score descending, then published descending, then arxiv_id ascending. Keep the top `max_papers`.
- Grouping on the kept papers: if there are at least 8, `k = min(4, n // 4)`, `KMeans(n_clusters=k, random_state=42, n_init=10)` on their TF-IDF vectors; label each group as below; number groups 0..k-1 by size, largest first. With fewer than 8 papers, one group with id 0 and label "All results".
- Group label: from the centroid terms with a weight above 0, leave out every term that has a word starting with a query term (this covers the query term itself, plurals such as `graphs`, and phrases such as `graph learning`; `subgraph` is kept). Query terms are split the way TF-IDF splits words, so `self-supervised` gives `self` and `supervised`. The label is the top 3 remaining terms by centroid weight joined by ", ", fewer if fewer remain, or "Other" if none remain. Equal weights are ordered alphabetically.
- With 0 papers (`empty` or `failed`), `groups` is an empty list.

## BibTeX (`app/bibtex.py`)
- Key: lowercase ASCII surname of the first author + year + first title word longer than 3 letters, letters only (for example `vaswani2017attention`). Repeated keys in one response get suffixes `a`, `b`, ...
  - Surname: the last whitespace-separated word of the first author's name. Accents are removed (Unicode NFKD, combining marks dropped, so `Müller` becomes `muller`), then only `a`-`z` are kept. If nothing remains, use `anon`.
  - Year: the year of `published`.
  - Title word: the first word whose letters-only form is longer than 3 letters, lowercased and accent-stripped the same way. If there is none, that part is left out.
  - Repeats: the first occurrence keeps the bare key; later ones get `a`, `b`, ... in response order (`vaswani2017attention`, `vaswani2017attentiona`).
- Entry: `@misc{key, title={...}, author={A and B and C}, year={YYYY}, eprint={arxiv_id}, archivePrefix={arXiv}, primaryClass={primary_category}, url={abs_url}}`. Curly braces inside titles are removed.
- Then the LaTeX special characters `&`, `%`, `#`, `_` and `$` in titles are escaped with a backslash (`R&D` becomes `R\&D`). A character already preceded by a backslash is left as it is, so it is not escaped twice.

## Cache (`app/cache.py`)
- In-memory, keyed by (terms tuple, category, from_year, max_papers). Time to live 24 hours. At most 200 entries; evict least recently used.
- Store `completed`, `partial` and `empty` responses. Never cache `failed`.
- A cache hit returns the stored response with `cached: true` and makes no arXiv request. The stored `message` and `trace` are returned unchanged. The cache is lost on restart; that is accepted.
- Placement: `run_search()` runs the loop, ranking, grouping and BibTeX with no cache. `cached_search()` wraps it with the cache. The API route calls `cached_search()`; the evaluation script calls `run_search()`.

## Inbound limit
- At most 10 searches per minute per client. Client = first address in `X-Forwarded-For`, else the socket address. Excess requests get 429 with detail "Too many searches. Please wait a minute."
- Every `POST /api/search` counts, including requests that end in 422 and cache hits. The limit is checked before validation, so a limited client gets 429 even for invalid input.
- Known limit: the first `X-Forwarded-For` address is set by the client and can be faked. Accepted for this project; noted in the README.

## Logging
- One log line per round: strategy, total_results, duration_ms. Do not log client IP addresses.

## Deployment
- `Dockerfile` from `python:3.12-slim`; install `requirements.txt`; run `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`.
- Render: Web Service, Docker runtime, free instance, health check path `/api/health`. No secrets required. Optional env var `CONTACT_EMAIL`.
- Free instances sleep when idle; the first request after sleep is slow. Open the app a minute before a demo.

## Open questions
- (none yet)
