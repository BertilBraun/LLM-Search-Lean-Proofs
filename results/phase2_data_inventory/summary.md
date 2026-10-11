# Phase 2 data inventory

## Inventory (verified on hf-mirror.com, GitHub and Zenodo)

| Category | Dataset | Items | Fields | Lean / Mathlib | License | Full proofs | Decision |
|---|---|---|---|---|---|---|---|
| proofs | Goedel-LM/Lean-workbook-proofs | 29,750 proofs | problem_id, full_proof | Goedel-Prover environment: Lean v4.9.0-rc1 + Mathlib 2f65ba7f (DeepSeek-Prover-V1.5 fork) | MIT (LICENSE file) | yes (whole files) | selected |
| proofs | kfdong/STP_Lean_0320 | 3,262,558 rows; 809,535 distinct prompts (conjecture 2,751,225 / statement 404,412 / mathlib 106,921 rows) | prompt, target, weight, iteration, tag | STP setup script: Lean 4.9.0-rc1 + xinhjBrant/mathlib4 (DeepSeek fork) | MIT | yes (statement + tactic block) | selected (conjecture and statement tags; mathlib tag is conjecture-generation data) |
| proofs | kfdong/STP_Lean | 1,738,754 rows | prompt, target, weight, iteration, tag | as STP_Lean_0320 | MIT | yes | skipped (superseded by STP_Lean_0320) |
| proofs | kfdong/STP_Lean_SFT | 235,430 train + 4,096 eval | prompt, target | as STP; eval split is Mathlib file completion | not stated | yes | skipped (SFT warm-up mix, overlaps STP and Mathlib) |
| proofs | Goedel-LM/SFT_dataset_v2 | 1,745,010 chats | messages (proof plan + Lean code, self-correction rounds) | Goedel-Prover-V2: Lean 4.9 + Mathlib 2f65ba7f | apache-2.0 | yes (final lean4 code block of the last assistant turn) | selected |
| proofs | Goedel-LM/RL_dataset_V2 | 98,632 prompts | subset, messages | as Goedel-Prover-V2 | apache-2.0 | no (RL prompts) | skipped |
| proofs | deepseek-ai/DeepSeek-Prover-V1 | 27,503 proofs | name, split, formal_statement, goal, header, formal_proof | not stated | other (deepseek-license; LICENSE file in the repo is empty) | yes | selected |
| proofs + statements | internlm/Lean-Workbook | 140,214 statements (57,321 + 82,893 plus); 12,823 with 223,156 proofs; wkbk_1009: 25,214 one-step rows | natural_language_statement, answer, tags, formal_statement, split, proof[] | Lean v4.8.0-rc1 + Mathlib v4.8.0-rc1 | apache-2.0 | yes (tactic blocks, no header) | selected (proofs and statement pool; 6,229 disproved ids dropped) |
| proofs + statements | AI-MO/NuminaMath-LEAN | 104,155 statements; 31,634 Kimina-Prover proofs; 9,475 complete human proofs | uuid, problem, formal_statement, formal_ground_truth, ground_truth_type, formal_proof, rl_data, ... | Mathlib v4.15.0 (version mismatch) | apache-2.0 | yes | selected (proofs lowest priority; statement pool) |
| statements | AI-MO/Kimina-Prover-Promptset | 24,418 rows (7,228 distinct statements) | statement_id, natural_language, formal_statement, source, name | Mathlib v4.15.0 (derived from NuminaMath-LEAN) | apache-2.0 (README) | no | selected (statement pool) |
| statements | Goedel-LM/Goedel-Pset-v1 | 1,732,594 statements | problem_id, formal_statement, informal_statement | compiled with sorry in the Goedel-Prover environment (Lean 4.9) | MIT (LICENSE file) | no | selected (statement pool) |
| proofs | stoney0062/Leanabell-Prover-Traindata-SFT | 218,988 proofs | prompt, output | not stated (DeepSeek-Prover-V1.5 prompt format) | apache-2.0 | yes (with explanatory comments) | selected (low priority, provenance unclear) |
| proofs | FrenzyMath/Herald_proofs | 44,553 proofs | id, name, formal_theorem, informal_theorem, formal_proof, informal_proof, commented_proof, header | Lean v4.11.0 | apache-2.0 | yes | skipped (Mathlib-internal theorems with per-file headers and variables) |
| proofs | iiis-lean/NuminaMath-LEAN-Sol | 81,311 rows | NuminaMath-LEAN fields + NL solution | Mathlib v4.15.0 | apache-2.0 | yes | skipped (same proofs as NuminaMath-LEAN) |
| proofs | iiis-lean/lean-math-formal-corpus | 2,877 rows | benchmark statements and proofs | v4.9.0 / v4.15.0 / v4.27.0 configs | not stated | partly | excluded (contains miniF2F and other benchmarks) |
| proofs | LukeBailey181/minif2f_proofnet_lean_workbook_deepseek_prover_sols | small | solutions per benchmark split | not stated | not stated | yes | excluded (contains miniF2F solutions) |
| traced transitions | HyperCactus0/LeanTransitionCorpus | 14.8 GB, 51,134 files | state before/after, tactic, Syntax/Expr trees, premises, provenance | Mathlib 29dcec07 (sources: DeepSeek-Prover-V1, Goedel workbook, Numina, Mathlib, OProofs) | apache-2.0 (packaging) | per-step only | skipped (traced in a different environment; we trace ourselves) |
| traced transitions | banach1729/goedel-workbook-lean427 | 29,750 proofs, 60,341 tactic pairs | Lean files + tactic_pairs.jsonl | Lean v4.27.0 | apache-2.0 | yes | skipped (version mismatch) |
| mathlib | LeanDojo Benchmark 4 v10 (Zenodo 12740403) | 122,517 theorems (random and novel_premises splits 118,517/2,000/2,000), corpus.jsonl premises | traced_tactics (state_before, tactic, annotated premises, state_after), corpus premises and imports | Mathlib 29dcec07 (2024-07-01, lean4:v4.10.0-rc1); closest LeanDojo release to the pin | CC BY 2.0 | per-step only | selected (zenodo.org is reachable from the node) |
| mathlib | l3lab/ntp-mathlib | 307,049 examples (7.8 GB) | state, srcUpToTactic, nextTactic, declUpToTactic, declId, decl, file_tag | Mathlib cf8e23a6, lean4:v4.4.0 | not stated | per-step only | skipped (older Mathlib, no premise annotations) |
| mathlib | internlm/Lean-Github | 29k theorems from 100+ repositories | lean-github.parquet | mixed | apache-2.0 | per-step | skipped (not Mathlib premises) |
| mathlib | ScalableMath/Lean-STaR-base / Lean-STaR-plus | 82 MB / 62 MB JSON | state, thought, tactic | not stated | not stated (no dataset card) | per-step only | skipped |
| mathlib | mathlib-initiative/mathlib-tactics | 1M-10M tactic invocations | goal states and tactics (lean_scout) | Mathlib d13f23b7 (2026) | apache-2.0 | per-step only | skipped (version mismatch) |
| mathlib | FrenzyMath/state_tactic_pairs | 56,407 pairs | state, tactic | not stated (REAL-Prover) | apache-2.0 | per-step only | skipped (no premises) |

## Downloads (`$LEAN_SEARCH_DATA/raw`)

| Directory | Size (MB) |
|---|---|
| deepseek_prover_v1 | 20 |
| goedel_lean_workbook_proofs | 16 |
| goedel_pset_v1 | 828 |
| goedel_sft_v2 | 6,106 |
| kimina_prover_promptset | 4 |
| lean_workbook | 99 |
| leanabell_sft | 377 |
| leandojo_benchmark_4_v10 | 902 |
| minif2f | 0 |
| numinamath_lean | 78 |
| stp_lean_0320 | 1,741 |
| **total** | 10,172 |

## Proof corpora (`$LEAN_SEARCH_DATA/normalized/proofs`)

| Source | Raw | Rejected | Exact duplicates | Decontaminated proofs | Statements | Over cap (3) | Kept proofs | Pinned env |
|---|---|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 29,750 | 0 | 1,547 | 457 | 20,219 | 497 | 27,249 | yes |
| stp_lean_workbook | 404,412 | 60 | 6,831 | 8,830 | 23,951 | 317,615 | 71,076 | yes |
| stp_conjectures | 2,751,225 | 403 | 4,937 | 99,135 | 673,927 | 1,007,194 | 1,639,556 | yes |
| goedel_sft_v2 | 1,744,769 | 5,172 | 380,246 | 13,931 | 902,374 | 76,424 | 1,268,996 | yes |
| deepseek_prover_v1 | 27,503 | 0 | 0 | 313 | 27,190 | 0 | 27,190 | no |
| lean_workbook | 222,904 | 559 | 17,089 | 3,748 | 8,898 | 176,377 | 25,131 | no |
| leanabell_sft | 218,988 | 17 | 5,209 | 3,306 | 179,209 | 4,777 | 205,679 | no |
| numinamath_lean_kimina | 31,634 | 13 | 58 | 545 | 29,573 | 199 | 30,819 | no |
| numinamath_lean_human | 9,475 | 102 | 42 | 217 | 9,060 | 0 | 9,114 | no |

Merged across sources (priority goedel_lean_workbook_proofs > stp_lean_workbook > stp_conjectures > goedel_sft_v2 > deepseek_prover_v1 > lean_workbook > leanabell_sft > numinamath_lean_kimina > numinamath_lean_human, at most 3 distinct proofs per statement): **2,943,274 proofs of 1,502,558 statements**.

Selected for tracing (`proofs/selected_for_tracing.jsonl`, budget 300,000): every merged proof from the non-sampled sources, then one proof each for further statements of the sampled sources in hash order until the budget is reached: **300,000 proofs of 246,606 statements** (goedel_lean_workbook_proofs: 27,249, stp_lean_workbook: 47,138, lean_workbook: 1,516, numinamath_lean_kimina: 30,171, numinamath_lean_human: 8,762, deepseek_prover_v1: 27,187, goedel_sft_v2: 64,834, stp_conjectures: 75,579, leanabell_sft: 17,564).

Rejection reasons per source:

- goedel_lean_workbook_proofs: none
- stp_lean_workbook: no_assignment: 1, no_declaration: 16, sorry_or_admit: 12, term_mode: 31
- stp_conjectures: no_assignment: 75, sorry_or_admit: 39, term_mode: 289
- goedel_sft_v2: declares_axiom: 20, empty_proof: 2, no_assignment: 712, no_declaration: 352, sorry_or_admit: 3,600, term_mode: 24, too_long: 294, unbalanced_brackets: 168
- deepseek_prover_v1: none
- lean_workbook: no_assignment: 559
- leanabell_sft: empty_proof: 1, no_assignment: 10, term_mode: 6
- numinamath_lean_kimina: declares_axiom: 1, no_declaration: 1, sorry_or_admit: 9, term_mode: 2
- numinamath_lean_human: sorry_or_admit: 26, term_mode: 55, too_long: 21

### Proof length (kept proofs)

| Source | Proofs | Mean top-level tactics | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 27,249 | 2.97 | 2 | 7 | 13 | 102 |
| stp_lean_workbook | 71,076 | 4.06 | 3 | 9 | 14 | 82 |
| stp_conjectures | 1,639,556 | 5.88 | 5 | 10 | 19 | 80 |
| goedel_sft_v2 | 1,268,996 | 4.08 | 3 | 7 | 14 | 201 |
| deepseek_prover_v1 | 27,190 | 2.31 | 2 | 3 | 5 | 27 |
| lean_workbook | 25,131 | 2.29 | 2 | 4 | 7 | 19 |
| leanabell_sft | 205,679 | 3.32 | 2 | 7 | 14 | 114 |
| numinamath_lean_kimina | 30,819 | 5.39 | 4 | 11 | 20 | 65 |
| numinamath_lean_human | 9,114 | 8.62 | 5 | 19 | 44 | 325 |
| merged | 2,943,274 | 5.01 | 4 | 9 | 17 | 325 |
| selected for tracing | 300,000 | 4.47 | 3 | 9 | 17 | 325 |

| Source | Proofs | Mean characters | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 27,249 | 224.8 | 174 | 449 | 1019 | 3,071 |
| stp_lean_workbook | 71,076 | 291.35 | 241 | 594 | 1066 | 2,015 |
| stp_conjectures | 1,639,556 | 503.8 | 458 | 915 | 1383 | 3,683 |
| goedel_sft_v2 | 1,268,996 | 2070.19 | 1611 | 4152 | 8350 | 19,989 |
| deepseek_prover_v1 | 27,190 | 45.69 | 40 | 73 | 139 | 709 |
| lean_workbook | 25,131 | 62.49 | 55 | 105 | 195 | 1,488 |
| leanabell_sft | 205,679 | 170.28 | 113 | 370 | 922 | 4,477 |
| numinamath_lean_kimina | 30,819 | 920.06 | 639 | 2169 | 4289 | 12,479 |
| numinamath_lean_human | 9,114 | 1810.91 | 1028 | 4564 | 10831 | 19,837 |
| merged | 2,943,274 | 1007.95 | 578 | 2420 | 6492 | 19,989 |
| selected for tracing | 300,000 | 777.96 | 392 | 1925 | 5950 | 19,989 |

Top-level tactic histograms:

- goedel_lean_workbook_proofs: 1: 10,581, 2: 5,896, 3: 3,388, 4-5: 3,581, 6-10: 3,144, 11-20: 630, 21-50: 25, 51+: 4
- stp_lean_workbook: 1: 14,126, 2: 15,135, 3: 11,082, 4-5: 12,484, 6-10: 15,037, 11-20: 3,169, 21-50: 39, 51+: 4
- stp_conjectures: 1: 82,427, 2: 167,683, 3: 215,146, 4-5: 427,399, 6-10: 590,370, 11-20: 143,610, 21-50: 12,851, 51+: 70
- goedel_sft_v2: 1: 390, 2: 354,843, 3: 373,535, 4-5: 299,846, 6-10: 195,572, 11-20: 43,623, 21-50: 1,172, 51+: 15
- deepseek_prover_v1: 1: 4,542, 2: 12,906, 3: 7,625, 4-5: 1,917, 6-10: 197, 11-20: 2, 21-50: 1, 51+: 0
- lean_workbook: 1: 7,412, 2: 9,772, 3: 4,466, 4-5: 2,777, 6-10: 650, 11-20: 54, 21-50: 0, 51+: 0
- leanabell_sft: 1: 49,739, 2: 56,071, 3: 35,305, 4-5: 35,542, 6-10: 23,399, 11-20: 4,966, 21-50: 560, 51+: 97
- numinamath_lean_kimina: 1: 3,286, 2: 1,868, 3: 7,519, 4-5: 7,505, 6-10: 7,510, 11-20: 2,858, 21-50: 268, 51+: 5
- numinamath_lean_human: 1: 935, 2: 486, 3: 1,401, 4-5: 1,788, 6-10: 2,087, 11-20: 1,667, 21-50: 679, 51+: 71
- merged: 1: 144,512, 2: 520,317, 3: 584,607, 4-5: 722,837, 6-10: 772,608, 11-20: 182,939, 21-50: 15,199, 51+: 255
- selected for tracing: 1: 35,489, 2: 61,675, 3: 61,822, 4-5: 61,817, 6-10: 61,464, 11-20: 15,979, 21-50: 1,660, 51+: 94

## Statement pools (`$LEAN_SEARCH_DATA/normalized/statements`)

| Pool | Raw | Rejected | Duplicates | Decontaminated | Kept |
|---|---|---|---|---|---|
| lean_workbook | 137,131 | 323 | 37,810 | 791 | 98,207 |
| goedel_pset_v1 | 1,732,594 | 1,457 | 86,630 | 20,188 | 1,624,319 |
| numinamath_lean | 104,155 | 1,092 | 5,070 | 918 | 97,075 |
| kimina_prover_promptset | 24,418 | 111 | 16,924 | 63 | 7,320 |

Merged pool (`statements/merged.jsonl`, deduplicated across pools): **1,822,234**.

## Decontamination against miniF2F (valid: 244, test: 244 problems)

A statement is removed (with all its proofs) when any rule fires against any miniF2F problem:

1. `exact`: identical token sequence after stripping comments, the declaration keyword and name, and the `:= by ...` suffix.
2. `name`: the theorem is named after a miniF2F problem, possibly with a non-digit suffix (`amc12a_2021_p12_6`). Most such hits in STP conjectures and Goedel SFT v2 reuse the benchmark name for unrelated content (formal similarity below 0.1); they are removed anyway so that no training statement carries a miniF2F problem name.
3. `formal_ngram`: Jaccard similarity of token 5-grams ≥ 0.35, after renaming bound variables to `v0, v1, ...` in order of appearance and collapsing every hypothesis name (`h...`) to `h`.
4. `shared_conclusion`: identical anonymized conclusion of at least 5 tokens and 5-gram Jaccard ≥ 0.25.
5. `informal_ngram`: Jaccard of lower-cased word 4-grams of the informal statement ≥ 0.2 (where a source has one; miniF2F's `Show that it is ...` suffix is ignored).
6. `propagated`: the same canonical statement was removed from a statement pool by rules 1-5.

Thresholds come from reading samples per similarity band: formal 5-gram scores of 0.30-0.35 were unrelated statements sharing binder boilerplate; 0.35-0.40 were mostly unrelated but included reformulated miniF2F problems (e.g. `∀ x > 0, ∀ y > 0` against `∀ x y, 0 < x → 0 < y →`); 0.40-0.50 were about half reformulations or variants; everything above 0.6 was a copy. Equal conclusions recover reformulated hypotheses down to 0.25 (e.g. `imo_1964_p2` with triangle inequalities written as `a + b > c`). Informal 4-gram scores of 0.20-0.25 still contained the same competition problem (e.g. `imo_1982_p1`), next to false positives from formula-heavy texts. We accept those false positives in exchange for recall.

| Source | exact | name | formal_ngram | shared_conclusion | informal_ngram | propagated |
|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs (statements) | 2 | 0 | 157 | 2 | 124 | 11 |
| stp_lean_workbook (statements) | 175 | 21 | 170 | 2 | 0 | 149 |
| stp_conjectures (statements) | 3 | 12,413 | 12,352 | 11 | 0 | 1 |
| goedel_sft_v2 (statements) | 5 | 3,533 | 5,772 | 27 | 0 | 709 |
| deepseek_prover_v1 (statements) | 0 | 0 | 307 | 5 | 0 | 1 |
| lean_workbook (statements) | 1 | 0 | 89 | 2 | 45 | 7 |
| leanabell_sft (statements) | 111 | 163 | 1,023 | 25 | 1,270 | 35 |
| numinamath_lean_kimina (statements) | 7 | 0 | 173 | 8 | 282 | 10 |
| numinamath_lean_human (statements) | 6 | 0 | 67 | 3 | 135 | 2 |
| lean_workbook (pool) | 4 | 0 | 376 | 5 | 393 | 13 |
| goedel_pset_v1 (pool) | 19 | 0 | 14,155 | 182 | 5,820 | 12 |
| numinamath_lean (pool) | 12 | 0 | 340 | 13 | 543 | 10 |
| kimina_prover_promptset (pool) | 1 | 0 | 33 | 0 | 25 | 4 |

Removed statements are listed in `normalized/decontamination/{proofs,statements}_<source>.jsonl`; every statement with formal similarity ≥ 0.3 or informal similarity ≥ 0.18 is listed in `normalized/decontamination/near_misses.jsonl` for review.

## Mathlib state/tactic/premise data (leandojo_benchmark_4_v10)

| Split | Tactic examples | With premise annotations |
|---|---|---|
| random/train | 250,814 | 162,262 |
| random/val | 4,260 | 2,681 |
| random/test | 4,506 | 2,836 |
| novel_premises/train | 246,714 | 159,234 |
| novel_premises/val | 6,240 | 4,165 |
| novel_premises/test | 6,626 | 4,380 |

Premises: 180,973 in 5,674 files (`mathlib/premises.jsonl`).

## Normalized schema (`lean_search.corpora.records`)

- `ProofRecord` (proofs/<source>.jsonl, proofs/selected_for_tracing.jsonl): `source`, `identifier`, `statement_identifier`, `header`, `formal_statement`, `tactic_proof`, `lean_version_hint`, `distinct_proofs_for_statement`
- `StatementRecord` (statements/<pool>.jsonl, statements/merged.jsonl): `source`, `identifier`, `header`, `formal_statement`, `informal_statement`, `lean_version_hint`
- `TacticExample` (mathlib/tactics_<split strategy>_<split>.jsonl): `source`, `identifier`, `split`, `file_path`, `theorem_full_name`, `theorem_start_line`, `tactic_index`, `state_before`, `tactic`, `annotated_tactic`, `state_after`, `premises`
- `PremiseReference` (nested in TacticExample.premises): `full_name`, `definition_path`
- `PremiseRecord` (mathlib/premises.jsonl): `source`, `full_name`, `file_path`, `start_line`, `kind`, `code`
- `FileImports` (mathlib/file_imports.jsonl): `source`, `file_path`, `imports`

`formal_statement` runs from the declaration keyword to `:= by`; `tactic_proof` is the dedented tactic block after it, comments removed; `ProofRecord.top_level_tactics()` splits it at the block's own column (a line-based heuristic: continuation lines, bullets, `<;>` chains and `calc` steps stay with their tactic). A tracer runs `header`, opens `formal_statement` with `sorry` to get the initial state, then replays the tactics one at a time.

## Normalized output sizes

| File | Size (MB) |
|---|---|
| decontamination/near_misses.jsonl | 55.1 |
| decontamination/proofs_deepseek_prover_v1.jsonl | 0.1 |
| decontamination/proofs_goedel_lean_workbook_proofs.jsonl | 0.1 |
| decontamination/proofs_goedel_sft_v2.jsonl | 4.0 |
| decontamination/proofs_lean_workbook.jsonl | 0.1 |
| decontamination/proofs_leanabell_sft.jsonl | 0.9 |
| decontamination/proofs_numinamath_lean_human.jsonl | 0.1 |
| decontamination/proofs_numinamath_lean_kimina.jsonl | 0.2 |
| decontamination/proofs_stp_conjectures.jsonl | 10.0 |
| decontamination/proofs_stp_lean_workbook.jsonl | 0.2 |
| decontamination/statements_goedel_pset_v1.jsonl | 7.6 |
| decontamination/statements_kimina_prover_promptset.jsonl | 0.0 |
| decontamination/statements_lean_workbook.jsonl | 0.3 |
| decontamination/statements_numinamath_lean.jsonl | 0.4 |
| mathlib/file_imports.jsonl | 1.9 |
| mathlib/premises.jsonl | 69.4 |
| mathlib/tactics_novel_premises_test.jsonl | 11.1 |
| mathlib/tactics_novel_premises_train.jsonl | 345.9 |
| mathlib/tactics_novel_premises_val.jsonl | 10.0 |
| mathlib/tactics_random_test.jsonl | 6.7 |
| mathlib/tactics_random_train.jsonl | 352.1 |
| mathlib/tactics_random_val.jsonl | 6.1 |
| proofs/deepseek_prover_v1.jsonl | 18.8 |
| proofs/goedel_lean_workbook_proofs.jsonl | 22.2 |
| proofs/goedel_sft_v2.jsonl | 3,699.7 |
| proofs/lean_workbook.jsonl | 14.4 |
| proofs/leanabell_sft.jsonl | 148.1 |
| proofs/numinamath_lean_human.jsonl | 24.0 |
| proofs/numinamath_lean_kimina.jsonl | 44.9 |
| proofs/selected_for_tracing.jsonl | 433.7 |
| proofs/stp_conjectures.jsonl | 1,872.7 |
| proofs/stp_lean_workbook.jsonl | 63.2 |
| statements/goedel_pset_v1.jsonl | 1,428.8 |
| statements/kimina_prover_promptset.jsonl | 4.3 |
| statements/lean_workbook.jsonl | 61.4 |
| statements/merged.jsonl | 1,555.2 |
| statements/numinamath_lean.jsonl | 63.6 |

## Lean version notes

- Our pin (lean/lean-toolchain) is Lean v4.9.0-rc1 with Mathlib d1d1e4b7 (2024-06-12), the upstream parent of the DeepSeek-Prover-V1.5 Mathlib fork commit 2f65ba7f, which Goedel-Prover (V1 and V2) and STP also pin.
- Goedel workbook proofs, STP_Lean_0320 and Goedel SFT v2 come from provers run in that environment.
- Lean Workbook proofs were found under Lean v4.8.0-rc1, one release older than the pin.
- DeepSeek-Prover-V1 and Leanabell do not state their Lean version.
- NuminaMath-LEAN and the Kimina prompt set target Mathlib v4.15.0, six Lean releases newer than the pin; their replay rate is unknown until they are traced.
- LeanDojo Benchmark 4 v10 traces Mathlib 29dcec07 (2024-07-01, Lean v4.10.0-rc1), 19 days newer than the pinned Mathlib; premises added in that window do not exist in our environment.
- Every proof is replayed in the pinned environment during tracing, so version drift costs coverage, not correctness.
