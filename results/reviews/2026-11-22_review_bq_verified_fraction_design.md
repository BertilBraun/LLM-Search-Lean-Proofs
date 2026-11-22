# Review BQ: `verified_fraction` credit and the F screen (design)

Reviewed: the uncommitted diff (`grpo_groups.py`, `advantages.py`, `policy_data.py`, `training_phase.py`,
`families.py`, `run_screens.sh`, README "Progress fraction"), `screens/F_2e-5.toml`, `tests/rl/test_verified_fraction.py`
(13 passed in WSL), and `results/followup_progress.md` (owner 2026-11-22, V's probe, V's per-phase table).

## Verdict

**Run the screen; amend the judgment rule before phase 8.** The credit fixes the direction of V's short-block
incentive and is hard to pad. Its cost is a smaller gradient (a lower effective learning rate at the same 2e-5), which
makes the pre-registered comparison of F at phase 8 with V at phase 16 lean further against F. A pass is
convincing, but a fail tells us little. Findings 2 and 5 are the ones to act on. None of them blocks the launch.

## Findings, ranked

### 1. It fixes the direction, and what the policy now optimizes is well defined (high, positive)

- Within a group `node_steps` (n) is fixed, so maximizing E[r] means maximizing E[steps gained · 1{clean, ends on
  graph}]: the expected verified distance one block covers. This is normalized potential-based progress
  (Φ(s) = −d(s)/n, r = Φ(s') − Φ(node)). Along a found proof the blocks' fractions sum to about 1, and closing is just
  covering all n steps, so closing earns no bonus beyond what its length already pays.
- The measure is graph distance on the block's **last state**, in units of the shortest found proof, not the block's
  own tactic count. That makes padding unprofitable: no-op and redundant tactics zero the block. Splitting
  `rw [a, b, c]` into three lines gains no distance, and a sideways detour that returns to the graph gains only the
  net distance.
- At node_steps = 1 F equals V: any clean closer earns 1, and block length has nothing to fix there. At
  node_steps = 2 a one-step block now earns 0.5 against 1 for closing.
- At a root with large n, the 1-step winners that V paid in full now earn 1/n, while a whole-proof block keeps 1.
  That removes the push behind V's 1.9-tactic blocks exactly where the probe's 5.7% within one expansion comes from.
- Caveat: the length ordering inside a group exists only when **two or more samples of different lengths end on the
  graph**, typically a shorter sample whose state is an intermediate state of a longer on-route sample. In a group
  with one lone winner, F only rescales V's signal by k/n. How often the first case occurs is unmeasured. Log it
  (finding 5).

### 2. The gradient shrinks, so the run moves more slowly at 2e-5 (high)

- Advantages are r − mean with no std normalization. So a group's total |advantage| scales with its winner's
  fraction: about 1 near the proof, about k/n at the root.
- Groups near the proof (small n) now carry most of the gradient. As finding 1 says, that is the intended effect at
  the root. The side effect is that the mean |advantage| per trained token falls below V's, which acts like a lower
  learning rate. The parameter change per phase (V: 2.3-2.7%) will probably drop.
- Across depths the variance is p(1−p) ≤ 0.25 at n = 1 against about 0.01 for root groups whose winners cover 0.1-0.3.
  So root groups weigh about 5-25x less than under V.
- This compounds finding 3: F at phase 8 has had both half the tokens and smaller steps.
- Do not "fix" this with per-group std normalization or by dividing by the group's best r. Either would scale a
  root group's lone 1/n winner back up to V's weight and bring back the short-block push. If the parameter change
  per phase falls well below about 2.5%, raise the learning rate in a later run and leave the credit alone.

### 3. The judgment rule is biased against F; add a conditional phase-8 comparison point (high)

- The rule compares F8 with V16: half the tokens, a value model trained 4 times instead of 8, and smaller steps
  (finding 2).
- A paired 95% interval above 0 needs F8 at roughly V16 plus 2 points, about 930 of 2,000. F would have to gain more
  over v0 in 8 phases than V did in 16.
- Pass means F is better. Fail does not separate "worse credit" from "fewer phases": nobody knows V's probe at
  phase 8. V's held-out success was flat from phase 8 to 16 (39.3% → 40.1%), but held-out and probe disagreed for V,
  so the probe at 8 cannot be inferred.
- The plan already budgeted phase-8 probes for every arm (plan row 6, "phase 8"). V's version 8 exists: the extension
  restarted servers on it. Check on the node that its policy adapter and phase-8 value model are still kept.
- C8 is not needed. The F-versus-C question is settled at 16 phases anyway, and C8 would only add a second
  equal-token reference.

**Proposed rule (pre-register before F's phase 8):**

1. Probe F8 (as planned).
2. **Extend F to 16** if F8 > V16 (paired 95% interval above 0). This is the pre-registered pass.
3. Otherwise **probe V8** (about 2.5 h, bought only in this case). **Extend** if F8 > V8 (paired interval above 0) and
   F8 solves at least v0's 10.1% within one expansion. **Stop** otherwise. Report the per-expansion curves of F8, V8,
   V16 and C16 together.
4. A 16-phase F probe paired against C16 (1,049) settles F against C, as pre-registered. One run each detects about
   2.6 points (noise floor), so a difference under about 3 points needs a second run before any claim.

The extra probe costs nothing when F passes outright. When it does not, the rule spends 2.5 h to avoid wrongly
dropping F, or wrongly running 8.5 more hours.

### 4. Risky long blocks and failing tails: limited, but watch them (medium)

- A failing tail still scores 0, so a (k+1)-th tactic pays only if it succeeds with p > k/(k+1): 0.67 at k = 2,
  0.8 at k = 4. That is a mild push, not a cliff, so a return of A's failing-after-graph habit (35-41%) is unlikely.
- The search keeps a failing block's valid prefix, yet F scores the whole block 0. The credit is therefore stricter
  than the search needs, and blocks may lengthen less than hoped.
- Length is paid only when the longer block agrees with the found route. A long clean block that takes another valid
  route ends unknown (left out) or explored off the graph (0). The unscored share was already 29.7% at V's phase 16
  and may climb faster under F, which would shrink the groups trained.

### 5. Log these per phase (medium; cheap, from data the phase already has)

The rule needs items 1 and 2, and they are the cheapest to add: both come from the phase's own groups, at no extra
Lean cost.

1. **Root-group closing rate**: the share of root-node samples, with node_steps = the tree's root steps, that close
   the goal. This is a free in-training proxy for the probe's "solved within one expansion", unlike the held-out
   states, which are intermediate.
2. **Fraction among positives** (mean r given r > 0) beside the positive rate. As written, `mean_verified_fraction`
   averages the zeros in too, so it mixes the two: "mean fraction" and "verified progress rate" can move in opposite
   directions.
3. **Within-group length signal**: the share of trained groups with two or more distinct positive r values
   (finding 1's caveat).
4. **Gradient mass by node_steps bucket** (1, 2, 3-4, 5+): sum of |advantage| × tokens, and groups trained.
5. Tactics per complete block (already charted): its distribution (median and p90), not only the mean. Target above
   2.5, against V's 1.9 and A's 4.0 drift.
6. Already on the table, to read against V: failing after graph, unscored share, parameter change (finding 2), bare
   `have`.

On held-out, add "closed within one block" per phase if it is cheap. It does not replace item 1.

### 6. Minor

- `F_2e-5.toml`'s comment points to README "Verified progress". It should also name "Progress fraction".
- Steps are counted as top-level tactics on the shortest found route. The assertion `0 < steps_gained ≤ node_steps`
  holds because a clean block on the graph is itself a forward route.

## Alternatives considered

- **r = 1 for closing, 0.5 for progress:** simpler and keeps V's scale at every depth. But it is only a 2x premium for
  closing, the same at every n, and it gives no ordering among progress blocks of different lengths. F's linear
  share is better founded (potential-based, additive along a proof) and pays the root's whole proof n times a single
  step. **Prefer F.** Keep 1/0.5 as the fallback if F's gradient proves too weak even at a higher learning rate.
- **Normalizing by depth** (per-group std, or per-node_steps bucket): rejected for the reason in finding 2. It undoes
  the root down-weighting that removes V's incentive.
- **Crediting the prefix of a failing block** (for example half its fraction): closer to how the search uses
  failing blocks (finding 4), but it reintroduces "progress then fail pays", which the owner rejected. Not now.

## Re-review (2026-11-22, after the owner's run order)

Read: the updated "Owner, 2026-11-22" reading in `results/followup_progress.md` and the `F_2e-5.toml` comment.

**Verdict: ready to launch.** The order (C8 probe, then F8 with a probe, then F extended to 16 with a probe) fixes
finding 3 better than my conditional V8 probe. F8 against C8 compares equal tokens, and F16 against C16 still settles
F against C. Folding the scale caveat into the pre-registered reading covers finding 2. Leaving the metrics until
after the run is fine, as long as the trees stay on the node. The toml comment is fixed.

Check before launch:

1. **Script the hand-off from probe to extension.** `F_2e-5.toml` stops at `max_phases = 8`, and `run_screens.sh` and
   `arm_loop.sh` refuse a finished run, so V's extension was done by hand (`extend_V.sh`). "No idle GPUs in between"
   therefore needs a node-local chain that runs: F finishes, the F8 probe runs with F's phase-8 adapter and phase-8
   value model, then the extension starts. Put it in place now, or the GPUs idle until someone steps in. Also confirm
   that the phase-8 adapter and value model are kept and that the probe reads version 8, not whatever is latest.
2. **The extension matches V's, not C's.** Searches cut at the phase-8 finish restart fresh, as V lost 2.3M tokens.
   F16 is therefore produced the same way as V16 but not as C16, which ran 16 phases without a break. This is minor;
   note it beside F16 against C16.
3. **Fix the caveat's wording.** It says F's advantages are V's "scaled down by about the node's remaining steps".
   More exactly, they are scaled by the positive block's share k/n. They are unchanged at nodes one step from a proof
   and smallest at root nodes with long proofs. The conclusion (smaller update; a weaker F reads as inconclusive) is
   right.
4. **Make clear that F reaches 16 phases unconditionally.** With F extended either way, F8 no longer decides
   anything. If "F is worth 16 phases if F8 beats V16" still appears anywhere, mark it superseded so that F8 against
   C8 is read as a description, not a gate.
5. **Also watch failing after graph** (V: 6.7-14%) next to tactics per block. If longer blocks bring back failing
   tails, it shows there first (finding 4).
6. **Keep the trees.** Keep F's per-phase trees for all 16 phases until the root-closing share and the share of
   groups with two or more different positive rewards are computed, and before the node is released. Both need the
   graph labels (node_steps), not only the records already pulled to the PC.
