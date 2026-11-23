# Review BS: arm D on F's credit with a round every phase (code, tests, docs)

Scope: the uncommitted diff to `experiments/configs/grpo/followup/arms/D.toml`, `DESIGN.md` and
`tests/rl/test_followup_arms.py`, plus what else still encodes D's old settings. Run in WSL:
`tests/rl/test_followup_arms.py tests/rl/test_followup_screens.py tests/rl/test_arms_chain.py`: **1 failed, 141
passed**; `ruff check` and `ruff format --check` on the test file: clean.

Validation (question 2): D's written configs load. `PolicyDataConfig` accepts `verified_fraction` with the cap off
(`rl/policy_data.py:52` refuses the cap only when it is on); `parse_loop_config` accepts
`grpo_and_expert_iteration` with every = 1, window = 4 (`rl/loop_config.py:436-453`: all ≥ 1, persistent, recipe and
initial adapter come from the base); `recipe_refusals` is empty for D (`test_a_round_arms_recipe_is_one_the_loop_runs[D]`
passes). No ValueError path is hit.

DESIGN's "reads neither" (question 3) holds: `claims_earn_progress` and `unproved_claim_cost` are read only in
`judged_in_block` (`rl/grpo_groups.py:290-293`), which changes `parts` and `gain` but never `label`, `steps_gained` or
`adds_claim`; `GroupSample.verified_fraction` (`grpo_groups.py:168-177`, via `verified_progress`, 151-165) reads only
those, and `advantages.py:53-54, 82-83, 119, 145` uses only `verified_fraction` for this mode.

## Findings

1. **blocker**: the change breaks `tests/rl/test_arms_chain.py:95-96`
   (`test_the_d_smoke_overlay_also_brings_its_round_within_its_one_phase`). `smoke_overlay`
   (`src/lean_search/rl/arms_chain.py:77-79`) only rewrites `expert_iteration_every_phases` when it exceeds the smoke's
   one phase; D's is now 1, so D's smoke overlay changes only `BUDGET_KEYS`. Fix: replace the C-only test (line 91-92)
   and the D test with one `@pytest.mark.parametrize("arm", ["C", "D"])` test asserting `changed_keys(arm) ==
   BUDGET_KEYS`. The branch at `arms_chain.py:77-79` is now dead for every live arm (A has no rounds, C and D run every
   phase): either delete it (project rule: no checks for cases that cannot happen) or, if kept, test it on a synthetic
   overlay with every = 4 so the behaviour stays pinned.

2. **should-fix**: stale docstring `src/lean_search/rl/arms_chain.py:65-67`: "the heaviest pause C and D meet (C at
   every even phase, D at every fourth)". D now meets GRPO + round + value at every even phase. Fix: "... the heaviest
   pause C and D meet (both at every even phase, D with its GRPO update too)", and drop the "round interval longer than
   the smoke's phases brought within them" clause if the branch goes.

3. **should-fix**: `tests/rl/test_followup_arms.py:46-48`: the `CLAIM_SWITCHES` / `EXPLANATION_CAP` comments say "on in
   the arms training with GRPO" and "on in the same arms"; D trains with GRPO and has neither. Fix: "on in arm A since
   ..." for both.

4. **should-fix**: `tests/rl/test_followup_arms.py:272`: `round_arm("D", 2e-5)` goes through `filled()`, which
   overwrites D's own phase rate (and SFT rate and window) before the comparison, so the test passes even if D.toml's
   rate drifts from F's 2e-5; only `CHOSEN_RATES` catches that. D has no placeholders, so compare the arm as written:
   `arm_configs(toml(CONFIGS / "followup/arms/D.toml")).phase`. Same for line 276-277: `round_arm` forces window 4 on both
   C and D, so a window divergence would not fail "D's loop config is C's but for its name and policy update"
   (it is caught only by line 349-351). Use `arm_configs(toml(...))` for both arms there too. The screen-building block
   (263-271) duplicates `screen_configs` in `tests/rl/test_followup_screens.py:39`; a module-level helper or a shared
   fixture would avoid the copy (note-level).

5. **note**: `tests/rl/test_followup_arms.py:223-238`: the `every` column is now 1 in both rows; drop it and set
   `"expert_iteration_every_phases": 1` in `rounds`, or parametrize only `(name, update)`. The test name then still says
   what it checks. Line 275-279 already pins D's loop = C's loop, so this parametrization over D is a near-duplicate.

6. **note** (lost guarantee, acceptable): the removed `D` rows of the claim-switch and cap tests and the "D's phase is
   A's" test are replaced by full phase equality with the F screen (line 262-272), which also pins that D sets neither
   switch nor the cap. But nothing refuses claim switches under `verified_fraction` credit (`study_configs.py:264`
   checks only per policy update; the cap is refused by `policy_data.py:52`). A future D overlay adding the switches
   would be silently inert, caught only by the F-equality test. Acceptable while that test stays.

7. **should-fix**: `DESIGN.md:1157`: Q2 row "D vs A and C | D ahead of both: GRPO and expert-iteration rounds are
   complementary". D's GRPO is no longer A's, so D vs A no longer isolates the rounds; the stated purpose is now D vs C
   (what one GRPO step adds to C's schedule). Fix the row: "Q2, D vs C | D ahead: F's GRPO step adds to C's rounds",
   and say D vs A compares credit and rounds together. Also `DESIGN.md:1499-1500` still lists "N = 4 for D" as an open
   owner confirmation; mark it decided (every phase, 2026-11-23).

8. **should-fix**: `src/lean_search/rl/README.md:1258`: "(D: A's GRPO update every phase, a round after it)" -> "(D: a
   GRPO update every phase, F's progress-fraction credit in the follow-up, a round after it)". Lines 105 and 175:
   "on in arms A and D since 2026-11-18/19" -> "on in arm A since ... (in D until 2026-11-23)".

9. **should-fix**: `tests/rl/test_claim_progress.py:16`: comment "# Arms A and D since 2026-11-18." -> "Arm A's since
   2026-11-18." (the constant `ARMS` at line 17 could become `ARM_A`, since it names the arms' settings).

10. **note**: other docs now stale about D, not code: `HANDOFF.md:17` ("on for A and D"); `results/followup_node_operations.md:529-531`
    (smoke: "D's round interval brought from 4 to 1", "D (every fourth) will meet"; historical for the smoke already run,
    but the future tense reads as current), and line 519-522's "2 × 21-23 h (C, D)" estimate: D now pays a round at every
    phase plus a GRPO update, so D's arm takes C's time plus 16 GRPO updates; restate. `results/followup_progress.md:461`
    still says D's round interval "stays open"; it needs the 2026-11-23 decision entry. `deployment/arms_chain.sh`'s header
    (lines 11-15) makes no claim about D's credit or period: fine.

11. **note**: `src/lean_search/rl/learning_rate_step.py:362` (`values_section`) maps D's GRPO rate to "A's". It renders
    step 2's historical report (already produced and applied); D's rate is pinned by the arm file and `CHOSEN_RATES`, so no
    change is needed. Rerunning it would print a now-wrong source for that one row; a one-line docstring note is optional.

12. **note**: `D.toml` comments. Line 1-2 "at every pause, and after it at every pause C's expert-iteration round"
    repeats "at every pause"; "the F screen's GRPO update and after it C's expert-iteration round over C's window at
    every pause" says the same once. The probe numbers appear twice (line 4 "after F at 16 phases tied C" and line 17
    "1,059 of 2,000 against C's 1,049"): keep one (the credit line's) and drop "(…, after F at 16 phases tied C)" or vice
    versa. `learning_rate = 2e-5` lost its rationale; line 1 implies it (F's), which is enough. No identifier issues.
    The smoke test the node ran used D's old per-tactic GRPO; the F screen exercised `verified_fraction` in the same
    resident trainer and the smoke exercised GRPO + value + round in one pause, so no new smoke is needed for the change.

## Re-review (2026-11-23)

Working tree re-read (`git diff`). WSL: `tests/rl/test_followup_arms.py tests/rl/test_arms_chain.py
tests/rl/test_claim_progress.py`: **171 passed**; `ruff check` and `ruff format --check` on the four changed Python
files: clean.

1. Resolved: one smoke-overlay test over C and D expects `BUDGET_KEYS` (`test_arms_chain.py:91-93`); the interval
   branch is kept and pinned on a made-up period-4 overlay (`:96-100`).
2. Resolved: the `smoke_overlay` docstring now says "both at every even phase"; its clause about bringing a longer
   interval within the phase stays, which matches the branch that was kept.
3. Resolved: the comments at `test_followup_arms.py:46-48` now name arm A.
4. Resolved: `as_written` builds D (phase vs F screen) and C/D (loop) from the tomls without `filled()`. The screen
   builder still copies `test_followup_screens.screen_configs` (note-level, left as is).
5. Resolved: the `every` column is dropped; the test sets 1.
6. Note, unchanged by design: nothing refuses claim switches under `verified_fraction`; the F-equality test guards D.
7. Resolved: the Q2 row is now "D vs C" with its reading; the open-point line records "every phase (owner, 2026-11-23)".
8. Resolved: README lines 105, 175, 1258.
9. Resolved: `test_claim_progress.py:16` comment (the constant `ARMS` keeps its name; fine).
10. Resolved: HANDOFF.md:17 and the smoke paragraph in `followup_node_operations.md` ("then every fourth");
    `followup_progress.md` has the 2026-11-23 "run D" section with the reading rule and an estimate of about 17.5 h of loop.
    The planning table's "about 19 + 2-3.5 each" (`followup_node_operations.md:519-522`) is left as is, and the new
    estimate falls inside it.
11. Note, no change needed (historical step-2 report).
12. Resolved: the D.toml header says "at every pause" once, and the probe numbers appear only in the header's
    "after F at 16 phases tied C".

No open findings.
