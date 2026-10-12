# GPU utilization: training, search, serving and publishing

Owner's report: LoRA SFT ran at 60–70% GPU utilization and the search fluctuated between 30% and 97%. Everything
below was measured on the idle node (2× RTX 3090, 46-core cgroup quota on 192 visible CPUs) unless a CPU load is
named. Utilization is NVML's (time with a kernel running), sampled every 0.5–1 s by `experiments/node_monitor.py`.

## Root causes

1. **CPU quota throttling, not nice levels.** During SFT v2 a 36-process tracing job and a 24-process pre-filter
   ran next to training; during the search a pre-filter ran next to 40 searches (load 57, 20% of periods
   throttled). The container sees 192 CPUs, so busy processes never share a CPU and `nice` has nothing to arbitrate:
   when the cgroup exhausts its 46-core quota, every thread in it stops until the next 100 ms period. 60 busy
   processes throttle 100% of periods at nice 0 and at nice 19; pinned to 32 CPUs, 0.3%. Training survives this
   (its launch queue is full), vLLM does not (it schedules every decoding step on the CPU).
2. **Training is GPU-bound on an idle node, but only half its GPU time is matmuls.** Profile of the SFT v2 setup
   (padded, 32k tokens per micro-batch, gradient checkpointing): 98.5% utilization, 342 W, matmuls 51% of GPU time,
   dtype casts 17%, element-wise multiplies 11%, adds, norm powers, depthwise convolution 2.5%; padding 4.7% of
   tokens. The evaluation pauses (6 × 110–150 s, generation on rank 0 while rank 1 waits) and the background jobs
   explain the low readings in the SFT v2 run.
3. **The search is bound by Lean CPU, not by the GPUs.** At 40 searches Lean used 30 of 46 cores and each search
   alternated between Lean and the GPU, so the servers ran 50 sequences on average (~25% of their decoding
   capacity) and utilization fluctuated with how many searches happened to wait on the GPU. More searches fill the
   GPUs until Lean saturates the quota at ~120 searches (5.8 Lean-seconds per expansion, `lean_breakdown_row4.md`).

## Training (`experiments/sft_throughput.py`)

SFT v2's data (20,000 random examples), LoRA rank 64, 32,768 tokens per micro-batch, gradient checkpointing on;
tokens/s over steps 6–16 (after Triton autotuning and compilation).

| Setup | Tokens/s | vs padded | Peak GiB | Utilization, power |
|---|---|---|---|---|
| 1 GPU, padded, length-grouped (SFT v2) | 3,667 | – | 14.5 | 98.5%, 342 W |
| 1 GPU, packed | 4,225 | +15% | 14.1 | |
| 1 GPU, packed, compiled norms and MLPs | 5,267 | +44% | 12.9 | |
| 1 GPU, packed, compiled norms, MLPs and mixer projections (`compile_layers`) | **5,670** | **+55%** | 12.9 | |
| 1 GPU, packed, whole token mixers compiled | 5,853, loss NaN at step 2 | rejected | 12.5 | |
| 1 GPU, packed + compiled, 64k tokens per micro-batch | 5,234 | +43% | 20.9 | |
| 1 GPU, packed + compiled, no gradient checkpointing, 8k tokens | out of memory | | | |
| DDP, padded (SFT v2 ran at 6,982 next to the background jobs) | 7,332 | – | 14.8 | 99.2 / 99.4%, 343 W |
| DDP, packed + compiled | **10,724** | **+46%** | | 99.7 / 97.5%, 346 / 339 W |
| DDP, packed + compiled, 60 busy processes, nice 0 (100% of periods throttled) | 10,876 | | | 98.3 / 99.7% |
| DDP, packed + compiled, 60 busy processes, nice 19 (100% throttled) | 10,880 | | | 99.7 / 99.6% |
| DDP, packed + compiled, 60 busy processes via `background.sh` (0.3% throttled) | 10,911 | | | 99.9 / 97.9% |

- Packing (`optimization.packing`, `lean_search.training.packing`): shuffled examples concatenated into one row per
  micro-batch; varlen flash attention (`torch.nn.attention.varlen`) and FLA's varlen convolution and gated delta
  rule restart at every example (transformers' own convolution fallback would leak three tokens across examples).
  Checked on the real model: mean completion loss 0.74816 packed vs 0.74825 alone over 64 examples (per-token
  differences from different bf16 kernels, mean 0.019), and changing every other example's tokens leaves an
  example's losses bitwise identical (difference 0.0); the same two checks on a tiny Qwen3.5 in
  `tests/training/test_packing_gpu.py`, plus one for value training's last-position logits.
- `optimization.compile_layers` compiles (dynamic shapes) each layer's norms, MLP and the token mixers' LoRA
  projections and norms, fusing the element-wise chains; matmuls stay cuBLAS. Step losses follow the uncompiled run
  within bf16 noise (0.657 / 0.751 / 0.645 vs 0.656 / 0.756 / 0.629).
- At 10.8k tokens/s, SFT v2's 60M tokens take 93 minutes instead of 143.

## Search (`experiments/search_throughput.py`)

Row 4 (A*, value v0, SFT v2 policy, n = 16, 64 expansions) on miniF2F-valid; 390 s per setting, averaged over
120–390 s (the first 120 s start the REPL pool). Samples/s counts policy samples; one policy request (16 samples)
per expansion.

| Setting | Samples/s | GPU utilization | Power W | CPU cores | Throttled | Running sequences |
|---|---|---|---|---|---|---|
| 40 searches, adapters (baseline) | 89.0 | 78 / 80% | 317 / 317 | 29.9 | 0% | 50 |
| 40, overlap + early value scoring | 94.3 | 70 / 73% | 305 / 308 | 32.4 | 0% | 66 |
| 120, adapters | 138.5 | 70 / 72% | 307 / 312 | 45.7 | 90% | 179 |
| 120, adapters, searches pinned to 40 CPUs | 138.2 | 76 / 80% | 323 / 323 | 42.6 | 0% | 132 |
| 120 pinned, overlap + early, merged policy + merged value instance per GPU | **151.6** | **95 / 96%** | **341 / 339** | 43.7 | 0% | 116 |
| same, merged policy + value as rank-128 difference adapter | 144.6 | 79 / 80% | 327 / 321 | 43.6 | 0% | 140 |
| same as the merged pair, served from GPU 0 only | 91.2 | 96.5% / – | 342 / – | 35.4 | 0.1% | 195 (542 waiting) |

- Overlap (`[expander] overlap`) and early value scoring (`[search] score_children_early`) change only timing; the
  Lean tests check that charged tokens and priorities equal the sequential search's, and that an overlapped request
  a proof made unnecessary is still charged (`src/lean_search/policy/README.md`).
- Merged models: the merged pair is the fastest layout; two instances share each GPU by time slicing, which also
  keeps utilization near 100%.
- vLLM batch settings: at 120 searches the servers ran 116–195 sequences with 17–27 waiting, below the defaults
  (256 sequences, 2,048 batched tokens), so these settings do not bind while Lean does; a 16,384-token prefill chunk
  did not speed up value re-scoring either (below).
- One GPU serves 91 samples/s at 96.5%; the CPU-bound demand at 40 Lean cores is ~150 samples/s, so the search
  needs about 1.7 GPUs of this kind at row-4 settings, and both GPUs reach full utilization only together with the
  merged pair layout.

## Lean time (`experiments/lean_time_breakdown.py`, row-4 trees)

5.81 Lean-seconds per expansion: the automation sweep 1.60 (27.5%), policy candidates 4.13 (71.1%), verification 0.08.
Value scoring uses no Lean. Candidates: errors 1.91 s per expansion (23,190 calls, 0.43 s each), **timeouts 1.33 s
(451 calls at 15.6 s each: the 10 s backstop plus the process restart and replay it causes)**, valid steps 0.88 s.
Sweep: aesop 0.48, simp_all 0.33, nlinarith 0.19, field_simp 0.11, decide 0.10, ring_nf 0.10, norm_num 0.09,
linarith 0.08 s per expansion. Full tables in `lean_breakdown_row4.md`.

| Reduction | Saved s / expansion | Cost |
|---|---|---|
| 7-tactic sweep (omega, constructor, rfl, field_simp, ring_nf, simp_all, nlinarith) | 0.83 (14%) | the dropped tactics were 71 proof steps (decide 27, linarith 28, aesop 11, norm_num 5); see the full runs |
| candidate calls capped at 5 s | ≤ 1.08 (19%) | 6 of 157 proofs contain a slower step |
| capped at 2 s | ≤ 1.87 (32%) | 12 proofs |
| caching sweep results per normalized goal across searches | 0 | no (goals, tactic) pair repeats across the 244 trees (within a tree, goals are deduplicated already) |

## Serving, publishing and re-scoring

See `deployment/README.md` (serving and publishing): merge 17 s (CPU) or 22 s (GPU), in-place reload 1.9 s, sleep
0.4 s (796 MiB left), wake with new weights 2.0 s, warm restart 56–61 s (cold 155–206 s). Re-scoring all 14,879
open states of the row-4 trees: 105 s on the two merged value instances (141 states/s), 126 s through the value
adapter (118 states/s), after batching 32 states per request (before: 74 states/s, client-bound).

## Full runs

Full miniF2F-valid runs at row-4 settings (64 expansions, 600 s) with the recommended serving (merged pair on both
GPUs), 120 searches pinned to 40 CPUs, overlap and early value scoring; `full_runs/` has their summaries and configs,
`full_runs/comparison.jsonl` the numbers. "Busy" is the part with at least 60 searches left (the first ~8 minutes).
The reference is row 4 itself (40 searches, adapters, sequential; it ran next to the pool pre-filter).

| Run | Solved | New / lost vs row 4 | Run min | Theorems/h | Lean s / expansion | Wall-clock stops | Busy samples/s | Busy GPU utilization, power |
|---|---|---|---|---|---|---|---|---|
| row 4 (`phase3_astar_v0_sft_v2`) | 157/244 | – | 24.3 | 603 | 5.73 | 25 | – | – |
| 13-tactic sweep | 155/244 | +4 / −6 | 11.8 | 1,241 | 9.2 | 47 | 135.7 | 94 / 95%, 337 / 337 W |
| 7-tactic sweep | 154/244 | +2 / −5 | 11.8 | 1,239 | 7.0 | 35 | 151.0 | 97 / 96%, 342 / 338 W |
| 7-tactic sweep, candidates limited to 5 s | 153/244 | +2 / −6 | 11.8 | 1,241 | 7.6 | 33 | 147.1 | 95 / 96%, 340 / 338 W |

- Throughput doubles (603 → 1,240 theorems per hour on the split, which ends with the 600 s searches) and the solve
  rate stays within noise of row 4 (two-sided sign tests far from significance).
- **Wall-clock budgets bind more:** 120 REPLs on 40 CPUs make each search slower in wall-clock terms (Lean seconds
  per expansion are wall time), so 47 searches stopped at 600 s instead of 25 and the split took 4,789 expansions
  instead of 5,261. Comparisons at equal expansions are unaffected for searches that finish; budgets in seconds should
  be read per search, or raised with the concurrency.
- The 7-tactic sweep cuts Lean time per expansion by 23% at equal solve rate and raises busy throughput by 11%
  (151 samples/s at 43.4 cores, 97% / 96% utilization at 340 W). It is still CPU-bound: one GPU serves ~91 samples/s,
  so two serve ~180, and the search would need about 48 Lean cores to fill them.
- Tighter candidate limits do not help: a 5 s wall-clock limit kills more processes (1,011 timeouts), and each kill
  costs a restart and a replay, so Lean time per expansion rose (7.6 vs 7.0).

## Hardware sizing

At row-4 settings with the 7-tactic sweep one expansion costs ~4.3 CPU-seconds of Lean (40 of the 43.4 cores at 9.4 expansions/s) (about 7 wall-seconds when 120
REPLs share 40 CPUs) and one policy request plus ~10 value states of GPU work. With 40 cores for Lean the node
reaches ~9.4 expansions/s (151 samples/s), about 85% of what the two 3090s can serve; filling both takes ~48 Lean
cores, and each further GPU of this class ~25 more. Thinking mode (about ten times the generated tokens per sample)
inverts this: the GPUs become the bottleneck.
