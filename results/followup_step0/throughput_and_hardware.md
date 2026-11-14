# grpo_loop_v1: compute, throughput and hardware (from the run logs)

From `node_backup/2026-11-01/hf_run/run_logs/metrics` and the evaluations file, by
`experiments/analysis/throughput_and_hardware.py` (full tables: `phases.csv`, `versions.csv`). GPU-h = 4 x wall hours
since the first log line (10-30 11:42 UTC); the 20.2 h of bring-up before it are unlogged and left out. Training-search
tokens are estimated (expansions x nearest probe's tokens/expansion; -3% to +7% on the 3 phases that recorded them).

## 1. Gain per GPU-hour

| version | GPU-h sampling/training/other = total | GPU-h, kept line | trees | expansions | tokens (est) | third | solved | points at 16 vs v0, same third | Elo [95%] |
|---|---|---|---|---|---|---|---|---|---|
| v0 | 0/0/10 = 10 | 10 | 0 | 0 | 0 | all | 203/501 (mean of 2) | 0 | 0 |
| v2 | 6/6/11 = 23 | 23 | 714 | 17k | 29M | 0 | 86/168 | +11.6 | +147 [+68, +249] |
| v4 | 16/10/11 = 37 | 37 | 2,252 | 40k | 72M | 1 | 92/168 | +7.7 | +109 [+26, +185] |
| v6 (rejected) | 26/14/11 = 51 | - | 3,658 | 67k | 114M | 2 | 68/165 | +6.4 | +27 [-73, +114] |
| v8 (rejected) | 36/17/12 = 65 | - | 4,835 | 91k | 153M | 0 | 69/168 | +1.5 | -28 [-133, +59] |
| v10 (rejected) | 46/20/12 = 78 | - | 5,870 | 114k | 186M | 1 | 43/168 | -21.4 | -361 [-465, -257] |
| v13 | 56/23/15 = 95 | 50 | 7,489 | 144k | 230M | 2 | 87/165 | +17.9 | +217 [+110, +325] |
| v15 | 66/27/15 = 108 | 63 | 8,422 | 160k | 259M | 0 | 83/168 | +9.8 | +117 [+41, +196] |
| v17 | 77/29/16 = 122 | 76 | 9,236 | 175k | 284M | 1 | 95/168 | +9.5 | +139 [+53, +214] |
| v19 | 87/32/16 = 135 | 90 | 10,120 | 191k | 310M | 2 | 94/165 | +22.1 | +286 [+189, +384] |
| v21 | 97/36/16 = 148 | 103 | 11,009 | 206k | 337M | 0 | 82/168 | +9.2 | +106 [+23, +210] |
| v23 | 107/39/16 = 161 | 116 | 11,954 | 222k | 362M | 1 | 103/168 | +14.3 | +222 [+143, +298] |
| v25 | 117/42/16 = 175 | 130 | 12,787 | 235k | 385M | 2 | 97/165 | +23.9 | +315 [+225, +400] |
| v31 (expert iteration) | 127/53/17 = 197 | 152 | 13,745 | 249k | 411M | 0 | 97/168 | +18.2 | +257 [+181, +352] |
| v33 | 137/57/17 = 210 | 165 | 14,631 | 262k | 434M | 1 | 106/168 | +16.1 | +254 [+179, +347] |
| v35 | 147/61/17 = 225 | 179 | 15,745 | 275k | 458M | 2 | 101/165 | +26.4 | +354 [+274, +443] |

Each row is one run on one third (165-168 problems); v0's two runs of a third differed by 9, 6 and 1 problems, so a
row carries about ±5 points of noise: compare rows only within a third. On third 0, v15 and v21 never beat v2's +11.6
despite 85-125 more GPU-h; expert iteration (v31) lifted it to +18.2. On thirds 1 and 2 the gain climbed slowly over
~80 GPU-h. "Kept line" leaves out the rejected branch (phases 5-10: 11.3 h, 45 GPU-h).

| pooled pass (last run of each third) | GPU-h so far | Elo vs v0 [95%] | projected solved of 501 (v0) | points |
|---|---|---|---|---|
| v13, v15, v17 (first pass after the rollback) | 128 | +153 [+106, +203] | 265 (215) | +9.9 |
| v21, v23, v25 (last pass before expert iteration) | 178 | +211 [+163, +257] | 282 (217) | +13.0 |
| v31, v33, v35 (final) | 228 | +289 [+248, +340] | 304 (218) | +17.2 |

The passes are the reliable numbers. GRPO from v13 to v25 (the reward fix applied from v16) added about +3 points over
50 GPU-h. Expert iteration plus 4 more phases added about +4 points over the next 50 GPU-h.

## 2. Phase anatomy

| of 79.5 node hours | bring-up (unlogged) | v0 baselines | sampling (with probe/miniF2F beside) | training pauses | held-out at pause | expert iteration | stops, restarts | final miniF2F + tail |
|---|---|---|---|---|---|---|---|---|
| hours | 20.2 (25%) | 2.2 (3%) | 37.6 (47%; 10.4 of it with evaluation beside) | 13.3 (17%) | 0.9 (1%) | 1.9 (2%) | 1.3 (2%) | 2.2 (3%) |

| median phase | sampling | pause | scoring | policy | value | drain, merge, wake, rest | held-out after |
|---|---|---|---|---|---|---|---|
| policy-only pause (14 phases) | 75 min | 18.4 min | 4.5 | 10.4 | - | 4.2 | - |
| policy + value pause (14 phases) | 75 min | 35.4 min | 5.0 | 12.4 | 10.2 | 5.2 | 3.3 |

| sampling period | trees / phase | groups | expansions | tokens (est) | tok/s/GPU | Lean core-s / expansion | search s per expansion: Lean / server wait | CPU cores of 122.9 | quota throttled |
|---|---|---|---|---|---|---|---|---|---|
| phases 1-12 (14.0 h) | 652 | 1,364 | 12.3k | 19.0M | 1,204 | 20 | 16 / 22 | 40-93 | 0% |
| phases 13-30 (22.5 h) | 451 | 932 | 7.3k | 12.9M | 773 | 52 | 54 / 13 | 90-118 | 25% |

Phases 3-30 all stopped at the 75-min minimum, far above the 300-group trigger. A pause took 27 min on average per
75 min of sampling. Generated tokens per expansion stayed at ~1,600-1,750. From phase 13 on, Lean CPU per expansion was
2.6x higher and token throughput 36% lower.

## 3. Hardware

| activity | GPU util % mean (p10) | GPU W | busiest-GPU memory GiB p50 / max | CPU cores mean / p90 | Lean cores | REPLs | RAM anon GiB mean / max |
|---|---|---|---|---|---|---|---|
| sampling (incl. evaluation beside) | 95 (86) | 294 | 23.3 / 23.8 | 96 / 120 | 81 | 122-141 | 106 / 136 |
| training pause | 89 (49) | 265 | 19.1 / 23.8 | 18 / 35 | 10 | 75 | 74 / 124 |

- **Phases 1-12 were GPU-bound:** searches waited on the servers longer than on Lean (22 vs 16 s per expansion), no
  CPU throttling, cards at ~299 W (never above 305 W, so probably capped near 300 W). Faster GPUs would have helped.
- **Phases 13-30 (62% of sampling hours) were Lean/CPU-bound:** 54 s Lean vs 13 s server wait per expansion, quota
  throttled 25% of the time. NVML's ~95% busy is kernel time, not batch fill. More CPU would have raised throughput;
  by how much is unknown (prompt and value-model load are not logged).
- **Memory:** serving memory is vLLM's fixed 0.62 + 0.28 reservation. The 4B + 2B bf16 weights are ~14 GB (DESIGN), so
  a 16 GB card cannot host both servers with a KV cache. Training reserved ~19-20 GiB on the busiest GPU (upper bound).
  Host RAM peaked at 136 GiB anonymous, ~158 GiB unavailable of 241 (tmpfs included); disk at 117 of 200 GiB.
- **Minimum node, same layout and difficulty:** 4 x 24 GB GPUs (16 GB needs split servers and smaller micro-batches,
  untested); ~45 CPU threads per GPU, the run had 31 (0.75 expansions/s/GPU x 52 Lean core-s + ~4, an estimate);
  192 GB RAM (256 GB with more REPLs); 200 GB disk; 32 GB or more shm.

## 4. Cost per unit ($0.965/h)

| basis | hours | $ | tokens | $ per M tokens | trees | $ per 1,000 trees |
|---|---|---|---|---|---|---|
| whole rental, all overheads | 79.5 | 77 | 548M (incl. evaluations) | 0.14 | 15,745 | 4.87 |
| sampling hours only | 37.5 | 36 | 495M | 0.07 | 15,745 | 2.30 |

A phase (sampling plus pause) cost ~$1.7: ~$2.6 per 1,000 trees early, ~$3.7 later. A probe third took 40 min
beside sampling (9 expansions, 15.6k tokens per statement): 1,000 statements at 16 expansions cost ~$1.1 by token share
(low: ignores its Lean CPU and 56 search slots) to $3.9 by wall time. miniF2F-valid at 64, alone: 1.03 h (~$1.0).

## Contradictions with the write-up, and gaps

- **Probe cadence:** every 3.4 h (median), after each value pause, not "every ~2 h"; a full pass took ~10 h.
- **Phase length:** exactly 75 min from phase 3 on (45 min in phases 1-2), not "75-120 min".
- **Price:** system.jsonl logs `hourly_price` 0.80 ($46.5 for the 58.1 logged h); the write-up uses $0.965.
- **Bring-up:** 25% of the bill (20.2 h) predates the logs; it is in the write-up's $75 but not in the GPU-h above.
- **Not recorded:** training-search tokens (estimated), prompt and value tokens, model latency, GPU batch fill, power
  limit, CPU model and SMT, why Lean CPU per expansion rose (harder curriculum likely), and expert-iteration GPU use
  (only a 1.9 h stop with GPUs 55% busy).
