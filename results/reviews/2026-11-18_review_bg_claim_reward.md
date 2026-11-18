# Review BG: the claim switches for arm A's bare-have drift

Branch `bare-have-claim-switches`, head 2e54601, on master 7109590. The focus is study design: is the target right, is
removing δ for claim steps principled, is 0.3 chosen soundly, what should the rerun watch and when should it stop,
does D stay "A plus rounds", is the health-check change right, and the explanation-length question.

Read:
- the branch diff and `experiments/analysis/bare_have_credit.py`;
- the replay outputs (`scratchpad/bh/replay3_{v0,A,lr2e5}.{md,json}`, `measure_*`);
- `src/lean_search/rl/README.md` ("Claims"), `results/grpo_loop_v1/README.md` (the old drift), `results/followup_progress.md`.

Checks run:
- In WSL, against the worktree's `src`: `tests/rl/test_claim_progress.py`, `test_phase_signals`, `test_followup_arms`,
  `test_advantages`, `test_token_credit`, `test_loop_health`, `test_health_across_arms`, `test_learning_rate_step`,
  and `tests/graph/test_claim_progress_groups`, `test_tactic_labels`, `test_grpo_groups`, `test_reward_replay`,
  `test_block_habits`. 729 passed.
- `ruff check` and `ruff format --check` over `src`, `experiments` and `tests`: clean.
- I recomputed the class shares and per-sample advantages below from the replay JSON.

**Verdict: merge, and rerun A, but with a written stop rule.** The code is correct and well tested. Both switches are
off by default, the golden loop only gains four empty threshold fields, and C refuses them. `claims_earn_progress =
false` is a principled change. The like-with-like health comparison is right. My doubt is about what the replay
shows: the fix moves the aggregate sign mostly by charging failed claims more. It hardly touches the subclass that
actually grew, and it leaves successful decompositions with most of their premium. So the drift may slow rather than
stop. The rerun is the test, and it needs agreed signals and a stop rule before it starts (S1, S2).

## What the replay says, recomputed

Shares of all openings (on the proof graph "G", off it "-"), phase reward, from the replay JSON:

| Phase | bare, proved in block, - | bare, proved in block, G | bare, open, never proved, failing after, - | `have … :=`, - | `have … :=`, G |
|---|---|---|---|---|---|
| v0 | 4.7% | 5.2% | 3.2% | 5.2% | 4.6% |
| A1 | 4.0% | 4.7% | 3.3% | 4.1% | 3.0% |
| A4 | 9.5% | 6.0% | 6.6% | 5.8% | 2.7% |
| A6 | 10.1% | 6.5% | 5.8% | 6.4% | 3.0% |
| A7 | 8.4% | 6.0% | 5.7% | 6.7% | 4.8% |

Mean sequence advantage per sample:

| Phase, reward | bare, proved in block, G | bare, proved in block, - | bare, open, failing after, - | other opening, G |
|---|---|---|---|---|
| A1 old | +0.91 | −0.42 | −0.45 | +0.38 |
| A1 fix | +0.79 | −0.42 | −0.57 | +0.38 |
| A4 old | +1.26 | −0.36 | −0.37 | +0.38 |
| A4 fix | +1.06 | −0.34 | −0.45 | +0.38 |
| A7 old | +1.19 | −0.40 | −0.40 | +0.30 |
| A7 fix | +1.00 | −0.38 | −0.48 | +0.31 |

- **The growth was mostly off the proof graph.** Bare blocks that prove their own claim off the graph went from 4.0%
  to about 10%, and bare claims left open and then followed by a failing attempt from 3.3% to about 6%. Bare blocks
  proving their claim on the graph stayed near 6%.
- **The growing classes were already negative under the old reward** (−0.36 to −0.45 per sample). They grew anyway.
  That is generalization: the explanation tokens of on-graph decompositions earned +0.9 to +1.3 per sample, about 3x a
  direct opening's, and the style spread to states where it does not help.
- **The fix trims that premium by about 15%** (+0.79 to +1.06, still 2.6-3.3x a direct opening) and makes open
  claims about 0.1 more negative. It leaves the largest growing class, off-graph claims proved in their block,
  practically unchanged (−0.42 → −0.42; −0.36 → −0.34).
- **So the aggregate goes negative mostly through the failure classes.** The removed claim δ contributes about
  −14k per phase, the 0.3 cost about −7k.

## Blocking

None.

## Should fix (before or at the rerun's start)

**S1. Write down the rerun's watch list and stop rule now.** The aggregate class sign is a weak proxy for the
mechanism above. Whether the drift stops is decided by the first 3-4 phases, about 5 hours of A.
- Watch these per phase, from the block habits the loop already logs plus the replay script on each phase's trees
  (CPU only, a few minutes per phase):
  - the share of bare-`have` openings (all statements and below the band);
  - its two growing subclasses: off-graph claims proved in their block, and open claims followed by a failing
    attempt;
  - `obtain`/`suffices` and `have … :=` openings, the likely substitutes. `suffices` keeps its δ; only claims adding a
    goal lose theirs;
  - claims proved;
  - the per-sample advantage of on-graph decompositions against direct openings;
  - mean explanation tokens;
  - held-out valid and success against v0.
- Suggested stop rule: stop and reassess if, by phase 4, the bare-`have` share has risen by more than 5 points over
  the rerun's phase 1 (the first run rose about 12 points in 6 phases), or either growing subclass has grown by more
  than 1.5x.
- The health alerts are warnings that act on nothing, and the bare-`have` one fired only at phase 6 in the first run,
  under either comparison. So this has to be the orchestrator's check after phases 2 and 4, agreed with the owner
  beforehand.

**S2. The cost of 0.3 is chosen in-sample, with thin margins in two places.**
- The candidates were 0.1, 0.2 and 0.3. The criterion was the smallest cost that makes the class sum negative on the
  same ten phases it is evaluated on. All ten come from policies trained under the old reward, which is exactly what
  the rerun changes.
- At 0.3 the margins are −3.8k (v0) and −1.6k (A5) on class sums of ±20-30k. At 0.2 both are positive. So the
  criterion sits on its boundary at the very phase (v0) the rerun's phase 1 will replay: phase 1 is sampled by v0.
- This is not a reason to change 0.3. It is a reason to treat it as provisional: confirm the sign on the rerun's own
  phases 1-3 with the replay script (S1), and do not read the replay as a prediction.
- One cheap improvement: hold one run out (e.g. the 2e-5 run's two phases), choose on the rest, and report the
  held-out result.

**S3. No per-band evidence that decompositions on long proofs keep their reward.** The replay does not split by
difficulty, so I could not check the bands. The question matters because long proofs (the 3,000+ character bands) are
where `have` chains are the natural style. In those statements, removing the claim's δ and raising the open-claim cost
falls most on legitimate decompositions.
- Fix: add a split by the statement's proof-character band (the trees record their difficulty) to
  `bare_have_credit.py`. Run it on A1-A7 and v0 for the old reward and the fix. Report, per band, the on-graph
  self-proved decomposition's per-sample advantage against a direct opening's, and the bare class's sign.
- If the fix makes on-graph decompositions in the top bands worse than direct openings there, the δ removal is
  over-correcting where it matters.
- This can run on the node's CPUs beside the rerun's first phases only if it is light. Otherwise run it on the PC from
  pulled trees, or before the rerun.

## Nits

**N1. The README's two kinds of per-sample number are hard to tell apart.** The README quotes +0.22 to +0.30 per
sample for self-proving bare blocks and +0.9 to +1.3 on the proof graph. From the JSON, the on-graph per-sample
sequence advantage is +0.9 to +1.26 old and +0.79 to +1.06 with the fix. State which numbers are all samples and which
are on-graph only, so the premium after the fix is visible: "self-proving decompositions stay positive" is true, at
2.6-3.3x a direct opening.

**N2. Below-band thresholds can come from very few samples.** With one reference phase (`reference_phases = 1`), the
reference's below-band subsample is about 35% of feeds. For `max_below_band_unproved_claim_after_proof_graph_share`
the phase's below-band count is checked (`min_proof_graph_samples`), but the reference's is not. A threshold from a
thin reference subsample can be noisy. Gate the below-band limit on the reference's count as well.

**N3. "Groups unchanged" is the right guard but says little about the size of the update.** Report the summed
absolute advantage too (the positive proof-graph mass falls 2-5.5%), so a fall in signal strength is visible next to
the unchanged groups.

## Points asked about

- **The target.** "The bare-`have` opening class net negative, self-proving decompositions positive" is the right
  direction. But as computed it is an aggregate over subclasses whose mix changes with the policy. On the old run's
  trees it would have predicted the drift (the old sums were positive). It does not show that the fix stops the
  generalization from on-graph successes (above). A sharper target is per-state: the self-proving decomposition's
  advantage relative to a direct block reaching an equal proof-graph distance. I would add that as a reading, not
  replace the current criterion.
- **Removing δ for claim steps.** Principled. Stating a claim is always valid in Lean and does no proof work; it only
  appears on the shortest route when the proof uses it. Counting it as one flattened step paid δ for free.
  - With the switch, a decomposition and a direct proof doing the same work earn the same δ to completion: `have … :=
    by p` counts as p's steps, as a term-mode `have` does.
  - It is capped at one step, never below 0, and dropped rather than deferred. The tests cover the anchor, later
    claims, flattened `have … := by` and `obtain`.
  - The asymmetry to watch is `suffices`, which keeps its δ, being a claim that replaces the goal rather than adding
    one (S1's watch list).
- **0.3** (S2): sound as a provisional choice, in-sample and on its margin at v0.
- **D stays "A plus rounds".** Yes. D's overlay gets the same two lines (test-pinned), its GRPO is A's, and C refuses
  reward keys. One consequence for the write-up: A and D now train under a reward that differs from grpo_loop_v1's and
  from the one step 2's rate was chosen under. The positive mass falls 2-5.5%, so the 5e-5 choice still stands, but
  say it.
- **The health-check change.** Right. Below-band is now compared with the reference's below-band limit, else every
  statement with every statement's. The README's numbers show the old mix (16.8% → 26.6% against a 30.8% all-statement
  limit) let the below-band rise pass. Same golden behaviour otherwise.
- **The explanation length (open question 2).** The trainer's loss is a token sum over a constant normaliser (n x 256,
  `policy_trainer.py:680-702`). That is the unbiased REINFORCE gradient: each token gets the same push per unit of
  advantage, and a sequence's log-probability moves with its length because it has more tokens.
  - A per-sequence length normalisation, as in original GRPO, reintroduces the known length bias: long negative
    samples are under-penalized per token, and long outputs grow.
  - So I would not add a trainer-side normalisation. "Long explanations are paid more" in the replay is a property of
    the token-summed metric, not a bias of the update.
  - The real lever is the credit itself: the explanation gets the whole sequence advantage. The watch is the mean
    explanation tokens per class (S1), with the existing 0.5-2x alert.

## Questions for the owner

1. **The stop rule for the rerun** (S1): stop and reassess at phase 4 if bare-`have` openings rose more than 5 points
   over phase 1, or a growing subclass grew more than 1.5x? Or another threshold?
2. **If the drift continues under the fix:** the next lever is either less credit for the explanation tokens of
   multi-tactic decomposition blocks, or a cost for claims proved in their block but off the proof graph (useless
   lemmas, the main growing class). Do you want one of these prepared now as an off-by-default switch, replayed like
   these two, so the rerun can be restarted the same day?
3. **Is v0's own bare-`have` rate a floor?** With the fix the class is already negative on v0's phase, so the rerun
   will push bare openings below v0's ~20%. Do you accept that as a side effect, or should the target be "no growth"
   rather than "net negative"?
