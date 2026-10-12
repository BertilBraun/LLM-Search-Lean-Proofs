# Served value adapter `value-v0` on `trees_phase2_sft_v1_search`

Scored through vLLM (2 server(s)) and read out as the search does: top-k logprobs renormalized over the nine bin tokens, h = Σ p_k·steps_k.

| Quantity | Value |
|---|---|
| States | 18,433 |
| Bin accuracy (exact and dead labels) | 19.9% |
| MAE of expected steps given alive (exact labels) | 2.173 |
| Spearman of h with exact remaining steps | 0.554 |
| Dead AUC of p_dead (dead vs exact) | 0.441 |
| Mean P(at least n or dead) on censored labels | 0.913 |
| Mean h / mean p_dead | 3.13 / 1.15e-07 |
| Bin tokens outside the top-k per request | 1.00 |
| Prompts too long | 0 |
| States/s | 104 |
| Mean request seconds | 1.223 |
| Prompt cache hit rate | 6.4% |

## By label

| Label | States | Mean h | Median h | Mean p_dead |
|---|---|---|---|---|
| exact 1 | 148 | 1.85 | 1.68 | 6.66e-08 |
| exact 2 | 69 | 2.89 | 2.63 | 1.11e-07 |
| exact 3 | 45 | 3.10 | 2.62 | 1.12e-07 |
| exact 4 | 35 | 3.57 | 3.06 | 1.24e-07 |
| exact 5 | 19 | 4.03 | 3.22 | 1.13e-07 |
| exact 6 | 14 | 3.99 | 2.98 | 1.23e-07 |
| exact 7 | 11 | 3.44 | 2.88 | 1.20e-07 |
| exact 8+ | 52 | 4.01 | 3.27 | 1.27e-07 |
| dead | 397 | 2.11 | 1.74 | 8.81e-08 |
| at least 2+ | 5,031 | 3.15 | 2.78 | 1.13e-07 |
| at least 1 (open) | 12,612 | 3.17 | 2.70 | 1.17e-07 |
