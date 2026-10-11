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
- `graph neural networks` should trigger date narrowing (very many results).

## How to read the results
- These topics name well-known papers on purpose, so a miss is informative. Likely causes to inspect in the trace: the exact-phrase round accepted a narrow set, the recency weight pushed older classics down, or the classic was not in arXiv's top 50 for that query.
- A hit rate on 10 hand-picked topics is not a measure of quality for all users. Report it as "on these 10 topics", with the misses listed.
- Any change to scoring weights or loop thresholds must be followed by a re-run, and both results kept for comparison.
