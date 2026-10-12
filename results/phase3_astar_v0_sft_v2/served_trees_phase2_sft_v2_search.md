# Served value adapter `value-v0` on `trees_phase2_sft_v2_search`

Scored through vLLM (2 server(s)) and read out as the search does: top-k logprobs renormalized over the nine bin tokens, h = Σ p_k·steps_k.

| Quantity | Value |
|---|---|
| States | 17,329 |
| Bin accuracy (exact and dead labels) | 22.1% |
| MAE of expected steps given alive (exact labels) | 2.160 |
| Spearman of h with exact remaining steps | 0.648 |
| Dead AUC of p_dead (dead vs exact) | 0.468 |
| Mean P(at least n or dead) on censored labels | 0.917 |
| Mean h / mean p_dead | 3.07 / 1.14e-07 |
| Bin tokens outside the top-k per request | 1.00 |
| Prompts too long | 0 |
| States/s | 112 |
| Mean request seconds | 1.129 |
| Prompt cache hit rate | 3.7% |

## By label

| Label | States | Mean h | Median h | Mean p_dead |
|---|---|---|---|---|
| exact 1 | 148 | 1.88 | 1.67 | 6.70e-08 |
| exact 2 | 71 | 2.74 | 2.39 | 1.07e-07 |
| exact 3 | 49 | 3.14 | 2.73 | 1.30e-07 |
| exact 4 | 30 | 3.53 | 3.15 | 1.47e-07 |
| exact 5 | 15 | 3.75 | 3.52 | 1.36e-07 |
| exact 6 | 13 | 3.99 | 2.84 | 1.28e-07 |
| exact 7 | 14 | 4.27 | 3.26 | 1.19e-07 |
| exact 8+ | 60 | 4.00 | 3.09 | 1.44e-07 |
| dead | 342 | 2.49 | 2.16 | 9.82e-08 |
| at least 2+ | 4,725 | 3.15 | 2.72 | 1.10e-07 |
| at least 1 (open) | 11,862 | 3.07 | 2.65 | 1.16e-07 |
