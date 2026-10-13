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
