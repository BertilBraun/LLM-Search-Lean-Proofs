# Review AB: design of the follow-up study's controlled arms (DESIGN.md, uncommitted, 2026-11-14)

Scope: the section against master (20ac13b), `results/followup_step0/` (no `training_signal.md` yet), the loop, credit,
health, search, policy, expert-iteration and evaluation code, the configs and `deployment/`. Two decisions flagged (S6).

## Must change before running

**M1. B2's reward pays no-ops and failed first tactics** (Arms table, B2; WP3 tests). "r = 1 if the state the
sample's kept prefix reaches is on the proof graph": every group sits at a proof-graph node, so a block whose first
tactic fails (empty prefix, the state is the node itself) and a no-op or back-to-ancestor block (`TacticLabel.NO_PROGRESS`
covers "the node and its ancestors") both "reach" a proof-graph state and score 1. That is the bare-claim/no-op hack of
phases 1-10 in its purest form. **Change:** r = 1 iff the last tactic of the kept prefix that reaches a state is labelled
`PROOF_GRAPH` (so NO_PROGRESS, REDUNDANT_HYPOTHESIS, an empty prefix and unparsed samples are 0). Add WP3 tests: first
tactic fails (0), pure no-op (0), back to an ancestor on the graph (0), graph then off-graph continuation (0).

**M2. Search outcomes on this node depend on CPU load, and nothing fixes the load** ("Identical in every arm":
concurrency 112; "Evaluation": no concurrency). The old node used 81 Lean cores late at 112 searches; here ~45 remain.
Load changes results, not only speed: a tactic past the 60 s wall `tactic_timeout_seconds` is `FAILING` ("timeouts
included"), a reward label; the held-out 120 s and probe 1,800 s caps are wall caps; a cgroup over `cpu.max` throttles
the vLLM processes too. The held-out v0 reference runs at `baseline_concurrency = 6`, every pause at 112, so the hard
stop's 0.7x compares different loads. **Change:** from the throughput test fix (a) sampling concurrency, (b) mandatory
`BACKGROUND_CPUS` pinning below the quota, (c) one probe and one held-out concurrency, the held-out baseline at the
pause's; compare wall-timeout shares with the old node's. Every arm and checkpoint evaluation uses these numbers.

**M3. No tool evaluates an arbitrary checkpoint** (standalone evaluation of step 2's variants, phases 4/8/16 with own
value or v0, runs 6/9 with none). `grpo_evaluate.py` evaluates the loop's `current.version` with `[evaluation]
value_model`; merges are kept only for the current version and v0 (`Publisher.prune`). **Change:** WP0's tool must take
(policy adapter, value adapter | v0 | none, target, budget, mode) independent of `models/current.json`, merge on demand,
delete the merge after (~13.5 GB), and write where WP6 and `probe_rating` read. Confirm WP0's scope before step 1.

**M4. Q3: A\*'s depth term penalises no-reasoning by block count** (Step 1, runs 3-4). `visible_student_v2.toml` has
`depth_weight = 0.25` on `node.depth`, which counts blocks; a no-reasoning block is ~1 tactic against ~2-3, so the same
proof costs the no-reasoning search 2-3x the depth penalty and pushes it breadth-first. The design scaled `max_depth`
for this reason but not the priority. **Change (config only):** run 3 and 4 both at `depth_weight = 0` (report run 3 vs
run 1 to show what that changes for visible), or scale it for run 4 by the measured tactics-per-block ratio.

**M5. Q4's value-free priority is undefined in the one parameter that decides it** (Step 1, "Q4 without a value
model"). `CumulativeLogProbability` divides by `depth ** length_exponent` (default 1: the mean block log-probability,
depth-first-leaning); the decision says "log-probability of the path" (a sum, exponent 0: near breadth-first). The two
give very different 16-expansion solve rates, so Q4's answer depends on it. **Change:** state the exponent; if it is
chosen (and the automation constant calibrated), do it on non-probe statements (the gate set or 200 pool statements),
never on probe v2 or run 1's proofs.

**M6. WP4b is under-specified where the loop breaks** (WP row 4b). (a) `check_health` takes the version with
`trigger == phase_trigger(phase)` (StopIteration otherwise) and judges only it: D's SFT round must publish as its
phase's one version, or no held-out check or hard stop ever sees it. (b) `ResidentTrainer` asserts `config.policy is not
None` (resident_trainer.py:182, 332): C's value-only phases need `persistent = false` or code. (c) An SFT job beside the
parked trainer finds `/dev/shm` full (~28 GiB parked, 8 GiB required free). (d) D's GRPO must run on A's code path
(resident trainer), not `grpo_phase.py`. **Change:** put (a)-(d) in WP4b with restart tests in build, train and publish.

## Should

**S1. Defer WP4b; size C's rounds first.** C enters step 3 only if step 2 puts it ahead: write WP4b after the gate.
Round 1 kept 6,826 examples from ~10 phases (~76 steps per epoch): one phase at W = 1 is ~8 optimizer steps (W = 4
~30), less than its load, compile and three ~1M-token evaluations. Run `train --dry-run` on slice 4 and slices 1-4
before fixing C's rates; alert on the replay-loss rise in every in-loop round (W = 4 is four epochs per block).

**S2. Sequence credit corrupts the explanation measure** (WP5). In `token_credits`, `not per_tactic` labels every
non-inserted token `EXPLANATION`, so `PolicyDataMetrics.mean_explanation_tokens` is the whole completion in B1 (and B2
if built the same way). WP5's tree-based explanation tokens are therefore required, not an alternative; WP3 must
label segments by position regardless of credit. For the reference: `reference_phases = 1` (existing switch) gives
every arm v0's own samples (phase 1 trains after sampling) under its own curriculum, and drops WP5's shared-run reference.

**S3. WP1 misses three things.** (a) A stop after phase N (or at a total token count): nothing stops an arm after
phase 16, and the step-2 shared run needs the same at 48M (also: `phase_due` fires at `max_sampling_minutes` with one
group, so that must be out of reach too). (b) The left-out trees' tokens must be persisted (progress file or index),
or a restart forgets them. (c) Drop "evaluation cadence by phase": the section itself uses a tiny `every_hours`, and
probes are standalone.

**S4. A second seed is not a config change.** `phase_config_text` sets the policy, value and replay seeds from the phase
number. Add a loop `seed_offset` before second seeds (identical seeds across arms are fine until then).

**S5. B1 is not outcome-only.** Its score keeps δ per step, λ·L for unknown/off-graph/failing, and c per wasted
tactic. If B1 goes on, the Q2 rows read "spreading graph credit per tactic adds nothing / helps", not "the labels add
nothing". Write the outcome rows per control.

**S6. Two decided rules, flagged once.** (a) One round favours the largest rate, the regime that collapsed v4 to v10;
remedy: the lowest rate within the noise floor (~2.6 points) of the best, which also defines "tie". (b) The control
"that differs more from A" may be the worse one; remedy: record the direction, and read a step-3 win accordingly.

**S7. Step 1 ordering and cost.** T64 = 64 × run 1's mean needs run 1 (WP0), so the no-reasoning miniF2F run cannot
run "now"; define T64 from miniF2F's own visible 64-expansion run. Run 4 does ~10x the expansions, each with the
7-tactic sweep: estimate 10-30 h alone on this node; pilot it on 200 stratified probe statements first and report
wall-cap stops per mode (the 7,200 s cap stops no-reasoning first, under-spending its tokens).

**S8. Take WP7 off the critical path.** pool.md §4-5: 43k unfed usable statements at 1,000-4,499 characters (~8x one
arm's demand); an arm is expected to reach ~1,500-2,000. The frozen snapshot is a file copy plus `unverified = ""`.

**S9. Launch and base-config hygiene.** `grpo_loop.sh` defaults `LOOP_CONFIG` to the old `loop.toml`, `HOURLY_PRICE`
to 0.80, and pinning is optional: use a launcher that requires the arm config. The base config must also set the keys
whose dataclass defaults differ from the old run (`persistent` false, sampling minutes 45/90, `value_model` initial,
`value_arm.enabled` true, held-out wall 600 s); a test should parse each arm config and diff it against the base.

## Minor

- Code statements to correct: the GRPO loop reads `verified` at every `watch` tick (30 s, `CurriculumStatements.refresh`;
  `reload_seconds` is used only by `search_service.py`); `phase_due` at 120 min needs ≥ 1 group; `sampled_token_offsets`
  moves to `search.texts` (WP0, e7222bb). The rest checked holds (credit modes, `policy_groups`, `has_signal`, rollback 0,
  `measurements`, `log_probability` incl. forced/merged samples, the token cap, harvesting, EI refusals, loop.toml).
- Q3's prompt check is answered by code: v0's no-explanation examples are `tokenize_example` (`render_prompt(goals)` +
  fence prefill), exactly what `visible_reasoning = false` renders. Drop it as a risk.
- WP2 tests: also REPAIR nodes (inherit the sampled block's value) and a visible sample running on after its block.
- The token cap's last-expansion overshoot is ~3% of T for visible, <0.5% for no reasoning: report tokens used.
- Tokens of searches lost to a crash or server failure are never counted; log them per phase.
- `tree_statistics.py:271` counts `groups_with_signal` with `PER_TACTIC` whatever the arm's credit (dashboard).
- Step 2's `grpo_phase.py` runs need `--lean-replay/--math-replay` (the loop's NLL replay) and slice directories.
  Finish-order slices: the stop drops in-flight (slow, hard) searches from slice 4, and the band rises across slices.
- Disk: ~10 GB of adapters per arm is fine; check free space before each merge-evaluate cycle. Run v0's held-out
  states once and copy it to every arm (one hard-stop line). WP4a: say whether carried trees' older-version samples count.
- `noise_floor.md` is in: fill the rule's placeholder (≥ 3 points). Step 2's 13 probe runs and the costs differ from
  `followup_progress.md` (held-out screening, finalists only; $30-45 per arm): make them one plan.

## Work packages and the node today

Riskiest: WP4b (state machine, trainer residency, restart mid-round), then WP1 (every arm's phase boundary; restart
tests with trees in flight). Missing packages: M3's evaluation tool (if WP0 lacks it), the seed offset (S4), the study
launcher and per-arm configs (S9). Runnable now with existing code, one at a time: node-check, the throughput test
alone (it sets M2's numbers, so nothing else beside it), the v0 reproduction on the old probe, miniF2F visible runs
(v0 with value v0 and final). Not runnable now: probe runs and the shared sampling (probe v2 must be in `held_out`),
the T64 run (S7), anything value-free (WP2).

## Verdict

Sound in structure, and the code claims are mostly accurate. Not ready to run step 1 until M2-M5 are settled (all
config or one-line decisions except M3, which may be WP0 scope), and not ready to implement WP3 or WP4b until M1 and M6
are written in. S1-S3 save money or prevent unattended overruns and should go in with WP1.

## Re-review (revised section, uncommitted, read 2026-11-14)

| Item | Status |
|---|---|
| M1 B2 pays no-ops | **Resolved**: r = 1 only if the kept prefix's last state-producing tactic is `PROOF_GRAPH`; WP3 tests cover failing first tactic, no-op, ancestor, off-graph end, unparsed |
| M2 load | **Resolved**: one sampling, probe and held-out concurrency plus mandatory pinning from the throughput test; held-out baseline at the pause's; nothing beside a run |
| M3 checkpoint evaluation | **Resolved** as WP0 scope (any policy/value/none pair, merge on demand, delete after) |
| M4 Q3 depth term | **Resolved**: `depth_weight = 0` in runs 3-4, run 4 compared with run 3 only |
| M5 Q4 priority | **Resolved**: exponent 1 (per-block mean) stated, taken from the pre-value row-2 search, automation constant on 200 non-held-out statements |
| M6 WP4b | **Resolved**: (a)-(d) and restart tests in the WP row; WP4b after the gate |
| Three code statements | **All correct now** (watch-tick re-read, ≥ 1 group at 120 min, offsets moving to `search/texts`) |

Not applying the shared v0 held-out run is not a blocker: with the load fixed, each arm's own v0 run differs by noise only.

New problems (none blocks step 1):
- **N1 (should).** "A run is accepted only with under 1% wall-clock stops" has no action for a failed run, and run 4
  (~10x Lean, up to 1,024 expansions) is the run most likely to fail it under the same 7,200 s cap. Pre-state: if the
  200-statement pilot exceeds 1%, raise the cap for runs 3 and 4 together before the full runs; say whether the rule
  also binds runs 3-4 and miniF2F.
- **N2 (should).** Step 3's phase-1 check (±30% against the arm's step-2 round) compares phase 1 at the band's start
  with slice 4, which is later and harder; groups and trained sequences per token will differ for curriculum reasons.
  Compare against slice 1 labelled offline with the arm's credit (labelling only, no training).
- **N3 (minor).** "Moved ≥ 3 points from v0" on single runs of the 402-statement gate set is near a coin flip at 3
  points (paired SE ~1.5-2 points there); report intervals and make the "step too small" call on the chosen rates'
  probe runs, which exist anyway.

Step 1 may start once WP0 (tool, probe v2, base config) and WP6's launcher and config-diff test are merged and the
throughput test has set the load numbers; runs 6 and 9 wait for WP2.
