# Research Radar -- API Contract

## Decisions (plain language)
- When the page asks whether the service is up, it gets "ok".
- When the user searches with a valid topic, the page always gets one result object with a status, papers, groups, a trace and a message, even if arXiv failed. The page decides what to show from `status`.
- When the input is invalid, the page gets a validation error and no search happens.
- When a user searches too often, the page gets a "too many searches" error.

## Encoding

### GET /api/health
200 `{"status": "ok"}`

### POST /api/search
Request body:
```json
{
  "topic": "diffusion models for time series",
  "category": "cs.LG",
  "from_year": 2020,
  "max_papers": 20
}
```
- `topic`: string, required, 3 to 100 characters after trimming.
- `category`: optional, null or one of `cs.AI, cs.LG, cs.CL, cs.CV, cs.RO, cs.IR, stat.ML, quant-ph, physics.comp-ph, math.OC, eess.SP, q-bio.QM`.
- `from_year`: optional, null or integer from 2000 to the current year.
- `max_papers`: optional integer 5 to 30, default 20.

200 response:
```json
{
  "status": "completed",
  "message": "Found 20 papers in 2 searches.",
  "cached": false,
  "query_terms": ["diffusion", "models", "time", "series"],
  "papers": [
    {
      "arxiv_id": "2301.01234",
      "title": "...",
      "authors": ["A. Author", "B. Author"],
      "published": "2023-01-03",
      "updated": "2023-02-10",
      "primary_category": "cs.LG",
      "abstract": "...",
      "abs_url": "https://arxiv.org/abs/2301.01234",
      "pdf_url": "https://arxiv.org/pdf/2301.01234v2",
      "score": 0.734,
      "group_id": 0,
      "bibtex": "@misc{author2023diffusion, ...}"
    }
  ],
  "groups": [
    {"group_id": 0, "label": "diffusion, forecasting, probabilistic", "size": 9}
  ],
  "trace": [
    {
      "round": 1,
      "strategy": "exact",
      "query": "(ti:\"diffusion models time series\" OR abs:\"diffusion models time series\") AND cat:cs.LG AND submittedDate:[202001010000 TO 202610102359]",
      "total_results": 4,
      "returned": 4,
      "decision": "broaden",
      "reason": "Only 4 matches for the exact phrase, so I searched for all the words separately.",
      "duration_ms": 1830
    }
  ]
}
```
- `status`: `completed | partial | empty | failed`.
- For `failed`: `papers` and `groups` are empty lists; `trace` contains every round run, including the failed one; `message` explains.
- `cached`: true when served from cache.

Errors:
- 422: invalid body (FastAPI validation format), or topic with no meaningful word (`{"detail": "Topic needs at least one meaningful word."}`).
- 429: `{"detail": "Too many searches. Please wait a minute."}`

### GET /
Serves `app/static/index.html`. Static assets under `/static/`.
