# Follow-up study: summary (2026-11-14 to 2026-11-24)

The follow-up to grpo_loop_v1 asked two things: where the old run's in-pool gain came from, and which training signal
inside the closed loop (search, train, search again) works best when every arm gets the same compute. Details, every
table and every decision are in `results/followup_progress.md`; reviews AM to BU in `results/reviews/`.

## Answer in brief

- **Expert iteration (C), the best GRPO credit (F) and the two combined (D) tie.** After 16 phases (192M generated
  tokens each) they solve 1,036-1,059 of the 2,000 probe statements, against 714.5 for v0. Every pairwise gap among
  them is inside about ±2 points. The other GRPO credits are clearly worse: per-tactic (A) 822, verified progress (V)
  891.
- **The ranking holds on miniF2F-valid**, at about a third of the size: C16 172, F16 174, D16 172 of 244 against v0's
  158 (+5.7 to +6.6 points), all three tied with each other.
- **GRPO did not beat expert iteration, and adding it to expert iteration added nothing.** D (C's rounds plus F's GRPO
  step) against C at phase 16: −0.7 points [−2.5, +1.3].
- **The old run's v35 still leads in-pool by 9-10 points**, but it trained on about 2.4 times the tokens. On
  miniF2F-valid the three arms are level with it (170).

## Results at 16 phases

Probe v2: 2,000 held-out pool statements, 16 expansions, each policy with its own value model, one run each.

| Arm | Training signal | Solved of 2,000 | Against v0 (714.5), points | Solved within 1 expansion |
|---|---|---|---|---|
| C | expert iteration (SFT on found proofs, window 4, every phase) | 1,049 | +16.7 [+15.0, +18.5] | 13.1% |
| F | GRPO, progress-fraction credit | **1,059** | +17.2 [+15.4, +18.9] | **16.1%** |
| D | C's rounds plus F's GRPO step, every phase | 1,036 | +16.1 [+14.3, +17.9] | 13.9% |
| V | GRPO, verified-progress credit | 891 | +8.8 [+7.1, +10.4] | 5.7% |
| A | GRPO, per-tactic credit with claim switches and cap | 822 | +5.4 [+3.7, +7.1] | 9.7% |
| v35 | old run, final policy and value model, ~458M tokens | 1,236 | +26.1 [+24.2, +28.1] | 17.1% |

Paired: F against C +0.5 [−1.4, +2.4]; D against C −0.7 [−2.5, +1.3]; D against F −1.1 [−3.0, +0.9]. At phase 8 F
(1,007) and D (978) were ahead of C (937), by +3.5 and +2.1 points; both leads were gone by phase 16.

miniF2F-valid (244, the old run's settings: 64 expansions, 3,600 s per search, up to 5% wall-clock stops accepted):

| Run | Solved | Against v0 (paired) |
|---|---|---|
| v0 (rerun; old run 160) | 158 | |
| C16 | 172 | +5.7 [+2.5, +9.0] |
| F16 | 174 | +6.6 [+3.7, +9.8] |
| D16 | 172 | +5.7 [+2.5, +9.0] |
| v35 (old run, not rerun) | 170 | |

## What each arm taught

- **Per-tactic GRPO (A) gets exploited.** Its shaped reward was gamed route after route: bare `have` claims, blocks
  that keep going after a failing tactic, then long blocks. Fixes (claim switches, a cap on the explanation credit for
  wasted blocks, a lower learning rate) slowed the drift but never made A competitive. At 5e-5 its step was about 3x
  C's; at 2e-5 it came level with C on held-out states but still failed the screen.
- **Outcome-only credit (B2) was worse than shaped credit** at the same rate, so the shaping was not the main problem.
- **Verified progress (V) shortened blocks to about 1.9 tactics**: a one-step block on the proof earns the same 1 as a
  block covering it. It looked best of all on the held-out states and was 7.9 points behind C on the probe.
- **Progress fraction (F) fixed that** by paying a block its share of the remaining proof. It is the strongest policy
  per expansion of any arm (16.1% within one expansion, close to v35's 17.1%) and ties C at 16 expansions.
- **Expert iteration (C)** was the simplest and steadiest: no exploits, no drift, its curriculum still rising at
  phase 16.
- **D** tested whether GRPO adds to expert iteration. It did not, with one caveat: D's rounds moved it away from v0
  fast (KL to v0 0.090 at phase 16, four times F's 0.023), and from phase 8 on the pull back toward v0 amounted to
  10-73% of its GRPO policy loss. A GRPO
  step without that pull was not tested.

## What step 1 found about the old run

- **About 70% of the old run's in-pool gain (+26.1 points) came from the policy and 30% from the value model**: policy
  +18.4, value +8.0, and the two add up (2x2 of v0/v35 policy by v0/final value).
- **The old run never trained the policy on unsolved statements** (groups only at proof-graph nodes); 82-85% of policy
  expansions went unused.
- **Visible reasoning does not pay per token** (no reasoning +4.9 points at equal tokens) **but pays per node hour**
  (193 against 121 solved per hour), because without it the search is Lean-bound and the GPUs idle.
- **Noise floor:** one paired comparison on the 2,000-statement probe resolves about 2.6 points; v0 against itself
  disagrees on 15% of statements. Run-to-run noise of a whole closed loop was never measured (one seed per arm).

## Is it worth continuing the best setup?

The arms' curves are slowing: C gained 11.1 points in phases 1-8 and 5.6 in 9-16, F 14.6 then 2.6, D 13.2 then 2.9.
C's curriculum was still climbing at phase 16. If C kept adding about 5.6 points per 8 phases it would reach v35's
1,236 around phase 30-32, near v35's own token count; if gains halve every 8 phases it stalls near 1,160. So a longer
run would likely match v35 at similar compute, not beat it per token. On miniF2F the arms already match v35. Plots:
https://claude.ai/artifact/F2x8fF8gp5Co2U7vhFCcPm (private to the owner).

## Caveats

- One closed-loop run per arm; gaps under about 3 points between arms are not settled.
- The held-out states (512 intermediate states, one expansion) misread GRPO arms in both directions (V over-read,
  F under-read); only the probe was used to judge.
- F and V were extended in place from 8 to 16 phases (the searches in flight at phase 8 were cut); C, A and D ran 16
  phases in one go.
- D's phase 7 was interrupted by a host outage (Vast maintenance); its curriculum state was rebuilt exactly from the
  log and it resumed from version 6.

## Where everything is

- On the PC, checked against the node's file sizes: every phase checkpoint (LoRA adapters) of every run, every
  run's training trees and every evaluation's trees (`node_backup/2026-11-15/full/`); all logs and results
  (`node_backup/2026-11-15/live/`). Not kept: merged serving weights and the base model, rebuilt from the adapters.
- Configs: `experiments/configs/grpo/followup/` (arms, screens, step 1, miniF2F).
- Cost: the second node from 2026-11-15 08:30 to 2026-11-24 about 19:30 UTC, about 227 h at $0.83/h (about $190);
  the first node about $11, partly refunded. $28.75 of Vast credit is left.
- Training tokens of v35: about 458M, estimated from the old run's expansions (`results/followup_step0/`); an
  earlier estimate in the progress notes says 495M. Either way 2.4-2.6 times an arm's 192M.

## Open

- Fix: `write_json_atomically` renames without an fsync, which left an empty state file after the host outage (code
  change with two reviews).
- Not started, each the owner's call: second seeds of C and F, a longer C run, a public write-up.
