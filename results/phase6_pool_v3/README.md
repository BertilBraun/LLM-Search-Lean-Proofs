# Pool v3: statements with known proofs

Normalized (decontaminated) proof corpora grouped by canonical statement; statements whose proofs were selected for tracing (every training set derives from those) are excluded. Candidates are ordered easiest first by their shortest proof (top-level tactics, then characters).

## Corpora

| Corpus | Pooled | Proofs | Statements | New statements | Excluded statements |
|---|---|---|---|---|---|
| lean_workbook | yes | 0 | 0 | 0 | 8,898 |
| goedel_lean_workbook_proofs | yes | 0 | 0 | 0 | 20,219 |
| stp_lean_workbook | yes | 0 | 0 | 0 | 23,951 |
| deepseek_prover_v1 | yes | 1 | 1 | 1 | 27,189 |
| numinamath_lean_human | yes | 39 | 37 | 37 | 9,023 |
| numinamath_lean_kimina | yes | 227 | 176 | 147 | 29,397 |
| leanabell_sft | yes | 143,879 | 140,405 | 140,321 | 38,804 |
| goedel_sft_v2 | yes | 1,109,550 | 790,367 | 789,233 | 112,007 |
| stp_conjectures | counted only | 1,455,157 | 598,180 | 326,213 | 75,747 |

## Near duplicates and negations

MinHash/LSH over normalized token 5-grams; one statement per cluster at estimated Jaccard >= 0.7 (sample pairs per similarity bin in dedup.json), the easiest kept; then proved negations of conjectures dropped. 929,739 -> 748,119 statements.

| Source | Before | Distinct | Without negations |
|---|---|---|---|
| deepseek_prover_v1 | 1 | 1 | 1 |
| goedel_sft_v2 | 789,233 | 701,832 | 615,832 |
| leanabell_sft | 140,321 | 132,300 | 132,143 |
| numinamath_lean_human | 37 | 28 | 28 |
| numinamath_lean_kimina | 147 | 115 | 115 |

## Candidates (929,739 before deduplication)

Each statement once, under the source of its shortest proof.

| Source | Candidates | Median shortest proof (tactics) |
|---|---|---|
| deepseek_prover_v1 | 1 | 2 |
| goedel_sft_v2 | 789,622 | 3 |
| leanabell_sft | 140,051 | 3 |
| numinamath_lean_human | 13 | 1 |
| numinamath_lean_kimina | 52 | 1 |

## Verification sample (seeded random candidates)

| Source | Attempted | Verified | Automation-trivial | Load failures | Usable | Median tactics | s |
|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 1,326 | 1,209 (91%) | 74 | 0 | 1,135 | 3 | 16.5 |
| leanabell_sft | 272 | 266 (98%) | 95 | 0 | 171 | 3 | 5.6 |
| numinamath_lean_kimina | 2 | 2 (100%) | 1 | 0 | 1 | 1 | 10.2 |

## Verified for the curriculum (easiest first)

| Source | Attempted | Verified | Automation-trivial | Load failures | Usable | Median tactics | s |
|---|---|---|---|---|---|---|---|

## Most common first failure

| Failure | Statements |
|---|---|
| Verification exceeded the wall-clock limit. | 79 |
| linarith failed to find a contradiction | 13 |
| unsolved goals | 9 |
| omega could not prove the goal: | 4 |
| tactic 'rewrite' failed, did not find instance of the pattern in the target expression | 3 |
| The rfl tactic failed. Possible reasons: | 2 |
| type mismatch | 2 |
| tactic 'assumption' failed | 2 |
| maximum recursion depth has been reached | 2 |
| invalid argument, variable is not a proposition or let-declaration | 1 |
