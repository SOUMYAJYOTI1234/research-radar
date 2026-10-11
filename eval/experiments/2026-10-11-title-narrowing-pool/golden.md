# Experiment: title narrowing and pool size (golden topics)

- Run: 2026-10-11 18:22 UTC
- Commit: `0083693-dirty`
- Configurations: `baseline`: date narrowing, max_results=50; `a`: title, then date narrowing, max_results=50; `b`: date narrowing, max_results=100; `ab`: title, then date narrowing, max_results=100.
- Order: interleaved per topic (every configuration back to back), alternating forward and reversed from topic to topic because arXiv caches identical request URLs; 3 s pause between searches; uncached `run_search()`, no filters, `max_papers=20`.
- Decision rule: specs/evaluation-spec.md, "Experiment: title narrowing and pool size" (fixed before the run).

## Expected paper per configuration

| # | Topic | Expected | baseline | a | b | ab |
|---|---|---|---|---|---|---|
| 1 | variational autoencoder | 1312.6114 | not in pool | not in pool | not in pool | not in pool |
| 2 | generative adversarial networks | 1406.2661 | not in pool | rank 19 | not in pool | in pool (arXiv #1), ranked out |
| 3 | denoising diffusion probabilistic models | 2006.11239 | not in pool | not in pool | not in pool | not in pool |
| 4 | retrieval augmented generation | 2005.11401 | not in pool | not in pool | not in pool | not in pool |
| 5 | chain of thought prompting | 2201.11903 | rank 1 | rank 1 | rank 1 | rank 1 |
| 6 | reasoning and acting language model agents | 2210.03629 | not in pool | not in pool | not in pool | not in pool |
| 7 | deep residual learning image recognition | 1512.03385 | excluded by narrowing | excluded by narrowing | excluded by narrowing | excluded by narrowing |
| 8 | adam stochastic optimization | 1412.6980 | in pool (arXiv #6), ranked out | in pool (arXiv #6), ranked out | in pool (arXiv #6), ranked out | in pool (arXiv #6), ranked out |
| 9 | quantum approximate optimization algorithm | 1411.4028 | not in pool | not in pool | not in pool | not in pool |
| 10 | variational quantum eigensolver | 1304.3117 | not in pool | not in pool | not in pool | not in pool |

## Search path per configuration

| # | Topic | baseline | a | b | ab |
|---|---|---|---|---|---|
| 1 | variational autoencoder | exact 4702 > exact+date_narrowed 3004 (2 req, 8.1 s) | exact 0 FAILED (1 req, 10.0 s) | exact 4702 > exact+date_narrowed 3004 (2 req, 11.3 s) | exact 4702 > exact+title_narrowed 1128 (2 req, 14.2 s) |
| 2 | generative adversarial networks | exact 8183 > exact+date_narrowed 3680 (2 req, 8.4 s) | exact 8183 > exact+title_narrowed 2218 (2 req, 7.0 s) | exact 8183 > exact+date_narrowed 3680 (2 req, 14.9 s) | exact 8183 > exact+title_narrowed 2218 (2 req, 16.0 s) |
| 3 | denoising diffusion probabilistic models | exact 755 (1 req, 3.8 s) | exact 755 (1 req, 5.8 s) | exact 755 (1 req, 7.8 s) | exact 755 (1 req, 5.6 s) |
| 4 | retrieval augmented generation | exact 6082 > exact+date_narrowed 6073 (2 req, 11.0 s) | exact 6082 > exact+title_narrowed 1555 (2 req, 8.4 s) | exact 6082 > exact+date_narrowed 0 FAILED (2 req, 13.1 s) | exact 6082 > exact+title_narrowed 0 FAILED (2 req, 17.5 s) |
| 5 | chain of thought prompting | exact 0 > all_words 2570 > all_words+date_narrowed 0 FAILED (3 req, 22.5 s) | exact 0 > all_words 2570 > all_words+date_narrowed 2566 (3 req, 6.7 s) | exact 0 > all_words 2570 > all_words+date_narrowed 2566 (3 req, 7.1 s) | exact 0 > all_words 2570 > all_words+date_narrowed 2566 (3 req, 6.2 s) |
| 6 | reasoning and acting language model agents | exact 0 > all_words 603 (2 req, 3.3 s) | exact 0 > all_words 603 (2 req, 5.1 s) | exact 0 > all_words 603 (2 req, 3.4 s) | exact 0 > all_words 603 (2 req, 4.4 s) |
| 7 | deep residual learning image recognition | exact 0 > all_words 1059 > all_words+date_narrowed 465 (3 req, 7.1 s) | exact 0 > all_words 1059 > all_words+date_narrowed 465 (3 req, 6.2 s) | exact 0 > all_words 1059 > all_words+date_narrowed 465 (3 req, 8.2 s) | exact 0 > all_words 1059 > all_words+date_narrowed 465 (3 req, 6.3 s) |
| 8 | adam stochastic optimization | exact 3 > all_words 523 (2 req, 3.2 s) | exact 3 > all_words 523 (2 req, 3.8 s) | exact 3 > all_words 523 (2 req, 3.2 s) | exact 3 > all_words 523 (2 req, 4.0 s) |
| 9 | quantum approximate optimization algorithm | exact 905 (1 req, 0.6 s) | exact 905 (1 req, 0.1 s) | exact 905 (1 req, 0.8 s) | exact 905 (1 req, 0.2 s) |
| 10 | variational quantum eigensolver | exact 1159 > exact+date_narrowed 832 (2 req, 3.7 s) | exact 1159 > exact+title_narrowed 314 (2 req, 6.4 s) | exact 1159 > exact+date_narrowed 832 (2 req, 3.7 s) | exact 1159 > exact+title_narrowed 314 (2 req, 3.8 s) |
| 11 | zxqv blorptastic | exact 0 > all_words 0 > any_word 0 (3 req, 6.4 s) | exact 0 > all_words 0 > any_word 0 (3 req, 6.1 s) | exact 0 > all_words 0 > any_word 0 (3 req, 6.5 s) | exact 0 > all_words 0 > any_word 0 (3 req, 6.1 s) |
| 12 | graph neural networks | exact 12325 > exact+date_narrowed 9876 (2 req, 3.6 s) | exact 12325 > exact+title_narrowed 4623 (2 req, 3.2 s) | exact 12325 > exact+date_narrowed 9876 (2 req, 3.9 s) | exact 12325 > exact+title_narrowed 4623 (2 req, 3.2 s) |

## Loop-behaviour cases

| Topic | Expectation | baseline | a | b | ab |
|---|---|---|---|---|---|
| zxqv blorptastic | empty after all rounds | pass | pass | pass | pass |
| graph neural networks | narrowing used (title or date) | pass | pass | pass | pass |

## Totals per configuration

| Measure | baseline | a | b | ab |
|---|---|---|---|---|
| Golden hits | 1 of 10 | 2 of 10 | 1 of 10 | 1 of 10 |
| Gained vs baseline | - | generative adversarial networks | - | - |
| Lost vs baseline | - | - | - | - |
| Mean requests per search | 2.08 | 2.00 | 2.08 | 2.08 |
| Search time median / max (s) | 5.1 / 22.5 | 6.2 / 10.0 | 6.8 / 14.9 | 5.9 / 17.5 |
| Request time p90 / max (s) | 5.0 / 9.4 | 3.5 / 5.7 | 7.7 / 8.9 | 7.2 / 9.3 |
| KB from arXiv per search mean / max | 150 / 237 | 144 / 237 | 303 / 477 | 303 / 477 |
| Failed searches | chain of thought prompting | variational autoencoder | retrieval augmented generation | retrieval augmented generation |
| Loop cases | pass | pass | pass | pass |

Hits are counted on these golden topics only; they are not a measure of quality for all topics.

## Decision rule applied

| Configuration | Qualifies | Failed criteria |
|---|---|---|
| a | no | 1. hits 2 < baseline 1 + 2; 3. failed searches: variational autoencoder |
| b | no | 1. hits 1 < baseline 1 + 2; 3. failed searches: retrieval augmented generation; 5. request p90 7.7 s > 7 s |
| ab | no | 1. hits 1 < baseline 1 + 2; 3. failed searches: retrieval augmented generation; 5. request p90 7.2 s > 7 s |

**No configuration qualifies: adopt nothing.** The failed criteria above say why.

Architect sign-off: ____________________  Date: __________
