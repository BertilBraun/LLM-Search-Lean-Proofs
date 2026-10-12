# Lemma-aware SFT data `lemmas_v1_15m`

Traced competition steps (sources goedel_lean_workbook_proofs, stp_lean_workbook, deepseek_prover_v1, lean_workbook, goedel_sft_v2, numinamath_lean_kimina, numinamath_lean_human, leanabell_sft), whole proofs in a fixed pseudo-random order up to an estimated 30,000,000 tokens with equal source shares. Each step draws its list length from [0, 4, 8, 16, 32]; for a non-empty list the retriever's top 32 candidates are checked on the replayed state as in the search (`exact {name}`, `apply {name}`, `rw [{name}]`, 10,000 heartbeats) and the best k by applicability, then score, are shown. With probability 0.5, premises the step names but retrieval missed replace low-ranked candidates. Replay failures (dropped): {}.

This set subsamples the training split of `lemmas_v1` to about 15,000,000 tokens: examples in a fixed pseudo-random order, each list length keeping its share of the tokens. The validation split is the same.

## train

23,425 examples (0 over length dropped), 15,001,404 tokens; prompt mean 611, p90 1285, max 3937; completion mean 29.

| List length | Examples | Step names a premise | Named premise shown | Injected | Closing lines |
|---|---|---|---|---|---|
| 00 | 4,671 | 33.2% | 0.0% | 0.0% | 0.00 |
| 04 | 4,668 | 32.8% | 11.7% | 12.8% | 0.04 |
| 08 | 4,755 | 33.0% | 15.0% | 12.7% | 0.04 |
| 16 | 4,705 | 32.9% | 19.1% | 12.7% | 0.04 |
| 32 | 4,626 | 33.4% | 23.7% | 12.8% | 0.04 |

| Source | Examples | Step names a premise | Named premise shown | Injected | Closing lines |
|---|---|---|---|---|---|
| deepseek_prover_v1 | 4,388 | 15.0% | 5.6% | 4.9% | 0.03 |
| goedel_lean_workbook_proofs | 4,128 | 46.2% | 20.2% | 11.9% | 0.04 |
| goedel_sft_v2 | 2,190 | 34.1% | 13.7% | 12.5% | 0.02 |
| lean_workbook | 1,059 | 44.2% | 20.2% | 12.1% | 0.08 |
| leanabell_sft | 4,327 | 26.0% | 10.9% | 8.8% | 0.05 |
| numinamath_lean_kimina | 3,406 | 33.0% | 13.7% | 11.3% | 0.02 |
| stp_lean_workbook | 3,927 | 43.5% | 18.2% | 13.0% | 0.02 |

## validation

1,967 examples (0 over length dropped), 1,304,805 tokens; prompt mean 636, p90 1350, max 3745; completion mean 28.

| List length | Examples | Step names a premise | Named premise shown | Injected | Closing lines |
|---|---|---|---|---|---|
| 00 | 396 | 40.7% | 0.0% | 0.0% | 0.00 |
| 04 | 384 | 35.9% | 9.6% | 11.2% | 0.03 |
| 08 | 362 | 37.3% | 15.2% | 15.7% | 0.03 |
| 16 | 405 | 39.3% | 24.7% | 14.3% | 0.06 |
| 32 | 420 | 38.6% | 27.9% | 14.5% | 0.04 |

| Source | Examples | Step names a premise | Named premise shown | Injected | Closing lines |
|---|---|---|---|---|---|
| deepseek_prover_v1 | 280 | 18.9% | 9.3% | 8.2% | 0.04 |
| goedel_lean_workbook_proofs | 373 | 42.9% | 18.5% | 10.5% | 0.05 |
| goedel_sft_v2 | 58 | 31.0% | 8.6% | 12.1% | 0.00 |
| lean_workbook | 10 | 60.0% | 30.0% | 10.0% | 0.10 |
| leanabell_sft | 236 | 24.6% | 10.2% | 7.6% | 0.01 |
| numinamath_lean_kimina | 26 | 7.7% | 3.8% | 3.8% | 0.00 |
| stp_lean_workbook | 984 | 46.5% | 18.4% | 13.2% | 0.03 |
