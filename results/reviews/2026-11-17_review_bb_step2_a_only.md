# Review BB: step 2 shrunk to arm A's learning rate

Branch `step2-a-only`, head 4a0b192: 3 commits on fdf6161 (91b6e3f, cb0251b, 4a0b192). Read against
`results/followup_progress.md`, "Decisions and open points (owner, 2026-11-17)", and DESIGN.md "Follow-up study:
controlled arms". This follows review AV of the larger first version.

Checks run:
- In WSL, against the worktree's `src`: `test_learning_rate_step`, `test_learning_rate_report`, `test_study_commands`,
  `test_study_chain_script`, `test_rate_ranking` and `test_followup_arms`. 245 passed.
- `ruff check` and `ruff format --check` over `src`, `experiments` and `tests/rl`: clean.
- No node access, as asked.

**Verdict: merge after fixes.** Nothing in the code blocks. The three rounds now match arm A's phase 1 more closely
than the old slice-4 plan did. The configs and the ranking are right. What needs fixing:
- the report does not state C's and D's rate itself (S2);
- the step's place in the node's order is not written down, and the efficiency branch interacts with it (S1);
- DESIGN's Arms section still describes the old plan (S3).

## Blocking

None.

## Should fix

**S1. The step's place in the node's order is not written down, and the efficiency branch changes the modes the step
pins.**
`results/followup_node_operations.md:312-319` ("Install and start"); `deployment/study_chain.sh` (mode); the arm
binding in `experiments/followup_arm.py` (`sampling.json`).
- Step 2 samples in the arms' final mode and pins it twice: the mode file plus the search config's sha256 in
  `mode.recorded.txt`, and `sampling.json`, against which every arm is checked. Since the owner's decisions of
  2026-11-17, that mode is not known until O2's probe gate has run (O2 against v35 decides reasoning or not).
- The search-efficiency branch (`worktree-agent-a884d29b93192b24f`, under review) repoints both mode files from
  `search/visible_student_v2.toml` and `search/no_reasoning_student_v2.toml` to new `*_sampling.toml` configs, which
  carry the result cache, timeout skip, warm spares and bounded `nlinarith`. The owner wants these in the arms'
  training sampling.
- Failure scenario: step 2 runs before that branch is merged and before O2's gate. Arms A, C and D are then refused
  by the sampling binding: other path, other sha256. Step 2's shared phase has to be sampled again, along with the
  rounds and held-out runs that depend on it.
- Second scenario: the operator works around the refusal by pointing an arm at the old mode. The arms then sample
  without the switches the owner asked for. And step 2's rate was chosen on trees sampled with a different `nlinarith`
  than A's phase 1 sees, which matters for valid-tactic labels.
- Related, to settle on the efficiency branch: step 2's held-out runs use the shared run's loop config
  (`--loop-config ${shared_loop_config}`), and the arms' in-loop held-out runs use the arm's loop config. Both take the
  mode's search config. After that branch is merged, the held-out states would therefore be sampled with the
  efficiency switches, bounded `nlinarith` included. The owner said "held-out evaluations keep today's settings". The
  comparison within step 2 stays consistent, but its v0 numbers would no longer match O2's held-out runs or the
  2026-11-15 run.
- Fix:
  - Install and start, step 1: start step 2 only after O2's gate has decided the mode and the efficiency branch is
    merged and deployed, with the mode taken from that master.
  - Decide on the efficiency branch whether held-out evaluations take the plain search config, as probe runs do.

**S2. The report does not give C's and D's expert-iteration rate. It gives a pointer whose content is a label, not a
rate.**
`src/lean_search/rl/learning_rate_step.py:327-337`, `deployment/study_chain.sh:198`.
- The values table says "from O2: the 'Chosen:' line of /workspace/runs/offline_chain/rank_matched.txt".
- That line reads `Chosen: matched_5e-5 (...)` (`offline_arm.py:976`, `run_label`). So the orchestrator must open
  another chain's file and strip a prefix. `offline_arm.py chosen-rate` exists for exactly this.
- By the time step 2 can run (after O2's gate, S1), O2's ranking exists. The report can state the value and fail
  loudly when it is missing.
- Failure scenario: the file is missing, or O2 was rerun under another state directory (`OFFLINE_CHAIN_STATE`).
  The report still prints the pointer and the step ends in HOLD. Arms C and D then wait on a manual lookup, which
  nobody checked during the step.
- Fix: in `report`, read `--o2-ranking` with the existing `chosen_label`, map `matched_<rate>` to the rate as
  `offline_arm.chosen_rate` does, and print the rate in the C and D rows. If the file is missing, print
  "O2 not ranked yet (<path>)" in bold above the table. One test per case.

**S3. DESIGN's Arms section still describes the old plan.** The new step-2 bullet (`DESIGN.md:1325-1334`) is
accurate, but the text around it contradicts it:
- `:1168` "Each enters step 3 with its own learning rate from step 2 (decided)": C's now comes from O2.
- `:1179-1181` "The closed-loop outcome-only control is B2 ... B1 and B2 both train at step 2": B is dropped.
- `:1188-1190`: the window is "tested" at step 2; it is now the owner's 4.
- `:1351`, `:1356`: D "takes A's and C's step-2 settings", "C's window by the same rule".
- `:1372`: "First two arms ... A with B2".
- HANDOFF.md:299-303 still has the 48M, slice-4, ten-round plan, and :21 asks the owner about D's window and C's
  window 1, which are now decided.

The next agent reads these sections first. Fix: one line at each place pointing at the 2026-11-17 decision. Mark the
old Step 2 table and "Ranking the rates" bullet as superseded, as the "Shared sampling" bullet already is.

## Nits

**N1. The report's window value is a constant, not read from the config.** `learning_rate_step.py:37`,
`C_WINDOW_PHASES = 4`. The report prints it, while `arms/C.toml` and `arms/D.toml` hold the value
(`test_a_round_arm_trains_on_the_owners_4_phase_window` pins 4 there). Nothing ties the two. Either read the window
from `arms/C.toml`, or add a test asserting the constant equals C's and D's configured window.

**N2. The rounds' seeds are not phase 1's.** The rounds keep the template's `policy.optimization.seed = 0` and
`policy_replay.seed = "grpo-replay"`; the loop's phase 1 uses 1 and `"grpo-replay/1"` (`loop.py:660-661`). With the
trees now the same kind as A's phase 1, setting these two seeds would make the chosen round A's phase-1 update in
everything but the trainer and GPU nondeterminism. It costs two lines in `grpo_phase_config`. The docstring already
states the difference honestly.

**N3. Values-table cells carry notes.** `learning_rate_step.py:332-336`: "4 (owner, 2026-11-17)", "5e-5 (A's)". These
cells are meant to be copied into TOML. Put the provenance in a fourth column ("Source") and keep the Value column
pure.

**N4. `slice_trees.py`'s docstring still describes the old use.** Its module docstring (line 11) still speaks of
slice_4 and four slices. Add the `--slices 1` use.

## Checked and fine

- **The rounds against A's phase 1.**
  - `shared_sampling.toml` now stops at 12M = B, as a sampling-only run (the phase budget of 1e9 never comes due).
    Its trees are v0's, from the curriculum's first band with the same seed. They end where arm A's phase 1 ends:
    the first check at ≥ B finished-tree tokens.
  - In both, the searches in flight at that moment are not in the phase: lost in the shared run, carried into phase 2
    in the arm.
  - So the training data is the same kind as A's phase 1, which the old slice-4 plan was not (later band, slowest
    searches dropped). The rate chosen is the rate for A's first update. Later phases (higher band, drifted policy)
    are untested by construction.
  - `slice_trees.py --slices 1` gives every tree in finish order (`slice_by_tokens` with count 1: one cut at the end).
- **The round config.** `grpo_phase_config` is arm A's overlay at the variant's rate through `overlay_configs`, as the
  arm's own config is built. That gives per-tactic credit, v0 as start and KL reference, KL 0.01, clipping, batch, one
  pass and the loop's replay files (tests pin each).
- **The ranking.** `choose_rate` over A's three variants: paired per state, ties by the 95% interval to the best, then
  the lower rate (`tie_break`). The report re-derives the choice and refuses a mismatch with `rank_A.txt`. The
  multiple-comparisons note counts 8 intervals (3 × 2 + v0's A/A pair). The below-v0 and drift warnings carry over
  from AV's fixes.
- **The arms' configs.** C has `expert_iteration_window_phases = 4` with a round every phase. D has a window of 4 with
  a round every 4 phases, so D's rounds now see every phase's trees (AV's question 4 is settled). The PLACEHOLDERs left
  are A's rate (A, D) and O2's rate (C, D), as `test_followup_arms` pins.
- **The driver.** The expert-iteration builds, dry runs and C rounds are removed cleanly. The rounds line has 8
  fields, no empty one. S3a and S3b are unchanged, and the stop at HOLD stays. The chain tests still cover a kill at
  every step.
- **Ops-doc timings.** About 0.5 h of sampling at ~25M tokens/h, plus the server start and the loop's v0 baseline;
  3 rounds of ~0.5 h; 4 held-out runs of ~12 min. That adds up to the stated 3-4 h. The PLACEHOLDER description
  matches the code.

## Questions for the owner

1. **A tie still picks 2e-5.** If one phase's update does not separate the three rates on 512 states, A gets 2e-5,
   the old run's rate. D inherits it. Keep the lower rate as the tie rule, or take the middle rate?
2. **Does O2's rate transfer to C's rounds?** O2 runs one cosine schedule over 4 epochs of ~2M tokens of known proofs,
   sampled without reasoning. Arm C runs 4-phase-window rounds, each 1 epoch with its own warmup and cosine, on the
   loop's own blocks, possibly with visible reasoning if the gate keeps it. Same recipe and trainer, but a different
   schedule and possibly another mode. Accept O2's rate as is, or check C's first round (replay-loss change, KL) before
   going on?
3. **The held-out states and the efficiency switches** (S1). Should the arms' in-loop held-out states and step 2's
   held-out runs be sampled with the efficiency switches, like the arm's training searches, or with today's plain
   search, like the probe runs? The latter keeps them comparable with O2's held-out runs and with v0's earlier runs.

## Re-review (2026-11-17)

Fixes reviewed: 4a0b192..6182609 (head 6182609), four commits.

Checks run:
- In WSL, against the worktree's `src`, these suites: `test_learning_rate_step`, `test_learning_rate_report`,
  `test_study_commands`, `test_study_chain_script`, `test_offline_chain_script`, `test_tree_slices`,
  `test_followup_arms`, `test_rate_ranking`. 366 passed.
- `ruff check` and `ruff format --check` over `src`, `experiments` and `tests/rl`: clean.
- No node access, as asked.

**Verdict: merge.** S1 and S2 and all four nits are fixed. S3 is fixed except two stale lines in HANDOFF section 8 B,
a nit below. I found nothing broken by the fixes.

### Status per finding

| Finding | Status | Notes |
|---|---|---|
| S1 node order and efficiency switches | fixed | The ops note's "Install and start" now begins with step 0, the node's order: O2's gate must have chosen the mode, the search-efficiency branch must be merged and deployed (the modes then name `*_sampling.toml`), and the offline chain must be at HOLD or STOPPED. Its claim about held-out runs is accurate: on the efficiency branch, `search_models.evaluation_run_config` sets `result_cache`, `timeout_skip` and `nlinarith_variant` to None and `spare_processes` to None, and `fixed_targets` applies it to the held-out states (line 122) as well as to probe runs. So held-out runs stay on today's plain search. A new guard, `other_chain_idle`, makes each driver stop itself before its first server or GPU action while the other has started and is neither at HOLD nor STOPPED. It is tested both ways, including O1's switch while step 2 runs. A simultaneous start of both drivers stops both, which is the safe outcome. |
| S2 C's and D's rate not stated | fixed | `o2_choice` reads `rank_matched.txt` with `chosen_label` and maps `matched_<rate>` over the offline config's `learning_rates`, as `offline_arm.py chosen-rate` does. A missing file, a chosen line of another subset (`pool_…`), or no or several "Chosen:" lines (a `ValueError`) all give "-" and a bold "O2 not ranked yet" with the reason. The report still completes. Tested: both rates, another subset, the missing file end to end. |
| S3 stale DESIGN and HANDOFF text | fixed, apart from N5 below | DESIGN's Arms intro, the B2-control bullet, the window bullet, the old Step 2 table, "Ranking the rates", "Gate" and "First two arms" are now marked superseded or rewritten. Each points at the 2026-11-17 decision, and the rewrites are accurate. HANDOFF's state lines and step 3 now describe the A-only step and the node order. The B2 rows of the Arms table stay under an explicit "for the record" line. The work-package "Order" paragraph (`DESIGN.md:1428-1433`) is history and fine as it is. |
| N1 window a constant | fixed | The window is read from `arms/C.toml` (`expert_iteration_window_phases`). D's equality with it is pinned by `test_followup_arms`. The window now appears as a line that it is already set, not as a table row, which is right since nothing is left to fill. |
| N2 seeds not phase 1's | fixed | `grpo_phase_config` merges `policy.optimization.seed = offset_number_seed(1, 0)` (that is, 1) and `policy_replay.seed = offset_seed("grpo-replay/1", 0)` (that is, `"grpo-replay/1"`). These are exactly `loop.phase_config_text` at phase 1 and seed offset 0. Tested. |
| N3 notes in value cells | fixed | The table has a Source column; the Value cells are bare rates. |
| N4 `slice_trees.py` docstring | fixed | The docstring now describes the `--slices 1` use. `--slices 1` has its own tests, and a name clash between phase directories is refused (see N6). |

### New nits

**N5. HANDOFF section 8 B still describes the old placeholders.** `HANDOFF.md:260-261` says "Both still carry
PLACEHOLDER values that the learning-rate step fills: C's window (1 or 4 phases) and learning rate (5e-5 or 1e-4); D
takes C's window and rate". The window is now set to 4, and C's rate comes from O2. Fix: change to "C's and D's
expert-iteration rate (from O2) and D's GRPO rate (A's, step 2); the window is 4".

**N6. The tree-name clash check is an `assert` on input data.** `tree_slices.write_slices` checks that two phase
directories do not hold trees of the same file name with an `assert`. That clash can come from a real multi-phase
run, so it is invalid input, not a broken invariant. The style rule asks for `ValueError` there, and an `assert`
would vanish under `python -O`. It cannot occur for step 2's one-phase run.
