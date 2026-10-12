# Served value adapter `value-v0` on `validation_v0`

Scored through vLLM (1 server(s)) and read out as the search does: top-k logprobs renormalized over the nine bin tokens, h = Σ p_k·steps_k.

| Quantity | Value |
|---|---|
| States | 2,566 |
| Bin accuracy (exact and dead labels) | 52.8% |
| MAE of expected steps given alive (exact labels) | 1.263 |
| Spearman of h with exact remaining steps | 0.798 |
| Dead AUC of p_dead (dead vs exact) | – |
| Mean P(at least n or dead) on censored labels | – |
| Mean h / mean p_dead | 3.36 / 9.99e-08 |
| Bin tokens outside the top-k per request | 1.00 |
| Prompts too long | 0 |
| States/s | 70 |
| Mean request seconds | 1.778 |
| Prompt cache hit rate | 0.6% |

## By label

| Label | States | Mean h | Median h | Mean p_dead |
|---|---|---|---|---|
| exact 1 | 794 | 1.67 | 1.39 | 5.84e-08 |
| exact 2 | 535 | 2.48 | 2.18 | 8.58e-08 |
| exact 3 | 356 | 3.37 | 3.02 | 1.17e-07 |
| exact 4 | 243 | 4.08 | 3.86 | 1.33e-07 |
| exact 5 | 187 | 4.72 | 4.48 | 1.48e-07 |
| exact 6 | 142 | 5.30 | 5.19 | 1.54e-07 |
| exact 7 | 102 | 5.92 | 5.82 | 1.42e-07 |
| exact 8+ | 207 | 7.47 | 7.46 | 1.26e-07 |
