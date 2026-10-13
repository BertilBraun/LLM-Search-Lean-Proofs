# GPU utilization of the expert-iteration loop in thinking mode

## Live loop, 2026-10-13 10:37–10:45 UTC

Measured without touching the loop (`experiments/node_monitor.py` on all four servers, `nvidia-smi dmon`) while it ran
120 searches in thinking mode (n = 8, 512 tokens) pinned to CPUs 152–191, with the merged policy (0.58 of memory) and
merged value (0.30) as two vLLM instances per GPU. The window ends at a service restart (10:42, 142 s without
requests) and the hold (10:45); the steady part is 10:37:27–10:41:40.

| Server | Generated tokens/s | Prompt tokens/s | Requests/s | Running | Waiting |
|---|---|---|---|---|---|
| policy-gpu0 | 2,712 | 2,453 | 1.23 | 41.2 | 2.1 |
| policy-gpu1 | 2,772 | 2,373 | 1.23 | 40.0 | 1.5 |
| value-gpu0 | – | 1,265 | 3.94 | 0.6 | 0.2 |
| value-gpu1 | – | 1,231 | 3.81 | 0.5 | 0.1 |

GPU 0 93.3% at 331 W, GPU 1 93.9% at 336 W; the cgroup used 42.3 cores, throttled in 0.7% of periods.

- **Balanced.** The search sends policy requests round-robin over both servers (`PolicyExpander` cycles its
  clients) and value requests likewise; both GPUs got 1.23 policy requests/s and the same tokens/s. The 98% / 61% of
  the 09:02 status is one NVML sample of a bursty load: with ~5 requests per server in flight, utilization swings
  between 0% and 100% from second to second.
- **Half the ceiling.** 2.7k generated tokens/s per GPU against 5.7k at 512-token outputs in the throughput
  benchmark, because each policy server ran ~40 sequences instead of the ~250 that reach the ceiling.
- **Cause: Lean CPU.** The 40 pinned CPUs were saturated (load 109), so only about 10 of the 120 searches waited on
  the policy at any moment. 2.46 expansions/s on ~40 Lean cores is ~16 CPU-seconds of Lean per thinking expansion,
  four times the ~4.3 of the row-4 setup without thinking (`../README.md`), so thinking mode has not made the loop
  GPU-bound on this node. More searches would add Lean demand at the same rate; the levers are the Lean cost per
  expansion (what makes thinking-mode candidates four times more expensive is the next thing to measure:
  `experiments/lean_time_breakdown.py` on the loop's trees) or more CPU per GPU.

## Why thinking-mode expansions cost four times the Lean time

`lean_breakdown_loop.md`: 76 trees of the loop's latest shards (47–49), 3,991 expansions, 28.7 wall-seconds of Lean
per expansion (wall time inside the REPL; 120 REPLs share 40 CPUs). The sweep is 29%, policy candidates 71%.

- **Timeouts are 39% of all Lean time, and every one is a wall-clock kill:** 1,673 timeouts, none by heartbeats. With
  120 REPLs on 40 CPUs a REPL gets about a third of a CPU, so the 10 s wall-clock backstop fires after ~3.3 CPU-seconds,
  long before the 200,000-heartbeat limit; each kill then costs a restart and a replay (27 s per timeout), which
  loads the CPU further.
- **`nlinarith` blocks from the thinking policy are the culprit:** 3,070 attempts, 1,160 wall-clock kills, 33% of
  all Lean time (12.3 s per attempt), for 7 children and 7 proof steps.
- Proposed fix (needs a calibration run before it becomes a default): a lower heartbeat limit for policy candidates
  (`[search] tactic_heartbeats`, e.g. 50,000) so heavy tactics fail by heartbeats inside the REPL, deterministically
  and without a restart, before the wall clock; or fewer REPLs per pinned CPU so the backstop measures CPU time.

## Heartbeat limit for policy candidates (`calibration.jsonl`)

The loop's search template in thinking mode (n = 8, 512 tokens, A*, overlap, 7-tactic sweep) with the loop's v0008
weights on the merged pair layout, 120 searches pinned to 40 CPUs, the first 120 miniF2F-valid problems at 16
expansions. Only the policy candidates' heartbeat limit changes; the sweep keeps 200,000. "Busy" is the part with at
least 40 searches left.

| Candidate heartbeats | Solved | Expansions | Wall-clock kills | Heartbeat timeouts | Lean wall-s / expansion | Run min | Busy tokens/s per GPU | Busy util, power |
|---|---|---|---|---|---|---|---|---|
| 200,000 (default) | 74/120 | 823 | 80 | 0 | 4.39 | 15.2 | 4,596 / 4,416 | 90 / 92%, 337 W |
| 50,000 | 77/120 | 766 | 49 | 57 | 3.78 | 11.1 | 4,528 / 4,717 | 92 / 92%, 333 W |
| **25,000** | **77/120** | 759 | **24** | 176 | **3.00** | **7.9** | 4,953 / 4,840 | 94 / 93%, 336 W |

- At 200k heartbeats every policy timeout was a wall-clock kill (32% of the run's Lean time, 15 s each with the
  restart); the heartbeat limit was never reached within the 10 s backstop, even with the CPUs only a third busy.
- 25k turns most kills into heartbeat timeouts, which fail inside Lean without a restart: a third less Lean time per
  expansion, half the run time (the tail of Lean-heavy searches shrinks: 809 → 366 Lean-seconds for the slowest), at
  an equal solve rate (77 vs 74 of 120, noise). Some kills remain: large rational arithmetic is not counted in
  heartbeats. **Set: `[search] tactic_heartbeats = 25000` in `loop_search.toml`** (the sweep stays at 200,000).
- A CPU-share-aware wall clock (30 s) was not run within the time box; with heartbeats doing the limiting, the wall
  clock is only a backstop.
- On miniF2F the busy phase is GPU-bound (220–280 sequences, ~85% of the 5.7k ceiling, 12–14 cores); the loop's pool
  statements cost about five times the Lean time per expansion, so the loop itself stays CPU-bound until its
  candidates get cheaper.

## Serving settings for thinking mode (`serving_*.json`)

`experiments/serving_benchmark.py`: 96 closed-loop workers, each a thinking policy request (n = 8, 512 tokens,
temperature 0.8, real tree states) followed by a value request of 8 states, on the loop's v0008 merged policy and
value (value instances at 0.25 of memory, 96 sequences); 120 s after 50 s of warm-up. Mean 325 tokens per sample,
34% of samples hit the 512 cap.

| Policy instances | Generated tokens/s (both GPUs) | Util | Power W | Preemptions |
|---|---|---|---|---|
| 0.52 of memory, 256 sequences, 2,048 batched tokens (as in the loop) | 8,629 | 97 / 98% | 346 / 343 | 28 |
| 0.62, 256, 2,048 | 8,730 | | | 0 |
| **0.62, 512 sequences, 8,192 batched tokens** | **9,096 (+5%)** | 98 / 97% | 347 / 343 | 8 |
| same, all value requests on GPU 0's value instance | 7,103 (−22%) | 100 / 92% | 349 / 333 | |
| same, FP8 weights (`--quantization fp8`, Marlin weight-only) vs bf16, one GPU each | 4,487 vs 4,575 per GPU | 99 / 99% | 347 / 345 | |

Recommended: policy instances at 0.62 of memory with `MAX_NUM_SEQS=512 MAX_NUM_BATCHED_TOKENS=8192`, value
instances at 0.25 with `MAX_NUM_SEQS=96` (at 0.25 the default 256 sequences exceed the hybrid model's cache blocks),
a value instance on each GPU, bf16 weights. FP8 weights give no speed on a 2B model at these batch sizes (weights are
not the bottleneck), so their quality was not checked; int8 weight-only has no Ampere kernel for this model in
vLLM 0.31 beyond this Marlin FP8 path. These settings reach 4.5k tokens/s per GPU, ~80% of the 5.7k ceiling measured
with uniform synthetic prompts; the rest is the shorter, varying sample lengths and the value prefill.
