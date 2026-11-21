# Review BM: arm D at a GRPO rate of 2e-5 (design), 2026-11-21

Scope: the uncommitted change (`arms/D.toml` GRPO rate 5e-5 → 2e-5, rounds stay 5e-5; `test_followup_arms.py`
expectation), read against `results/followup_progress.md` (arm C, A's runs, the explanation cap, the two screens and
their rule), `DESIGN.md` "Arms" and `rl/README.md` "Expert iteration inside the loop". `test_followup_arms.py`: 72
passed. The diff itself is correct; the findings are about what the run can answer.

## Findings, ranked

1. **Major: with rounds every 4th phase, D against C does not answer "does GRPO add anything on top of expert
   iteration".** C runs a round every phase over a 4-phase window: 16 rounds, each phase's blocks trained in four
   rounds (the "about four epochs per block" that `DESIGN.md` gives as the reason for W = 4 and O2's 4 epochs). D at
   N = 4, W = 4 runs 4 rounds over non-overlapping windows: each block trained once, a quarter of C's expert-iteration
   dose. D minus C is therefore (GRPO) minus (12 rounds). Only one outcome is readable: D clearly ahead of C means
   GRPO adds something even at a quarter of the rounds. D level with or behind C says nothing about GRPO (fewer rounds
   explain it). Two clean designs, pick one before the start:
   - **(a) To answer the stated question: `expert_iteration_every_phases = 1`** (window 4, rate 5e-5, recipe
     unchanged). D is then C's exact round schedule plus the A screen's GRPO step before each round; D against C
     (held-out and the paired probe) reads symmetrically. Cost: about 4 more minutes per pause; per-phase movement
     about C's 2-3.4% plus GRPO's 3-4.5% every phase (see 5). It departs from `DESIGN.md`'s "N = 4 (proposed)", so it
     needs the owner's word, a test update (`ROUND_ARMS`/the `every` cases) and the `DESIGN.md` row.
   - **(b) Keep N = 4 and rename the question** to "do occasional expert-iteration rounds keep GRPO from drifting".
     Its control is the A screen (identical config and seeds through phase 3; rounds at 4 and 8), but the screen
     stopped at phase 8, so phases 10-16 have no GRPO-alone reference at 2e-5 (A capped ran at 5e-5). D against C
     is then reported as recipe against recipe with the asymmetric reading above.
   Changes that would confound either design: a different round rate, window or epoch count (C is the EI reference);
   rounds before the GRPO update; another credit (B2's, or no explanation cap; A capped and the screen are the GRPO
   references); a KL reference other than v0; a different curriculum seed or tokens per phase. Raising the round's
   epochs to 4 at N = 4 would match C's dose per block but not its schedule and would put a 4x step on one pause in
   four.

2. **Moderate: the phase-4 dip lands on a round phase (design b).** Every GRPO run dips at phase 4 (A runs 30.1-31.2%
   success, the A screen 34.2%/56.8%, B2 32.4%/54.1%); C did not (35.4%/61.4%). In D (N = 4) phase 4 is GRPO plus the
   first round, so a round that masks the dip lifts the 4-8 mean for a reason specific to that phase. Report phase 4
   alone and the 5-8 mean beside the pre-registered 4-8 mean; under (a) every phase has a round and this does not
   arise.

3. **Moderate: the A screen is D's only GRPO reference at 2e-5, and only to phase 8.** Under (b), D's phases 1-3 must
   reproduce the screen (held-out 61.2/57.2/60.3% valid, 33.6/34.9/35.9% success, change 4.5/3.6/3.4%) within the
   held-out's ~3-point resolution, or the deployment differs and phases 4-8 cannot be read against the screen. Under (a)
   use phase 1 against the screen only for the parameter change direction (the round adds to it).

4. **Minor: held-out is a sawtooth under (b).** Phases 4, 8, 12, 16 are measured right after a round, the others after
   GRPO alone. Both pre-registered windows hold the same share of round phases as each other's stop-rule halves (6-8
   and 10-12 each contain one: 8 and 12), so the stop rule stays fair; report round-phase and GRPO-only-phase means as
   description.

5. **Minor: step size per phase.** A at 5e-5 moved 6-10% a phase and slid; the A screen 3-4.5%; C 2-3.4%. A
   GRPO-plus-round phase should land near 4-6% (not additive unless aligned), under A at 5e-5. Under (a) that is every
   phase, under (b) one in four. Record the phase's whole change (the `expert_iteration` metric line has it) beside
   GRPO's alone; no stop on it.

6. **Minor: KL to v0 after rounds.** The GRPO update's KL (penalty 0.01, alert at 0.5 nats per token, alert only)
   includes the rounds' drift from v0, so its penalty pulls slightly against the rounds and a KL alert after phase 4
   would be the rounds', not GRPO's. Expected small (A's penalty about 0.0006); report the KL at the first GRPO update
   after a round against the one before.

7. **Minor, wording.** The new `D.toml` comment says the A screen "kept pace with C"; it matched C on success through
   phase 8 but missed valid Lean by 2.4 points and failed the rule. The header ("D takes A's ... settings") and
   `DESIGN.md` ("D interleaved: exactly A") now mean the A screen, not arm A; the progress file (line 593) still says D
   runs 5e-5. Update with the commit.

## Proposed pre-registered reading (fix before D publishes phase 4)

References (held-out, one expansion, the same 512 states; means of the phases named):

| | Success 4-8 | Valid 4-8 | Success 10-16 | Valid 10-16 |
|---|---|---|---|---|
| C | 35.9% | 64.2% | 38.7% | 69.3% |
| A screen (2e-5) | 36.1% | 61.8% | - | - |
| A capped (5e-5) | 33.6% | 60.5% | 32.8% | 61.0% |
| Lines (C − 1 and − 2 points) | 34.9% | 62.2% | 37.7% | 67.3% |

- **Run rule (as the screens' passing run):** stopped and reported if the mean success of phases 10-12 falls 1 point
  or more below that of phases 6-8. A held-out collapse stops it as every arm.
- **Habit guards** (means of phases 7-8 and of 15-16, as the screens): tactics per complete block ≤ 3.0, failing
  after the graph ≤ 30%, bare `have` ≤ 22%. A failed guard at 15-16 is reported with the result and blocks an "adds"
  verdict.
- **Held-out reading.** Phases 4-8 against the lines and the A screen (descriptive, same rule as the screens; under
  (b) with phase 4 and 5-8 reported apart). Phases 10-16 against C's 38.7%/69.3%. Each also against D's own v0
  baseline, with solved held-out states per phase. A selection signal, never the verdict alone.
- **Probe (decides).** D's phase-16 policy with its own value model, longest expected search first, paired against
  C's probe (1,049 of 2,000) and against the v0 anchors (714.5); A capped's (822) as context only (different rate).
  One paired comparison resolves about 2.6 points.
- **"GRPO adds something on top of expert iteration"** requires all of: probe D − C paired 95% interval above 0; held-out
  success mean 10-16 ≥ C's 38.7% and valid ≥ 67.3%; the guards at 15-16 pass; the run rule not tripped.
  - Under (a): interval containing 0 → "no measurable gain from GRPO on top of expert iteration at this budget, one
    seed"; interval below 0 → "GRPO costs on top of expert iteration".
  - Under (b): only "adds" is a statement about GRPO. Level → "GRPO plus 4 rounds matches 16 rounds" (no claim about
    GRPO's contribution without a C at N = 4); behind → not attributable. D against the A screen at 4-8 (and D's probe
    against v0) answers whether occasional rounds help GRPO.
- One seed, one probe: a reading for the owner, not a significance claim beyond the paired probe interval.

## Verdict

The rate change is correct and consistent with the screens (2e-5 is the only GRPO step that held pace with C to phase
8); tests pass. But at N = 4, D against C confounds GRPO with a quarter of C's expert-iteration dose and can only
show a positive result. **If the question is "does GRPO add on top of expert iteration", set
`expert_iteration_every_phases = 1` (nothing else) before starting; otherwise keep N = 4 and pre-register the
asymmetric reading above.** Either way, fix the reading before phase 4 publishes, run the phase 10-12 stop rule, and
correct the wording in finding 7.
