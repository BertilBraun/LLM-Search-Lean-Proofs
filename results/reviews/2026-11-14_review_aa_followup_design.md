# Review AA: design of the follow-up study (DESIGN.md, "Follow-up study: controlled arms", uncommitted)

Scope: whether steps 1-3 can answer Q2-Q4, fairness of the arms, statistics, cost. Read: the section; DESIGN.md's loop
sections where the section leans on them; `results/followup_step0/{throughput_and_hardware,pool,noise_floor}.md`
(`training_signal.md` did not exist yet; I read `experiments/analysis/training_signal.py`); the project report;
`rl/grpo_groups.py`, `rl/advantages.py`, `rl/loop.py` (`phase_due`, `keep_tree`), `rl/policy_trainer.py`
(normalization), `rl/loop_config.py`, `search/search.py`, `search/priority.py`, `configs/grpo/{loop,phase}.toml`.

Code claim checked: **no policy signal from unsolved trees holds.** `policy_groups` skips every node whose class is not
`NodeClass.PROOF_GRAPH` and `require_policy_proof = True` drops groups without a policy sample on the graph. With
mu = 0 (`value_share`), an off-graph state's G is 0, so (1 - lambda) = 85% of A's anchor reward is the same 0/1 "reached
the proof graph" that B2 uses. A differs from B2 only by delta = 0.2 per step of progress, the 15% local term, the
within-block costs (c = 0.1) and where in the sample the credit lands. C trains the positive half of the same groups.
All four signals are filters on the same object. Q2 is therefore "shaped against unshaped credit inside solved trees",
not "dense against sparse".

## Must change before running

1. **The probe's 1,800 s wall cap will bind on this node and make solve rate depend on Lean CPU** ("Probe v2": "wall
   cap 1,800 s per problem (as loop.toml)"). In the old run's Lean-bound phases a search spent 54 s in Lean plus 13 s
   waiting per expansion, so 16 expansions took ~1,070 s. That was with 81 Lean cores. With ~50 cores Lean latency
   rises ~1.6x, which puts the median unsolved search near 1,600 s and the heavy tail over the cap. Standalone at
   concurrency 112 and ~1 expansion/s it is 112 x 16 s = 1,790 s for every search. Trained policies used 2.6x more Lean
   per expansion (20 -> 52 core-s), so the cap would cost later checkpoints, and arms that learn heavier tactics, solves
   that the expansion budget allows. That is a compute confound inside a comparison at equal expansions. **Change:** use
   7,200 s for every probe run (the cap is only an emergency stop). Fix one concurrency and one GPU layout for all
   evaluations. Accept a run only if wall stops are < 1% of statements, and report stops by stratum.
2. **Step 3's control must be B2, not "the one whose probe result differs more from A's".** B1 keeps the progress and
   wasted-tactic costs: it is graph credit spread over the sequence, not outcome-only. The outcome row "per-tactic
   credit beats the outcome-only control: the labels add signal beyond which samples reach a proof" is only tested by
   B2. Picking the control that differs more from A is selection on noise when both differences are ~1 point, and it
   can silently switch Q2 to "per-tactic against per-sample shaping". **Change:** B2 goes on unless it is shown broken
   (check 9) or collapses; B1 is reported as a step-2 result only. If the owner keeps the decided rule, the outcome
   table must say which contrast step 3 answers.
3. **The step-2 gate reads the least informative point of the trajectory, and the "C replaces B" rule reads step
   size** ("Gate", "First two arms"). The old run's largest gain was generic and early: +11.6 points on a third by v2,
   before any shaping could compound. One round from v0 will mostly show that generic gain for every signal, so "all
   within 3 points" is the likely outcome whether or not the signals differ over 16 phases. The section's Risks list
   says this; the gate does not use it. One SFT epoch at 1e-4 (C) is a far larger step than one GRPO pass with 5 warmup
   steps, so "C ahead after one round" says nothing about C against A over 16 rounds. Yet the rule would drop the
   outcome-only control, the one baseline the project lacks (report, gap 2). **Change:**
   - (a) The gate table shows every variant against v0 (the rule, paired). A variant that did not move >= 3 points from
     v0 counts as "step too small", never as "equal".
   - (b) Beside the gate, show A-vs-B2 agreement on the shared trees from `training_signal.py`: the share of trained
     tokens whose advantage has the same sign under both, and the correlation of sample advantages. If agreement is
     >= ~95%, tell the owner that a closed-loop A-vs-B2 pair is unlikely to separate. Do this before the $70-135 is
     spent, not after.
   - (c) Step 3's first two arms are A and B2 whatever step 2 says about C. C is the third arm.
4. **The Q2 null and the policy/value split need a frozen-policy reference.** "No two arms differ: the gain comes from
   searching and filtering" cannot be read without knowing what the arm's value model alone gives. Each arm also
   co-trains its own value model. The planned "phase 16 with value v0" isolates the policy only one way. **Change:** add
   one probe run per step-3 arm: v0 policy with the arm's phase-16 value model (~5 h, ~$4.5 per arm). With the existing
   runs this gives a 2x2 (policy v0/arm x value v0/arm). That is the cheapest substitute for a value-only arm.
5. **Pin the decision rule's endpoint, threshold and limits now** ("Rule for 'two arms differ'", placeholders).
   `noise_floor.md` exists and gives the numbers:
   - Threshold 3 points; two runs for v0 and each final checkpoint; ~2.6 points detectable with one run.
   - Primary endpoint: phase 16, two runs pooled. Phases 4 and 8 are descriptive only (three checkpoints times up to
     6 arm pairs otherwise gives many looks).
   - Say before step 3 what a second seed can confirm. By noise_floor §5, a difference under ~5 points cannot be
     confirmed with two seeds, so 3-5 points stays "provisional" for good. The owner should know this before paying for
     seeds.
   - Fix what an arm stopped at its first collapse contributes: compare at the last checkpoint both arms have, and
     report the stop itself as the arm's result.
6. **Choose learning rates off probe v2, and make "tie" real** ("Choices": "best rate by probe solves (a tie: the lower
   rate)"). Choosing on the probe that later judges the arms biases each signal's best rate upward by ~0.8 points (max
   of 3 at ~0.93 points paired SE), less for C (2 rates). An exact-tie rule picks the highest rate whenever noise says
   so, and a hard stop at the first collapse turns a too-high rate into a lost arm. **Change:** rank rates on the held-out
   states plus the old gate's 402 statements (disjoint from probe v2, ~1/5 of a probe run each). Treat rates within
   3 points as tied and take the lower. Run probe v2 only for each signal's chosen rate: 5 runs instead of 13, saving
   ~30-50 h ($25-45) and the selection bias.
7. **Q3's expansion caps will bind before the token cap** (step 1 runs 3-4 and the miniF2F row).
   - At ~170 tokens per no-reasoning block, T = 27k is ~160 expansions on average. Statements with shorter samples
     reach the "up to 256 expansions" cap first.
   - At miniF2F's T64 (~109k) the no-reasoning run needs ~640 expansions, and the row gives no expansion cap at all.
   - Once the expansion cap binds, the runs are no longer equal in tokens.
   - **Change:** max_expansions >= 4x the expected count (1,024 at 16, 4,096 at 64). Report per statement which limit
     ended the search (tokens, expansions, depth, wall).

## Should change

8. **Cost: about 60% of the money is evaluation, while the GPUs mostly wait on Lean.**
   - My per-run estimate is 4-6 h. The probe is harder than the old one (37% vs 41% for v0, 70% at 1,000-4,499
     characters), so expect ~17-18k tokens per statement, not 15.6k.
   - Step 1 is ~45-75 h, with run 4 alone 10-25 h: ~10x expansions at 7-17 Lean core-s each, plus 10x value calls. The
     section's "runs 1-6 ~20-40 h" undercounts it.
   - Step 2 is ~60-90 h and step 3 ~65 h per arm, of which ~27 h is evaluation. Total ~240-300 h, $210-270.
   - The progress file's "$30-45 per arm" and step 2 "$40-60" disagree with the section's own figures.
   - **Changes** (keep every answer, save ~55-75 h):
     - Item 6.
     - Phases 4 and 8 on a fixed stratified half of the probe (1,000; curves only).
     - Runs 7-9 only if runs 5-6 leave Q4 ambiguous. The step-3 2x2 covers trained policies.
     - Runs 3-4 first on a stratified 500. Extend to 2,000 only if |difference| < ~5 points. The prior effect is +14
       per expansion.
     - In the throughput test, time a probe slice on 2 vs 4 GPUs. If within ~10%, run every evaluation on 2 GPUs (one
       fixed layout) beside the GPU-only jobs: step-2 and expert-iteration trainings.
9. **Cheap checks that catch a broken arm early** (none in the section):
   - WP3's B2 advantages against `training_signal.py`'s "outcome" scheme, per sample on the same shared trees: two
     independent implementations must agree.
   - Each step-3 arm's phase 1 against its own step-2 round on v0 trees: trained sequences, tokens, steps and groups
     with signal within ~+-30%. Anything else is a config or credit bug, not a result.
   - A WP1 smoke loop with B = 200k across a restart before any arm.
   - Calibrate the "none" search's `automation_log_probability` on the gate set, not on run 1 (that is probe v2).
10. **Expert iteration's window 4 repeats every block in 4 consecutive rounds, about 4 epochs.** Round 1 found that 2
    epochs forgot. Step 2's W = 4 is one round over 4x the data, so it cannot see the repetition. It also gets 4x the
    tokens of every other variant, and slices by finish order are not exchangeable (later = longer searches), so the
    screen favours W = 4 for reasons absent in the loop. **Change:** emulate both windows at step 2 as four successive
    rounds continuing the adapter, W = 1 over slices {1},{2},{3},{4} and W = 4 over {1},{1-2},{1-3},{1-4}. They then
    differ only in repetition. That is ~2-3 h of training plus two evaluations.
11. **Unequal optimizer steps and anchors** ("Ways the arms could differ").
    - A trains every group where any tactic advantage is non-zero, which includes groups split only by the 0.015-scale
      local term. B2 drops groups where all samples agree. So A takes more 64-sequence Adam steps per phase at the same
      rate. Round 1's rate sweep compensates only at round 1.
    - D with a moving KL reference is A + C + a different anchor. **Change:** D keeps v0 as its reference, so that D is
      exactly A + C.
    - Log per phase: steps, the KL term's share of the loss, and replay tokens. If A's steps exceed B2's by > 1.5x,
      say so beside any A-B2 difference.
12. **Drift and order.** Evaluations are standalone and sequential over ~10 days, and a node may be replaced. **Change:**
    alternate the arms' evaluation jobs (A4, B4, A8, B8, ...) and rerun v0 once at the end (~5 h). Record the node, Lean
    and vLLM identity per run.

## Minor

13. Runs 1-2 use the default `max_depth` 16 (`visible_student_v2.toml`), while run 3 uses 32 and a 7,200 s cap.
    Compare run 4 with run 3 only, never with runs 1-2.
14. At concurrency 112 and ~1 expansion/s, a 48-expansion training search takes ~90 min. At each pause ~112 searches
    holding ~4-5M tokens (~1/3 of B) are in flight, so a third of each phase's trees are mostly one version stale.
    This is the same for every arm, but log it per phase; it also makes C's W = 1 effectively ~1.3 phases.
15. miniF2F-valid has 244 statements, so differences between arms under ~7 points are unresolvable. Use it against v0
    only.
16. Q4's null is limited to 16 expansions: "none ~ v0" there does not mean the value model is useless. The outcome
    table should say "at this budget".
17. C's replay (40% of completion tokens, no KL penalty) and GRPO's (NLL weight 0.1, KL 0.01) differ. A C-over-A result
    is "recipe over recipe"; word it so.

## Verdict

The structure is right (shared trees, paired probe, pre-set rule, staged spending), and Q3 and Q4 at v0 are answerable
at step 1 once items 1 and 7 are fixed. Q2 is at risk as written, for three reasons:
- the gate reads one round, where the signals are least distinct;
- the control can be swapped for a graph-credit variant (B1) or for C;
- the code confirms that A and B2 share ~85% of their reward, so a closed-loop difference is likely small, and below
  ~5 points a single seed cannot confirm it.

Fix items 1-7 (text and config, plus one probe run per arm), and read the offline A-vs-B2 agreement before spending on
step 3.

## Re-review (revised section, 2026-11-14)

Must items:
- **Item 1: resolved.** Wall cap 7,200 s, fixed concurrencies from the throughput test, nothing running beside an arm,
  runs accepted below 1% wall stops by stratum.
- **Item 2: resolved.** B2 is the closed-loop outcome-only control and B1 is labelled as graph credit spread over the
  sequence; the owner still has to confirm.
- **Item 3: partly resolved.** (a) and (b) are in: every variant is shown against v0, "step too small" is not read as
  "equal", and the offline A-B2 agreement and the cross-check sit beside the gate. (c) is not: the first pair is left to
  the owner (A-B2 or A-C). That is acceptable now that A-C is labelled "recipe against recipe". It also matters less
  than I thought, because C's one-slice round is only ~8 optimizer steps, so step 2 does not favour C by step size.
- **Items 4, 5 and 7: resolved.** Item 4 is the 2x2 with the frozen-policy run. Item 5 pins the endpoint, the 3-point
  threshold, the under-5-points two-seed limit and the rule for a stopped arm. Item 7 sets the caps at 1,024 / 4,096
  expansions and depth 64, with the ending limit reported.
- **Item 6: resolved,** with a side effect (N1).

New problems (none blocks step 1):
- **N1.** Rates are ranked on 402 statements plus the held-out states. On the 402 a single paired run has an SE of
  ~2 points, so "within 3 points = tied, take the lower" will usually pick 2e-5. That is the rate the section says
  "moves little", so the gate's "step too small" verdict becomes more likely by construction. Also say how the two sets
  combine when they disagree. Cheapest fix: break the tie on the held-out states' valid-Lean and success, which are
  paired per state and resolve ~3 points; take the lower rate only when both sets tie.
- **N2.** With `depth_weight = 0`, run 3 changes the tuned visible search, not only the no-reasoning one. Read run 3
  against runs 1-2 as a check: if run 3 is >= 3 points below run 1, the setting handicaps visible reasoning, and Q3 has
  to be reported with that caveat (or rerun at 0.25 in both modes).
- **N3.** The miniF2F T64 visible-vs-no-reasoning pair costs ~150k no-reasoning expansions (~5-12 h). On 244 statements
  it cannot resolve less than ~7 points, which contradicts "miniF2F against v0 only". Run it only if run 4 differs from
  run 3 by >= 5 points.
- **N4.** E (groups at off-graph nodes, judged by local labels only) brings back the conditions of the phase 1-10
  reward hacking. If the owner wants it, it needs its own step-2 round and a habit-metric check before any closed loop,
  not a direct arm.

Deliberately not applied (evaluations beside training jobs, the four-round window emulation, half probes): none is a
blocker. **Step 1 may start** once the throughput test has set the concurrencies and WP0's evaluation tool has landed.
