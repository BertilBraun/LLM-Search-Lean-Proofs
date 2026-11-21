# Review BO: verified-progress credit and its screen (design)

Scope: the uncommitted change (`GroupSample.verified_progress`, `CreditMode.VERIFIED_PROGRESS`, `PolicyDataMetrics`
fields, `screens/V_2e-5.toml`, `run_screens.sh`), README "Verified progress", progress "Owner, 2026-11-21: a
verified-progress screen before D" and the screens' results and rule. `tests/rl/test_verified_progress.py`: 20 passed.

## Findings, ranked

### 1. Must fix before the run: the two new metrics are never recorded

`mean_verified_progress` and `unscored_progress_share` are computed in `policy_data.data_metrics` but not copied into
`GrpoPhase` (`training_phase.py` around line 539 copies only the four proof-success fields; `monitoring/families.py`
line 353 has no verified-progress fields). The README's sentence that they "record the mean r and the share left
untrained" is false today, and the screen would run 8.5 h without its own diagnostics. Add both to `GrpoPhase`, and
compute them over **all** groups' samples, as `mean_proof_success` is: over trained groups only, the mean r is
conditioned on the group having mixed r, so it cannot show learning. Worth adding a third: the unscored share among
complete forward samples (how much of the valid output is left untrained). `mixed_reward_group_share` (groups trained)
is already logged.

### 2. Residual exploits: a block ending on a claim, and wasted tactics before the last one

`verified_progress` judges only the **last** tactic and `complete` (no FAILING or MASKED). Two consequences:

- **A block ending on a bare `have h : A` scores 1** when the search's proof later went through that state (the state
  after the claim is on the proof graph one step closer). The README's "r = 0 for ... an open claim" holds only for
  claims the tree never proves (`UNPROVED_CLAIM`). A bare claim is the safest single step there is (it rarely fails in
  Lean), and the search's later expansions do the proving. This is the inverse of `claims_earn_progress = false`, which
  the owner adopted for A after the bare-`have` drift (V's base keeps the default `true`, though that switch does not
  touch V's r anyway). The phase 7-8 guard (bare `have` at most 22%) will catch it, but only by failing the screen.
- **Wasted tactics before the last one are free.** A redundant `have`, a no-op, or an unproved claim in the middle of a
  block that ends closer on the graph still gets r = 1, and its tokens are pushed up. The README's "a redundant or
  sideways step" scoring 0 holds only for the last tactic. The tests cover these labels only as single-tactic blocks.

What it does remove: failing tails (any FAILING/MASKED gives 0; B2 paid them r = 1 in 23.5% of its r = 1 samples,
review AF), lengthening (binary r: a 5-tactic block on the graph earns what a 1-tactic one earns, against A's δ per
step), never-proved claims (0), and progress followed by an unverified continuation (untrained, where B2 paid it).

### 3. Pressure toward one-tactic blocks; A's δ against "closer than the node"

A paid δ = 0.2 per step gained, so more steps on the graph paid more (the lengthening route) and a detour lost δ. V pays
a 1-tactic prefix of the found block the same as the whole block or a full proof, and any failure costs everything, so
the expected r of a k-tactic block on the route is roughly p^k: the optimum is the shortest safe step. Closing a goal
earns no premium. This is not a reward hack (every r = 1 is a verified step of a found proof), but it can lower held-out
success if shorter blocks need more expansions than the budget allows. The tactics guard is one-sided (at most 3.0);
v0 sits at 2.55-2.70. Do not add a lower bound now (the rule is pre-registered), but report tactics per complete block
and treat a fall below about 2.0 together with falling success as the failure mode, not noise.

"Closer than the group's node" also zeroes a valid step onto the graph that is not on the shortest found route
(sideways), and an explored alternative (OFF_GRAPH): both get the same 0 as a Lean error. Under A they sat at about
−0.075 against an error's −0.15; V drops that distinction. Acceptable for a binary reward.

### 4. Untrained samples change the step size at the same 2e-5

A sample without r stays in `sequences` with every token untrained. `plan_grpo_steps` cuts all sequences into steps of
64, and the normalizer is `len(step.sequences) * 256`, so untrained sequences add optimizer steps whose gradients come
from fewer trained sequences. Adam rescales per step, so V takes more, noisier steps per phase than A or B2 at the same
rate, by about 1/(1 − unscored share). That is a confound in a screen meant to differ only in credit. Either drop
sequences without a trained token before step planning (in A this is rare, in B2 it never happens, so it changes V only),
or at least compare the per-phase parameter change ("Change" column) with A's 3.0-3.4% and B2's 2.7-4.0%.

### 5. Hindsight: what leaving UNKNOWN untrained fixes, and what it does not

- UNKNOWN is a state never expanded, or expanded off the graph with live children and fewer than 4 expanded nodes in its
  subtree (`off_graph_min_expanded_nodes = 4`). OFF_GRAPH is a dead end or 4 or more expanded nodes without a proof.
  Siblings of the found route that the search never got to (the bulk of hindsight's false negatives in A and B2) are
  now untrained instead of pushed down. That is the main fix, and it is real.
- What remains: a valid alternative the search explored 4 or more nodes deep and abandoned when another branch finished
  first scores 0, like an error. For long statements, 4 expanded nodes is weak evidence. Groups exist only at proof-graph
  nodes of solved trees (`require_policy_proof`), so the bias toward statements the search solves is the same as in A,
  B2 and C, not new.
- The untrained share is probably large among valid blocks (old trees: unknown about 20% of group tactics, review T;
  "unknowns are mostly progress moves", review D) and small among all samples, since most r = 0 samples are failures
  (21% of sampled blocks complete in the A screen's phase 5 warning). Easy trees, solved in a few expansions, leave
  almost every sibling unknown; hard trees expand more and turn siblings into OFF_GRAPH zeros. So V is closer to "found
  step against Lean errors" on easy statements, and pushes harder toward the one found route on hard ones. Also, a group
  whose only progress sample failed later or ended unknown has no r = 1, so it drops out. V will train fewer groups than
  B2. Steering into unknown states is not an exploit (untrained earns nothing), but a drift there silences training.
  Log the share of groups trained and the unscored share (finding 1) and read them per phase.
- Cheap pre-check, optional: replay V's r on the A screen's phase-1 trees (v0 data) on the node to get the unscored
  share, the share of groups trained and the mean r before spending 8.5 h. `reward_replay.py` hard-codes `PER_TACTIC`
  in `has_signal`, so this needs a small change.

### 6. Is the screen fair under the same rule?

Same follow-up base, 2e-5, 8 phases, seed and curriculum, the same rule and guards: yes. A's claim switches and the
explanation cap are absent, but they do not act on this credit, as for B2. Two caveats belong in the report:

- V is a third variant chosen after two screens failed. A pass is a selection among three on one seed. The rule's
  16-phase run with stop rule and the paired probe must still decide, as already written.
- The guards still apply. "Failing after the graph" should fall well below A's 28-30%. If it does not, the credit is not
  reaching the policy, which is worth checking at phase 2, not 8. Bare `have` is V's most likely failure (finding 2).

### 7. Minor

- The diagnosis's third point ("sequence credit spread over reasoning tokens") is not changed by V: every sampled token,
  the explanation included, gets r − b̄. That is standard GRPO and fine now that r is clean. Say so rather than imply a
  fix.
- README: "an open claim" should read "a claim the tree never proves"; "a redundant or sideways step" should read "a
  block ending on ...".

## One concrete improvement (keeps the rule simple)

Score r = 1 only for a **clean** block: forward, no tactic anywhere labelled failing, masked, no-op, redundant or
unproved claim (`WASTED_LABELS` plus MASKED), and the last tactic does not add a claim (`not last.adds_claim`, a bare
`have`/`obtain` left open; a flattened `have h : A := by p` ends on p and still counts). Everything else stays: closer on
the graph gives 1, an unknown ending gives no r, otherwise 0. This is a few lines in `GroupSample.verified_progress` and
three parametrized tests. It closes finding 2 ahead of the guard and matches the owner's `claims_earn_progress = false`.
A block whose only new content is a claim earns nothing until a block proves something.

## Verdict

**Run the screen after fixing finding 1** (the metrics must be recorded and computed over all groups). Strongly
recommended before the start: the clean-block rule (finding 2) and either dropping untrained sequences from step planning
or reporting the step-size difference (finding 4). The design removes the failing-tail and lengthening loopholes of B2
and A and most of the hindsight push-down. Its remaining risks are the bare-`have` ending and a drift toward one-tactic
blocks; neither invalidates the screen. Under the unchanged rule it is a fair third screen, with the caveat that it is
chosen after the other two.

## Re-review (working tree, 2026-11-21)

Suites run one at a time: `test_verified_progress.py` 27 passed, `test_policy_data.py` 51, `test_token_credit.py` 21;
`tests/graph/test_grpo_groups.py` **1 failed**, 53 passed.

- **1 (metrics): fixed.** `mean_verified_progress` and `unscored_progress_share` are computed over all groups'
  samples. They and `unscored_sequences` (plus the cap's two counters) are copied into `GrpoPhase` in
  `grpo_phase_record`. Two test names still say "of the trained samples" (`test_verified_progress.py` lines 122 and 128);
  rename them. The unscored share among complete forward samples is not added; optional.
- **2 (clean block): fixed as proposed.** Forward, complete, no `WASTED_LABELS` tactic anywhere, `not last.adds_claim`.
  A wasted block ending unknown scores 0, which is right. The `if not self.tactics` guard is gone. `edge_tactics` always
  gives at least one tactic (an unparsed sample counts as one failing), so the change is fine. But `verified_progress`
  now runs for every sample under every credit mode in `data_metrics`, so a violated invariant would stop any arm's
  phase, not just V.
- **New, must fix (test only):** `test_trainable_groups_are_counted_with_the_phases_credit[verified_progress-0]`
  expects 0 trainable groups on `two_proofs_tree`, but the code gives 1. The code is right by the design: the root needs
  1 step, so `exact p` (closes, r = 1) and `intro` (onto the two-step proof, 1 remaining, sideways, r = 0) differ. The
  expectation was copied from proof success. Set it to 1. This case also shows finding 3: a valid step onto a longer
  found proof is pushed down.
- **3 and 7 (README): done.** The pull toward one-step blocks with its below-2.0 watch, the explanation tokens carrying
  the sequence advantage, and the clean-block wording are all accurate to the code.
- **4 (step size): fixed.** Samples without an r add no sequences (`PolicyDataParts.unscored`), so they add no optimizer
  steps and no KL tokens. They are counted only in trained groups, which is correct, since untrained groups add none.
  Still compare the per-phase parameter change with A's and B2's when reporting.
- **Not done:** the phase-1 replay pre-check (optional; the per-phase metrics now cover it from phase 1 on).

**Verdict: ready to run once the one test expectation is corrected** (and the full suite is green). No design
objection remains. At phases 1-2, watch the bare-`have` and failing-after-graph columns, tactics per complete block,
`unscored_progress_share` and the share of groups trained.
