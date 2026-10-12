# Lemma-aware SFT data `lemmas_v1`

Traced competition steps (sources goedel_lean_workbook_proofs, stp_lean_workbook, deepseek_prover_v1, lean_workbook, goedel_sft_v2, numinamath_lean_kimina, numinamath_lean_human, leanabell_sft), whole proofs in a fixed pseudo-random order up to an estimated 30,000,000 tokens with equal source shares. Each step draws its list length from [0, 4, 8, 16, 32]; for a non-empty list the retriever's top 32 candidates are checked on the replayed state as in the search (`exact {name}`, `apply {name}`, `rw [{name}]`, 10,000 heartbeats) and the best k by applicability, then score, are shown. With probability 0.5, premises the step names but retrieval missed replace low-ranked candidates. Replay failures (dropped): {'train': 11, 'validation': 0}.

## train

47,845 examples (2,263 over length dropped), 30,674,541 tokens; prompt mean 612, p90 1283, max 3937; completion mean 30.

| List length | Examples | Step names a premise | Named premise shown | Injected | Closing lines |
|---|---|---|---|---|---|
| 00 | 9,497 | 33.5% | 0.0% | 0.0% | 0.00 |
| 04 | 9,541 | 32.7% | 11.7% | 12.8% | 0.04 |
| 08 | 9,712 | 32.9% | 15.1% | 12.7% | 0.04 |
| 16 | 9,604 | 33.1% | 19.0% | 12.8% | 0.04 |
| 32 | 9,491 | 33.3% | 23.5% | 12.9% | 0.05 |

| Source | Examples | Step names a premise | Named premise shown | Injected | Closing lines |
|---|---|---|---|---|---|
| deepseek_prover_v1 | 8,927 | 15.0% | 5.5% | 5.0% | 0.04 |
| goedel_lean_workbook_proofs | 8,435 | 46.5% | 20.5% | 12.8% | 0.04 |
| goedel_sft_v2 | 4,475 | 34.1% | 14.3% | 12.5% | 0.02 |
| lean_workbook | 2,130 | 44.5% | 20.8% | 12.1% | 0.07 |
| leanabell_sft | 8,713 | 26.2% | 11.2% | 8.6% | 0.05 |
| numinamath_lean_kimina | 7,032 | 32.5% | 13.0% | 11.3% | 0.02 |
| stp_lean_workbook | 8,133 | 43.4% | 17.8% | 12.5% | 0.02 |

## validation

1,967 examples (34 over length dropped), 1,304,805 tokens; prompt mean 636, p90 1350, max 3745; completion mean 28.

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
