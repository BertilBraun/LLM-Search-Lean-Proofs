# Expert-iteration statement pool `pool_v1`

Finalized 2026-10-12T05:37:26+00:00 (git 821b0c7d85). Candidates: per source the first statements of a seeded hash order (seed `expert-iteration-pool-v1`) of `normalized/statements/merged.jsonl` (decontaminated against miniF2F), leaving out statements with a proof in `normalized/proofs/selected_for_tracing.jsonl` (the policy was trained on them; exclusion is checked only for statements that could still be selected), interleaved so that every prefix holds the sources in proportion. 19,912 headers had `import Mathlib` alone and now also import Aesop (Mathlib imports it), so every REPL process imports Mathlib once.

| Source | Available | Excluded / checked | Quota | Selected |
|---|---|---|---|---|
| lean_workbook | 98,207 | 20,733 / 70,194 | 16,000 | 16,000 |
| numinamath_lean | 95,394 | 29,594 / 76,806 | 16,000 | 16,000 |
| kimina_prover_promptset | 5,640 | 9 / 5,640 | 4,000 | 4,000 |
| goedel_pset_v1 | 1,622,993 | 2,040 / 171,019 | 24,000 | 24,000 |

## Load check and automation pre-filter

Each candidate is searched with the automation sweep only (`experiments/configs/expert_iteration/prefilter_search.toml`: at most 8 expansions, 60 s, 24 REPLs); a failed start is a load failure. Prepared = loaded and not solved by automation: the rounds search these. The longest prefix of candidates that all have a result is classified (5,679 of 59,998).

| Source | Candidates | Processed | Load failures | Solved by automation (of loaded) | Prepared |
|---|---|---|---|---|---|
| lean_workbook | 16,000 | 1,514 | 60 (4.0%) | 0 (0.0%) | 1,454 |
| numinamath_lean | 15,998 | 1,514 | 5 (0.3%) | 3 (0.2%) | 1,506 |
| kimina_prover_promptset | 4,000 | 379 | 1 (0.3%) | 51 (13.5%) | 327 |
| goedel_pset_v1 | 24,000 | 2,272 | 36 (1.6%) | 782 (35.0%) | 1,454 |
| all | 59,998 | 5,679 | 102 (1.8%) | 836 (15.0%) | 4,741 |

Cost: 17.8 s wall per statement (p90 50.9 s), 17.5 Lean s, 5.1 expansions; 2,701 statements per hour over 0.45 h of finished pre-filter runs (alongside the tracing job).

## Load failures by first error line

| Source | Category | Statements |
|---|---|---|
| lean_workbook | ambiguous, possible interpretations  | 55 |
| lean_workbook | unexpected token '…'; expected '…' | 3 |
| lean_workbook | unexpected token '…'; expected '…' or identifier | 2 |
| numinamath_lean | invalid field notation, function '…' does not have argument with type (Multiset  | 2 |
| numinamath_lean | invalid field notation, function '…' does not have argument with type (MvPolynom | 1 |
| numinamath_lean | Expected exactly one sorry in the statement, found 2. | 1 |
| numinamath_lean | failed to synthesize | 1 |
| kimina_prover_promptset | failed to synthesize | 1 |
| goedel_pset_v1 | The header does not elaborate: ('…', '…', '…') | 4 |
| goedel_pset_v1 | The header does not elaborate: ("tactic '…' failed, did not find instance of the | 4 |
| goedel_pset_v1 | The header does not elaborate: ("unknown identifier '…'", "tactic '…' failed, eq | 3 |
| goedel_pset_v1 | The header does not elaborate: ('…',) | 3 |
| goedel_pset_v1 | The header does not elaborate: ('…', '…') | 3 |
| goedel_pset_v1 | The header does not elaborate: ('…', '…', '…', '…', '…') | 2 |
| goedel_pset_v1 | The header does not elaborate: ("unknown constant '…'", "unknown constant '…'",  | 2 |
| goedel_pset_v1 | The header does not elaborate: ("unknown identifier '…'", "unknown identifier '… | 2 |
| goedel_pset_v1 | The header does not elaborate: ('…', '…', "tactic '…' failed\ncase «0»\nn : ℕ\nh | 1 |
| goedel_pset_v1 | The header does not elaborate: ('…', '…', '…', '…', '…', '…', "'…' tactic failed | 1 |
| goedel_pset_v1 | The header does not elaborate: ('…', "unknown constant '…'", "unknown constant ' | 1 |
| goedel_pset_v1 | The header does not elaborate: ("expected '…' or indented tactic sequence", '…', | 1 |
