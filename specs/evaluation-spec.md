# Research Radar -- Evaluation Specification

## Purpose
Unit tests show that the code does what the specs say. This evaluation asks a different question: for realistic topics, does the reading list contain papers a knowledgeable reader would expect?

## Automated tests (no network)
- Recorded Atom fixtures in `tests/fixtures/`: a normal result (at least 10 entries), a broad result (`opensearch:totalResults` above 1000), a small result (3 entries), an empty result, an arXiv error feed, malformed XML, and an entry with an old-style ID.
- `httpx.MockTransport` returns fixtures per query, so loop decisions can be tested round by round.
- The 3-second limiter is tested with an injected clock, not real sleeping.
- The limiter is also tested to show that a second request does not start until the first has finished (the lock is held for the whole request).

## Live evaluation (`eval/run_eval.py`)
- Input: `eval/golden_topics.json`, a list of `{topic, expected_ids, note}`.
- For each topic: call the search function directly (the uncached `run_search()`, so every run is live; no filters, `max_papers=20`), record status, number of rounds, final strategy, and which expected IDs appear in the top 20. "Final strategy" is the strategy of the last trace row; the table also records that row's decision and reason, because the reason names the round whose results were kept.
- Output: `eval/results.md` with run date and time (UTC), app commit hash, a table per topic, and totals: topics with at least one hit, total expected IDs found out of total expected.
- Commit hash: `git rev-parse --short HEAD`, with "-dirty" appended when `git status --porcelain` shows uncommitted changes, or "unknown" when git or a commit is not available. The run goes ahead in every case.
- Run spacing comes from the shared limiter; a full run takes several minutes. Results change as arXiv adds papers daily, so the date matters.

## Golden topics (draft; I verify every ID on arxiv.org before the first run)
| Topic | Expected arXiv IDs |
|---|---|
| variational autoencoder | 1312.6114 |
| generative adversarial networks | 1406.2661 |
| denoising diffusion probabilistic models | 2006.11239 |
| retrieval augmented generation | 2005.11401 |
| chain of thought prompting | 2201.11903 |
| reasoning and acting language model agents | 2210.03629 |
| deep residual learning image recognition | 1512.03385 |
| adam stochastic optimization | 1412.6980 |
| quantum approximate optimization algorithm | 1411.4028 |
| variational quantum eigensolver | 1304.3117 |

Loop-behaviour cases (checked for status and trace, not hits):
- `zxqv blorptastic` should end `empty` after all rounds.
- `graph neural networks` should trigger narrowing, by title or by date (very many results).

## How to read the results
- These topics name well-known papers on purpose, so a miss is informative. Likely causes to inspect in the trace: the exact-phrase round accepted a narrow set, the recency weight pushed older classics down, or the classic was not in arXiv's top 50 for that query.
- A hit rate on 10 hand-picked topics is not a measure of quality for all users. Report it as "on these 10 topics", with the misses listed.
- Any change to scoring weights or loop thresholds must be followed by a re-run, and both results kept for comparison.

## Held-out topics
- `eval/heldout_topics.json` holds 10 topics that are not in the golden set, each with one well-known paper ID. The architect verifies every ID on arxiv.org before the file is first used.
- The held-out topics are never used for tuning. They are run only after a decision on the golden topics has been recorded and committed, once per adopted change, comparing the baseline with the adopted configuration.
- Held-out results are reported as they are. They can confirm or reject an adopted change; they never choose parameters, and a held-out result is never followed by another tuning step on the same held-out set.
- The held-out topics and IDs must not overlap the golden topics or IDs (checked by a test).

## Controlled experiments
- A controlled experiment compares configurations of the search on the same day, interleaved: for each topic, every configuration runs back to back, so arXiv's data cannot drift between configurations.
- Configurations are chosen with evaluation-only switches (`python eval/run_eval.py --configs ...`). Production always runs the configuration the backend spec describes; a switch never changes it.
- The evaluation pauses 3 seconds between searches, so no search waits on the previous search's spacing. "Search time" is the wall time of one `run_search()` call. "Request time" is the time of one arXiv HTTP request from sending to the full response, without the limiter wait.
- Each experiment writes `eval/experiments/<run date>-<name>/golden.md` (and later `heldout.md`). `eval/results.md` stays as the baseline record.

### Experiment: title narrowing and pool size (2026-10-11)
Configurations:
- `baseline`: date narrowing (today's rule 2), `max_results=50`.
- `a`: title narrowing first (`ti:"P"` with the same filters, only after an `exact` round above 1000; date narrowing if the title total is below 10 and no from_year), `max_results=50`.
- `b`: date narrowing, `max_results=100`.
- `ab`: title narrowing first, `max_results=100`.

Decision rule (fixed before the run; applied mechanically by the report):
1. A configuration qualifies only if all of these hold on this run:
   1. Golden hits (expected ID in the top 20) are at least the baseline's golden hits in the same run plus 2.
   2. Every golden topic that the baseline hits in the same run is also hit.
   3. No search ends with status `failed`, and no trace row has decision `failed`.
   4. Every search time is at most 40 seconds.
   5. The 90th percentile (nearest rank) of all request times is at most 7 seconds.
   6. Both loop-behaviour cases pass.
2. Among qualifying configurations, choose the one with the most golden hits. On a tie, prefer a single change (`a` or `b`) over `ab`, and `a` over `b` (it does not increase the data fetched from arXiv).
3. If no configuration qualifies, adopt nothing and record why.
4. The result is a recommendation. Nothing changes in production until the architect signs off; then the backend spec is updated first, then the code and tests, and the held-out topics are run once.
