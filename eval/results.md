# Research Radar evaluation results

- Run: 2026-10-11 17:14 UTC
- Commit: `1e55bfe-dirty`
- Search: uncached `run_search()`, no category or from-year filter, `max_papers=20`, shared 3-second arXiv limiter.
- arXiv adds papers every day, so results depend on the run date.

## Golden topics

| # | Topic | Status | Rounds | Final strategy | Final decision | Final reason | Expected | Found in top 20 (rank) |
|---|---|---|---|---|---|---|---|---|
| 1 | variational autoencoder | completed | 2 | exact+date_narrowed | accept | 3004 matches in the last 5 years, so I kept these results. | 1312.6114 | none |
| 2 | generative adversarial networks | completed | 2 | exact+date_narrowed | accept | 3680 matches in the last 5 years, so I kept these results. | 1406.2661 | none |
| 3 | denoising diffusion probabilistic models | completed | 1 | exact | accept | 755 matches, a good number for a reading list. | 2006.11239 | none |
| 4 | retrieval augmented generation | completed | 2 | exact+date_narrowed | accept | 6073 matches in the last 5 years, so I kept these results. | 2005.11401 | none |
| 5 | chain of thought prompting | completed | 3 | all_words+date_narrowed | accept | 2566 matches in the last 5 years, so I kept these results. | 2201.11903 | 2201.11903 (1) |
| 6 | reasoning and acting language model agents | completed | 2 | all_words | accept | 603 matches, a good number for a reading list. | 2210.03629 | none |
| 7 | deep residual learning image recognition | completed | 3 | all_words+date_narrowed | accept | 465 matches in the last 5 years, so I kept these results. | 1512.03385 | none |
| 8 | adam stochastic optimization | completed | 2 | all_words | accept | 523 matches, a good number for a reading list. | 1412.6980 | none |
| 9 | quantum approximate optimization algorithm | completed | 1 | exact | accept | 905 matches, a good number for a reading list. | 1411.4028 | none |
| 10 | variational quantum eigensolver | completed | 2 | exact+date_narrowed | accept | 832 matches in the last 5 years, so I kept these results. | 1304.3117 | none |

## Totals

- Topics with at least one hit: 1 of 10, on these 10 topics.
- Expected IDs found in the top 20: 1 of 10, on these 10 topics.
- Misses: variational autoencoder (1312.6114); generative adversarial networks (1406.2661); denoising diffusion probabilistic models (2006.11239); retrieval augmented generation (2005.11401); reasoning and acting language model agents (2210.03629); deep residual learning image recognition (1512.03385); adam stochastic optimization (1412.6980); quantum approximate optimization algorithm (1411.4028); variational quantum eigensolver (1304.3117)

These topics name well-known papers on purpose, so a miss is informative. A hit rate on hand-picked topics is not a measure of quality for all users.

## Loop-behaviour cases

| Topic | Expectation | Status | Rounds | Strategies | Result |
|---|---|---|---|---|---|
| zxqv blorptastic | empty after all rounds | empty | 3 | exact, all_words, any_word | pass |
| graph neural networks | date narrowing used | completed | 2 | exact, exact+date_narrowed | pass |

## Trace per topic

### 1. variational autoencoder

Auto-Encoding Variational Bayes (Kingma and Welling, 2013). Terms: variational, autoencoder. Status: completed. Message: Found 20 papers in 2 searches.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"variational autoencoder" OR abs:"variational autoencoder")` | 4702 | 50 | narrow | 4702 matches are too many, so I searched only the last 5 years. | 0.6 s |
| 2 | exact+date_narrowed | `(ti:"variational autoencoder" OR abs:"variational autoencoder") AND submittedDate:[202201010000 TO 202610112359]` | 3004 | 50 | accept | 3004 matches in the last 5 years, so I kept these results. | 2.9 s |

Top 5 kept: 2610.06545 (2026), 2509.14072 (2025), 2408.07020 (2024), 2511.00475 (2025), 2509.13000 (2025)

### 2. generative adversarial networks

Generative Adversarial Networks (Goodfellow et al., 2014). Terms: generative, adversarial, networks. Status: completed. Message: Found 20 papers in 2 searches.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"generative adversarial networks" OR abs:"generative adversarial networks")` | 8183 | 50 | narrow | 8183 matches are too many, so I searched only the last 5 years. | 3.0 s |
| 2 | exact+date_narrowed | `(ti:"generative adversarial networks" OR abs:"generative adversarial networks") AND submittedDate:[202201010000 TO 202610112359]` | 3680 | 50 | accept | 3680 matches in the last 5 years, so I kept these results. | 3.0 s |

Top 5 kept: 2409.03657 (2024), 2402.19035 (2024), 2412.16662 (2024), 2206.09210 (2022), 2603.18348 (2026)

### 3. denoising diffusion probabilistic models

Denoising Diffusion Probabilistic Models (Ho, Jain and Abbeel, 2020). Terms: denoising, diffusion, probabilistic, models. Status: completed. Message: Found 20 papers in 1 search.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"denoising diffusion probabilistic models" OR abs:"denoising diffusion probabilistic models")` | 755 | 50 | accept | 755 matches, a good number for a reading list. | 3.0 s |

Top 5 kept: 2312.01682 (2023), 2102.09672 (2021), 2301.06871 (2023), 2301.03949 (2023), 2311.16353 (2023)

### 4. retrieval augmented generation

Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks (Lewis et al., 2020). Terms: retrieval, augmented, generation. Status: completed. Message: Found 20 papers in 2 searches.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"retrieval augmented generation" OR abs:"retrieval augmented generation")` | 6082 | 50 | narrow | 6082 matches are too many, so I searched only the last 5 years. | 3.0 s |
| 2 | exact+date_narrowed | `(ti:"retrieval augmented generation" OR abs:"retrieval augmented generation") AND submittedDate:[202201010000 TO 202610112359]` | 6073 | 50 | accept | 6073 matches in the last 5 years, so I kept these results. | 3.2 s |

Top 5 kept: 2403.01616 (2024), 2405.13002 (2024), 2407.03955 (2024), 2503.10150 (2025), 2607.01852 (2026)

### 5. chain of thought prompting

Chain-of-Thought Prompting Elicits Reasoning in Large Language Models (Wei et al., 2022). Terms: chain, thought, prompting. Status: completed. Message: Found 20 papers in 3 searches.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"chain thought prompting" OR abs:"chain thought prompting")` | 0 | 0 | broaden | Only 0 matches for the exact phrase, so I searched for all the words separately. | 2.6 s |
| 2 | all_words | `(all:chain AND all:thought AND all:prompting)` | 2570 | 50 | narrow | 2570 matches are too many, so I searched only the last 5 years. | 3.4 s |
| 3 | all_words+date_narrowed | `(all:chain AND all:thought AND all:prompting) AND submittedDate:[202201010000 TO 202610112359]` | 2566 | 50 | accept | 2566 matches in the last 5 years, so I kept these results. | 3.2 s |

Top 5 kept: 2201.11903 (2022), 2311.09277 (2023), 2306.00550 (2023), 2505.04135 (2025), 2310.04959 (2023)

### 6. reasoning and acting language model agents

ReAct: Synergizing Reasoning and Acting in Language Models (Yao et al., 2022). Terms: reasoning, acting, language, model, agents. Status: completed. Message: Found 20 papers in 2 searches.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"reasoning acting language model agents" OR abs:"reasoning acting language model agents")` | 0 | 0 | broaden | Only 0 matches for the exact phrase, so I searched for all the words separately. | 2.4 s |
| 2 | all_words | `(all:reasoning AND all:acting AND all:language AND all:model AND all:agents)` | 603 | 50 | accept | 603 matches, a good number for a reading list. | 4.1 s |

Top 5 kept: 2408.06458 (2024), 2608.03169 (2026), 2601.12560 (2026), 2410.10020 (2024), 2512.13159 (2025)

### 7. deep residual learning image recognition

Deep Residual Learning for Image Recognition (He et al., 2015). Terms: deep, residual, learning, image, recognition. Status: completed. Message: Found 20 papers in 3 searches.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"deep residual learning image recognition" OR abs:"deep residual learning image recognition")` | 0 | 0 | broaden | Only 0 matches for the exact phrase, so I searched for all the words separately. | 1.7 s |
| 2 | all_words | `(all:deep AND all:residual AND all:learning AND all:image AND all:recognition)` | 1059 | 50 | narrow | 1059 matches are too many, so I searched only the last 5 years. | 4.7 s |
| 3 | all_words+date_narrowed | `(all:deep AND all:residual AND all:learning AND all:image AND all:recognition) AND submittedDate:[202201010000 TO 202610112359]` | 465 | 50 | accept | 465 matches in the last 5 years, so I kept these results. | 4.1 s |

Top 5 kept: 2202.00676 (2022), 2312.06940 (2023), 2208.14625 (2022), 2308.07627 (2023), 2510.23659 (2025)

### 8. adam stochastic optimization

Adam: A Method for Stochastic Optimization (Kingma and Ba, 2014). Terms: adam, stochastic, optimization. Status: completed. Message: Found 20 papers in 2 searches.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"adam stochastic optimization" OR abs:"adam stochastic optimization")` | 3 | 3 | broaden | Only 3 matches for the exact phrase, so I searched for all the words separately. | 0.6 s |
| 2 | all_words | `(all:adam AND all:stochastic AND all:optimization)` | 523 | 50 | accept | 523 matches, a good number for a reading list. | 3.5 s |

Top 5 kept: 2003.00231 (2020), 2603.18899 (2026), 2402.03982 (2024), 2503.01660 (2025), 2403.13704 (2024)

### 9. quantum approximate optimization algorithm

A Quantum Approximate Optimization Algorithm (Farhi, Goldstone and Gutmann, 2014). Terms: quantum, approximate, optimization, algorithm. Status: completed. Message: Found 20 papers in 1 search.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"quantum approximate optimization algorithm" OR abs:"quantum approximate optimization algorithm")` | 905 | 50 | accept | 905 matches, a good number for a reading list. | 2.8 s |

Top 5 kept: 2112.07461 (2021), 1907.02359 (2019), 2211.12903 (2022), 2306.09198 (2023), 2312.06181 (2023)

### 10. variational quantum eigensolver

A variational eigenvalue solver on a quantum processor (Peruzzo et al., 2013). Terms: variational, quantum, eigensolver. Status: completed. Message: Found 20 papers in 2 searches.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"variational quantum eigensolver" OR abs:"variational quantum eigensolver")` | 1159 | 50 | narrow | 1159 matches are too many, so I searched only the last 5 years. | 2.8 s |
| 2 | exact+date_narrowed | `(ti:"variational quantum eigensolver" OR abs:"variational quantum eigensolver") AND submittedDate:[202201010000 TO 202610112359]` | 832 | 50 | accept | 832 matches in the last 5 years, so I kept these results. | 4.0 s |

Top 5 kept: 2203.04978 (2022), 2512.22572 (2025), 2303.15237 (2023), 2305.19014 (2023), 2412.19150 (2024)

### 11. zxqv blorptastic

Loop-behaviour case: no matches, so it should end empty after all rounds.. Terms: zxqv, blorptastic. Status: empty. Message: No arXiv papers matched. Try fewer or more general words.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"zxqv blorptastic" OR abs:"zxqv blorptastic")` | 0 | 0 | broaden | Only 0 matches for the exact phrase, so I searched for all the words separately. | 1.4 s |
| 2 | all_words | `(all:zxqv AND all:blorptastic)` | 0 | 0 | broaden | Only 0 matches with all the words, so I searched for any of the words. | 3.0 s |
| 3 | any_word | `(all:zxqv OR all:blorptastic)` | 0 | 0 | accept | No matches, and no broader search is left. | 3.4 s |

### 12. graph neural networks

Loop-behaviour case: very many results, so it should trigger date narrowing.. Terms: graph, neural, networks. Status: completed. Message: Found 20 papers in 2 searches.

| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |
|---|---|---|---|---|---|---|---|
| 1 | exact | `(ti:"graph neural networks" OR abs:"graph neural networks")` | 12325 | 50 | narrow | 12325 matches are too many, so I searched only the last 5 years. | 5.1 s |
| 2 | exact+date_narrowed | `(ti:"graph neural networks" OR abs:"graph neural networks") AND submittedDate:[202201010000 TO 202610112359]` | 9876 | 50 | accept | 9876 matches in the last 5 years, so I kept these results. | 3.4 s |
