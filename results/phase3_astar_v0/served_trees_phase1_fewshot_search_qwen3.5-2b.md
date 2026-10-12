# Served value adapter `value-v0` on `trees_phase1_fewshot_search_qwen3.5-2b`

Scored through vLLM (1 server(s)) and read out as the search does: top-k logprobs renormalized over the nine bin tokens, h = Σ p_k·steps_k.

| Quantity | Value |
|---|---|
| States | 13,661 |
| Bin accuracy (exact and dead labels) | 8.0% |
| MAE of expected steps given alive (exact labels) | 2.493 |
| Spearman of h with exact remaining steps | 0.394 |
| Dead AUC of p_dead (dead vs exact) | 0.687 |
| Mean P(at least n or dead) on censored labels | 0.837 |
| Mean h / mean p_dead | 2.62 / 1.37e-07 |
| Bin tokens outside the top-k per request | 1.00 |
| Prompts too long | 0 |
| States/s | 41 |
| Mean request seconds | 3.120 |
| Prompt cache hit rate | 0.6% |

## By label

| Label | States | Mean h | Median h | Mean p_dead |
|---|---|---|---|---|
| exact 1 | 115 | 1.84 | 1.61 | 6.23e-08 |
| exact 2 | 42 | 2.99 | 2.66 | 1.03e-07 |
| exact 3 | 27 | 3.07 | 2.72 | 1.05e-07 |
| exact 4 | 15 | 2.94 | 2.41 | 1.13e-07 |
| exact 5 | 11 | 2.55 | 2.16 | 1.02e-07 |
| exact 6 | 10 | 2.50 | 2.09 | 1.07e-07 |
| exact 7 | 7 | 2.67 | 1.93 | 1.41e-07 |
| exact 8+ | 39 | 2.43 | 2.15 | 1.04e-07 |
| dead | 1,140 | 2.81 | 2.46 | 1.27e-07 |
| at least 2+ | 4,761 | 2.67 | 2.43 | 1.40e-07 |
| at least 1 (open) | 7,494 | 2.56 | 2.34 | 1.39e-07 |
