# Review BJ: the two GRPO screens (A at 2e-5, B2 at 5e-5)

Scope: `experiments/configs/grpo/followup/screens/A_2e-5.toml`, `B2_5e-5.toml`, `tests/rl/test_followup_screens.py`,
`results/followup_progress.md` section "Owner, 2026-11-20 ~10:50 UTC" (lines 307-325). Read against
`experiments/followup_arm.py`, `src/lean_search/rl/study_configs.py`, `deployment/arm_loop.sh`, `grpo_loop.sh`,
`arms_chain.sh`, `chain_helpers.sh`, `src/lean_search/rl/loop.py`, `loop_services.py`, `experiments/node_checks.py`.

## What I verified

- **Configs are exactly as intended.** Built both overlays through `overlay_configs(OverlayKind.SMOKE, ...)` with the
  real base, `phase.toml` and recipe. Loop config vs `base.toml`: only `name`, `training.max_phases` 16 → 8 and
  `training.phase_config` differ; every other top-level table is identical (`phase_generated_tokens` 12M and
  `value_every_phases` 2 restate the base's values). Phase config (as `TrainingPhaseConfig`): A screen == `phase.toml`
  + A's claim switches + cap at 2e-5; B2 screen == `phase_proof_success.toml` at 5e-5.
- **B2's template.** `followup_arm.py` always uses `base.training.phase_config` (`phase.toml`) and only overlays
  `credit = "proof_success"`; it never reads `phase_proof_success.toml`. That is not a silent difference:
  `phase_proof_success.toml` is `phase.toml` with only `[policy.data] credit` changed (the diff is comments plus that
  line), and `test_followup_arms.py::test_an_arms_phase_config_is_its_credits_shipped_phase_at_the_chosen_rate`
  (`CREDIT_PHASES["B2"]`) already pins the parsed equality. The B2 screen is what arm B2 would have been at 5e-5.
  The cap and claim switches stay at the template defaults, as in `arms/B2.toml`.
- **ARM kind refuses both screens** ("changes only ..."), so running them without `--kind smoke` fails loudly.
- **Smoke kind is safe for 8 phases.** In `arm_loop.sh` the kind only reaches `followup_arm.py` (allowed settings and
  the shared-sampling check, which applies to SMOKE as to ARM). Everything keyed on "smoke" (`SMOKE_PHASES = 1`,
  `smoke_checks`, the kill, `sample_resources`, `smoke_poll_seconds`) lives in `arms_chain.sh`/`arms_chain.py`
  `run_loop`/`smoke_test` and only touches `followup_smoke_{C,D}`; the manual screens never pass through it. No
  script, backup or dashboard selects runs by a `followup_*`/`smoke` pattern. The loop sees an ordinary arm:
  fresh curriculum from `initial_band_low` with the same seed (no seed derives from the run name), v0 held-out
  baseline at start, held-out at every pause including phase 8 (`ends_with` only changes the early resume), value
  model at phases 2/4/6/8, constant LR (`minimum_learning_rate_ratio = 1.0`), so phases 1-8 of a screen equal phases
  1-8 of a 16-phase run. `on_health_stop` is the driver's file and plays no part; a hard stop writes
  `health_stop.json` and the loop exits.
- **No wrong-weights risk for B2.** Even with A-screen servers left up, B2's `grpo_loop.sh servers` keeps them (they
  answer), but the loop's start calls `servers.serve(current)` (`loop.py:1125`), which with `swap = "restart"`
  restarts every server on B2's v0 before the v0 held-out baseline (`loop.py:1138`). Stopping the servers between
  runs is still right (GPU memory for B2's `init`, cost), and the procedure does it.
- **Driver interplay is safe.** At HOLD the driver has exited 0 and every restart exits at once on HOLD; if someone
  starts it while a screen runs, `no_other_loop` (only `followup_{A,C,D,smoke_C,smoke_D}` are its own) writes
  STOPPED instead of touching the servers. A screen cannot start while A's probe still holds the serving lock
  (`node_checks.py servers-free`).
- Tests: 9 passed in WSL.

## Blocking

None.

## Should fix

1. **The decision rule has no margin and mixes baselines** (`results/followup_progress.md:315-316`). "Beating C by
   phase 8" on single held-out points: A's own phase-to-phase swing is 31.1 → 36.1% (phases 4-8), step 2's A/A check
   on v0 was −0.4 [−2.8, +1.9], and the baselines differ (C's v0 run 34.3%, A's capped rerun 33.2%). A screen at
   36.5% at phase 8 could "beat" or "lose to" C by noise. Fix: state the rule now, e.g. mean held-out success over
   phases 4-8 minus the run's own v0 baseline, against C's same quantity, with a threshold (or the paired interval
   at phase 8 via `rank_learning_rates.py`-style comparison). Also add C's phase-5 value, missing from the list.
2. **B2 at 5e-5 confounds problems 1 and 2** (`B2_5e-5.toml`, progress doc line 319). If diagnosis (1) is right
   (5e-5 GRPO steps are ~3x C's), B2 inherits it, so a B2 failure does not show that shaping was the problem; B2's
   never-on-graph samples still get −mean r, so problem 3 also stays. B2's rate was never ranked (arm B was dropped
   before step 2). Fix: say so in the doc and read B2's per-phase parameter change / KL against A's 6-10% before
   attributing its outcome; or run B2 at 2e-5 if only one B2 screen is affordable.
3. **The procedure omits deploy, detach and watch** (`results/followup_progress.md:321-325`).
   - The overlays are uncommitted here; the node checkout needs them (commit, deploy at the HOLD as for b5f6425).
   - `arm_loop.sh` runs `init` and `servers` in the foreground for minutes; over SSH it must be fully detached, as the
     driver does with `setsid --wait` (ops doc section 1: `(setsid nohup deployment/arm_loop.sh ... > log 2>&1 <
     /dev/null &)`), or an SSH drop can kill a merge mid-way.
   - Nothing restarts a manual screen after a crash or container restart, and nothing starts B2 when A ends (up to
     hours of idle servers). Name the watchdog: `arm_loop.sh --status`, rerun the same command to resume, then stop
     and start B2.
4. **Health stops and the step between runs are not covered** (`results/followup_progress.md:323-324`). "When it ends
   (finished.json ...)" leaves out `health_stop.json`; the stop command is the same, but say so (and that a hard stop
   at A's 2e-5 or B2 is itself a screen result). Before B2, also check that A's loop process is gone and every GPU reads
   under 100 MiB (`arm_loop.sh` does not wait for GPUs as the driver's `wait_gpus` does; `servers-free` refuses only
   while the loop lives), and `df` (an arm takes about 38 GB; two 8-phase runs about 40 GB).
5. **"The better one then run to 16 phases" cannot extend the run in place** (`results/followup_progress.md:316`).
   `arm_loop.sh` exits on `finished.json`, and an overlay with `max_phases = 16` under the same name is refused
   ("holds other ['loop.toml']"). Since the LR is constant, extending (edit `loop.toml`, move `finished.json` aside)
   would equal a 16-phase run, but no path does that today. Decide now: a fresh 16-phase run from v0 (about 15 h
   more, the first 8 phases repeated), or a reviewed extension step.

## Minor

6. **Missing test: the written phase config per screen** (`tests/rl/test_followup_screens.py`). Nothing in this file
   checks that the screens' phase configs parse and equal the credit's shipped template at the screen's rate (B2 →
   `phase_proof_success.toml`); today that holds only through `test_followup_arms.py` at 5e-5. Add a parametrized
   `test_a_screens_phase_config_is_its_arms_shipped_phase_at_its_rate` comparing `TrainingPhaseConfig`s, reusing
   `CREDIT_PHASES` and `CLAIM_SWITCH_ARMS`.
7. **Missing test: an arm kind refuses a screen** (pins that `--kind smoke` is required, not silently ignored).
8. **Tests 3-5 largely restate test 2** (`test_followup_screens.py:53-66`): they check `merged` on values test 2
   already pins. Fine as smoke tests of acceptance, but `test_a_screen_is_accepted_as_a_smoke_run` asserting on the
   name reads as testing the name; asserting that it does not raise, or on `max_phases`, would read better.
9. **Style** (`test_followup_screens.py:14`): `SCREENED` maps to bare tuples `("A", 2e-5)`; a `NamedTuple Screen(arm,
   learning_rate)` matches the CLAUDE.md rule against untyped structures. `test_the_screens_are_a_at_2e_5_and_b2_at_5e_5`
   only asserts the stems; the name over-promises. `toml()` and `BASE` duplicate `test_followup_arms.py`; acceptable
   for a test module.
10. **The overlays restate base values** (`phase_generated_tokens`, `value_every_phases`): harmless and explicit, but
    a base change would no longer reach the screens; the test pins them to the base, so a mismatch fails loudly.

## Verdict

Approve with should-fix items. The configs are exactly the intended loops and phases (B2's included, equal to
`phase_proof_success.toml`), and the smoke kind is safe for 8 phases. Before running: fix the procedure (deploy,
detached start, watchdog, health-stop and GPU-free checks between runs) and write down the comparison rule with a
margin and the B2 learning-rate confound.

## Re-review (2026-11-20)

Checked: `screens/A_2e-5.toml`, `screens/B2_2e-5.toml`, `deployment/run_screens.sh`, the new progress section, the
reworked tests (9 passed in WSL). The configs, the 2e-5 move (B2's confound gone; the screens now differ only in
credit), the pre-registered rule with C's phase 5, and the tests (`Screen` NamedTuple, whole loop config against the
base, phase configs against A's and `phase_proof_success.toml`, ARM-kind refusal) close my items 1, 2 and 6-9.
`run_screens.sh` gets the basic `loop.pid` / `finished.json` contract right: the loop unlinks `loop.pid` only on a
finish (`loop.py:1103`) and leaves a dead pid on a crash or health stop, so `kill -0` ends the wait in every case
(nohup → background.sh → taskset all `exec`, so `$!` is the python pid); `grpo_loop.sh stop` copes with either. A
STOPPED from an earlier run blocks a start as intended. But its restart paths mostly end in STOPPED instead of a resume.

### Should fix

R1. **A retry never gets free GPUs** (`run_screens.sh:55-59`). A loop that dies while sampling leaves its 8 servers up
    (only a failure in training leaves them stopped), so `gpus_free` stays false and attempt 2 becomes STOPPED after 10
    min. The arms driver avoids this with `stop_servers` before `wait_gpus` (`arms_chain.sh` `start_loop`). Fix:
    `deployment/stop_model.sh --all` before the GPU wait on every attempt, and wait up to an hour as the driver does
    (a dead loop's persistent trainer finishes its command first). That also covers a script killed after a screen's
    `finished.json` but before its `grpo_loop.sh stop`: on restart that screen is skipped with its servers still up,
    and the next screen's wait fails the same way.
R2. **A restart is not resumable as the header says** (`run_screens.sh:10, 47-54`).
    - A health-stopped screen is not skipped. On restart `arm_loop.sh` inits nothing, starts 8 servers, the loop
      refuses on `health_stop.json` and exits, `arm_loop.sh` exits 1, and the script writes STOPPED with the servers
      left up. Fix: skip on `health_stop.json` as on `finished.json` (after `grpo_loop.sh stop`).
    - A screen whose loop still lives (the script was killed, the loop was not) is not adopted. The GPU wait fails,
      or `arm_loop.sh` refuses on the held lock, and the script writes STOPPED. Fix: `if loop_alive "${run}"`, skip the
      start and go straight to the wait.
R3. **`gpus_free` is unsafe under `set -u` and reads empty as free** (`run_screens.sh:34-38`). `[[ "${used}" -lt 500 ]]`
    evaluates its operand arithmetically. Text on stdout such as "No devices were found" makes bash look up `No` as
    a variable, and under `set -u` that kills the script on the spot, with no STOPPED (I checked: "No: unbound
    variable", exit 1, even inside `&&`). Empty output (nvidia-smi missing or writing only stderr) compares as 0 and
    reads as free; `set -e`/`pipefail` do not catch it because the function runs in `&&`/`||` context. Fix: read
    every line, require `^[0-9]+$` and exactly 4 lines, else not free (or STOPPED).
R4. **The documented start fails on a fresh node** (`run_screens.sh:5`, `followup_progress.md` "Run:"). The shell opens
    `> /workspace/runs/screens/run.log` before the script's `mkdir -p` runs. If `screens/` does not exist, nothing
    starts, and the error is easy to miss behind `&`. Fix: `mkdir -p /workspace/runs/screens` first, and use the ops
    doc's form `(cd /workspace/LLM-Search-Lean-Proofs && setsid nohup deployment/run_screens.sh > ... 2>&1 < /dev/null &)`.
R5. **"Under its arm config" for the 16-phase run collides** (`followup_progress.md`, decision rule, bullet 2). Arm A at
    2e-5 means editing `arms/A.toml` (pinned at 5e-5 by `test_followup_arms.py` `CHOSEN_RATES`), and
    `followup_configs/followup_A/` already exists, so `followup_arm.py` refuses ("holds other"). For B2, `arms/B2.toml`
    still has a PLACEHOLDER and B is in `DROPPED_ARMS`. Fix: say now that the run uses a new name (for example
    `followup_A_2e-5`), or that the old run and its configs are moved aside first, and which tests change.

### Minor

R6. The script runs from the checkout for about 17 h, and bash reads a running script lazily. A deploy during the
    screens can corrupt it, which is why the arms driver runs from an installed copy. Say "no deploy while it runs",
    or run a copy.
R7. 500 MiB against the driver's 100 MiB: fine, but say why.
R8. The decision rule compares absolute means with C's, while C's v0 baseline (34.3%) sits about a point above A's
    (33.2%). The 1-point margin and the phase-1 sanity check roughly absorb this; reporting the mean minus each run's
    own v0 too would make it explicit.
R9. Tests: `Screen.credit_phase` is used only by the B2 test; the A test hardcodes `PHASE`. Use it in both, or drop it.

### Verdict

The configs, the rule and the tests are ready. `run_screens.sh` needs R1-R4 before it runs unattended: as written, a
first crash becomes STOPPED instead of a resume, and an nvidia-smi hiccup can kill it silently. R5 must be settled
before the 16-phase run. With R1-R4 fixed: approve.

## Final check (2026-11-20)

R1-R7 hold in `deployment/run_screens.sh`. Every start or restart runs `stop_model.sh --all` and then waits up to 1 h
for the GPUs (lines 82-84). A screen that has ended and has no live loop is skipped. A live loop is adopted, and an
adopted loop that dies later gets up to 3 restarts. A script killed between a screen's end and its server stop is
covered by the next start's `stop_model.sh` or by the final one (line 102). `gpus_free` fails closed: empty input
gives one empty line, and text, too few lines or a high reading make awk exit non-zero. Every test is in an
`until`/`&&`/`||` context, so `set -euo pipefail` cannot kill the script. It runs from an installed copy, its state
directory exists before any redirect, and the limit is 100 MiB. Two residual minors, neither blocking. A crashed
loop's stale `loop.pid` whose pid the kernel reuses would be "adopted" and waited on forever; the driver guards
against this by checking the cmdline for `grpo_loop.py`, and the same guard fits `loop_alive`. Also, the copy still
calls the checkout's `arm_loop.sh`, `grpo_loop.sh` and `followup_arm.py` at each start, so no deploy should happen
until "every screen done". **Verdict: approve.**
