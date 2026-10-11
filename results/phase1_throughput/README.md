# Phase 1: vLLM throughput at the proof-search prompt shape

One NVIDIA GeForce RTX 3090 per server; vllm 0.31.0, torch 2.13.0. Each configuration keeps a fixed number of requests in flight; every request asks for n=16 samples at temperature 1 with `ignore_eos`, and its `max_tokens` is drawn uniformly from [0.5, 1.5] x the workload's output length, so samples average exactly that length and requests do not finish in synchronized waves. Prompts are unique synthetic Lean proof states rendered with the model's chat template (thinking on or off as named). Generated tokens/s and computed (non-cached) prompt tokens/s come from the server's counters over the measurement window; samples/s = generated tokens/s / output length, requests/s = samples/s / n, and prompt tokens/s counts each request's prompt once. Peak GPU MiB is what the vLLM process reserves (`--gpu-memory-utilization 0.90`), not what the model needs.

## Overview: generated tokens/s (samples/s), base model on a LoRA-enabled server

| Model | prompt600-short | prompt600-thinking | prompt1500-short | prompt1500-thinking |
|---|---|---|---|---|
| qwen3.5-2b | 4,524 (47) | 6,339 (12) | 3,829 (40) | 5,677 (11) |
| qwen3-1.7b | 5,131 (53) | 5,224 (10) | 2,813 (29) | 3,332 (7) |
| qwen2.5-math-1.5b | 7,852 (82) | 8,498 (17) | 4,807 (50) | 6,952 (14) |
| qwen3.5-0.8b | 6,109 (64) | 8,973 (18) | 4,854 (51) | 7,681 (15) |
| qwen3.5-4b | 1,979 (21) | 2,299 (4) | 1,278 (13) | 1,568 (3) |

## All measurements

| Model | Variant | Workload | Prompt tokens | Generated tokens/s | Samples/s | Requests/s | Prompt tokens/s | Computed prompt tokens/s | Prefix cache hit rate | Running sequences | KV cache use | Preemptions | Peak GPU MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b | base | prompt600-short | 577 | 4,524 | 47.1 | 2.95 | 1,701 | 2,897 | 0.89 | 244 | 0.42 | 0 | 23,260 |
| qwen3.5-2b | base | prompt600-thinking | 618 | 6,339 | 12.4 | 0.77 | 478 | 635 | 0.92 | 254 | 0.44 | 0 | 23,260 |
| qwen3.5-2b | base | prompt1500-short | 1497 | 3,829 | 39.9 | 2.49 | 3,731 | 4,693 | 0.92 | 246 | 0.42 | 0 | 23,262 |
| qwen3.5-2b | base | prompt1500-thinking | 1488 | 5,677 | 11.1 | 0.69 | 1,031 | 1,370 | 0.92 | 253 | 0.49 | 0 | 23,262 |
| qwen3-1.7b | base | prompt600-short | 589 | 5,131 | 53.4 | 3.34 | 1,966 | 2,278 | 0.93 | 255 | 0.18 | 0 | 21,912 |
| qwen3-1.7b | base | prompt600-thinking | 602 | 5,224 | 10.2 | 0.64 | 384 | 470 | 0.93 | 256 | 0.57 | 0 | 21,912 |
| qwen3-1.7b | base | prompt1500-short | 1506 | 2,813 | 29.3 | 1.83 | 2,758 | 2,988 | 0.93 | 252 | 0.27 | 0 | 21,912 |
| qwen3-1.7b | base | prompt1500-thinking | 1473 | 3,332 | 6.5 | 0.41 | 599 | 667 | 0.93 | 256 | 0.66 | 0 | 21,912 |
| qwen2.5-math-1.5b | base | prompt600-short | 583 | 7,852 | 81.8 | 5.11 | 2,981 | 3,320 | 0.93 | 254 | 0.04 | 0 | 22,008 |
| qwen2.5-math-1.5b | base | prompt600-thinking | 605 | 8,498 | 16.6 | 1.04 | 628 | 725 | 0.93 | 255 | 0.14 | 0 | 22,008 |
| qwen2.5-math-1.5b | base | prompt1500-short | 1498 | 4,807 | 50.1 | 3.13 | 4,688 | 4,896 | 0.93 | 251 | 0.07 | 0 | 22,008 |
| qwen2.5-math-1.5b | base | prompt1500-thinking | 1471 | 6,952 | 13.6 | 0.85 | 1,248 | 1,325 | 0.93 | 255 | 0.16 | 0 | 22,008 |
| qwen3.5-0.8b | base | prompt600-short | 579 | 6,109 | 63.6 | 3.98 | 2,304 | 3,552 | 0.90 | 245 | 0.36 | 0 | 23,198 |
| qwen3.5-0.8b | base | prompt600-thinking | 621 | 8,973 | 17.5 | 1.10 | 680 | 937 | 0.92 | 254 | 0.38 | 0 | 23,198 |
| qwen3.5-0.8b | base | prompt1500-short | 1495 | 4,854 | 50.6 | 3.16 | 4,725 | 6,195 | 0.92 | 245 | 0.36 | 0 | 23,200 |
| qwen3.5-0.8b | base | prompt1500-thinking | 1487 | 7,681 | 15.0 | 0.94 | 1,395 | 1,971 | 0.91 | 253 | 0.44 | 0 | 23,200 |
| qwen3.5-4b | base | prompt600-short | 578 | 1,979 | 20.6 | 1.29 | 745 | 1,086 | 0.91 | 134 | 0.97 | 104 | 21,468 |
| qwen3.5-4b | base | prompt600-thinking | 610 | 2,299 | 4.5 | 0.28 | 171 | 322 | 0.89 | 132 | 0.98 | 147 | 21,468 |
| qwen3.5-4b | base | prompt1500-short | 1493 | 1,278 | 13.3 | 0.83 | 1,242 | 1,500 | 0.93 | 122 | 0.94 | 296 | 21,468 |
| qwen3.5-4b | base | prompt1500-thinking | 1478 | 1,568 | 3.1 | 0.19 | 283 | 469 | 0.90 | 109 | 0.98 | 256 | 21,468 |
| qwen3.5-2b | LoRA server, base requests | prompt600-short | 578 | 4,611 | 48.0 | 3.00 | 1,734 | 2,942 | 0.89 | 239 | 0.41 | 0 | 23,134 |
| qwen3.5-2b | LoRA server, base requests | prompt600-thinking | 618 | 6,562 | 12.8 | 0.80 | 495 | 657 | 0.92 | 254 | 0.44 | 0 | 23,134 |
| qwen3.5-2b | LoRA server, base requests | prompt1500-short | 1497 | 3,775 | 39.3 | 2.46 | 3,678 | 4,673 | 0.92 | 238 | 0.40 | 0 | 23,136 |
| qwen3.5-2b | LoRA server, base requests | prompt1500-thinking | 1486 | 5,688 | 11.1 | 0.69 | 1,032 | 1,409 | 0.92 | 252 | 0.49 | 0 | 23,136 |
| qwen3.5-2b | LoRA server, rank-64 adapter | prompt600-short | 577 | 3,903 | 40.7 | 2.54 | 1,467 | 2,516 | 0.89 | 242 | 0.41 | 0 | 23,136 |
| qwen3.5-2b | LoRA server, rank-64 adapter | prompt600-thinking | 616 | 5,969 | 11.7 | 0.73 | 449 | 620 | 0.91 | 253 | 0.43 | 0 | 23,136 |
| qwen3.5-2b | LoRA server, rank-64 adapter | prompt1500-short | 1495 | 3,395 | 35.4 | 2.21 | 3,303 | 4,277 | 0.92 | 244 | 0.41 | 0 | 23,136 |
| qwen3.5-2b | LoRA server, rank-64 adapter | prompt1500-thinking | 1488 | 5,200 | 10.2 | 0.63 | 945 | 1,281 | 0.92 | 254 | 0.49 | 0 | 23,136 |
| qwen3.5-2b | merged, LoRA disabled | prompt600-short | 578 | 5,150 | 53.6 | 3.35 | 1,940 | 3,115 | 0.90 | 241 | 0.40 | 0 | 22,100 |
| qwen3.5-2b | merged, LoRA disabled | prompt600-thinking | 620 | 6,632 | 13.0 | 0.81 | 502 | 681 | 0.92 | 254 | 0.43 | 0 | 22,102 |
| qwen3.5-2b | merged, LoRA disabled | prompt1500-short | 1499 | 3,938 | 41.0 | 2.56 | 3,842 | 4,790 | 0.92 | 244 | 0.41 | 0 | 22,102 |
| qwen3.5-2b | merged, LoRA disabled | prompt1500-thinking | 1486 | 5,746 | 11.2 | 0.70 | 1,042 | 1,411 | 0.92 | 253 | 0.49 | 0 | 22,102 |
| qwen3-1.7b | LoRA server, base requests | prompt600-short | 589 | 5,164 | 53.8 | 3.36 | 1,980 | 2,302 | 0.93 | 251 | 0.16 | 0 | 22,482 |
| qwen3-1.7b | LoRA server, base requests | prompt1500-thinking | 1547 | 3,217 | 6.3 | 0.39 | 608 | 704 | 0.93 | 255 | 0.65 | 0 | 22,482 |
| qwen3-1.7b | LoRA server, rank-64 adapter | prompt600-short | 588 | 4,700 | 49.0 | 3.06 | 1,800 | 2,092 | 0.93 | 247 | 0.17 | 0 | 22,482 |
| qwen3-1.7b | LoRA server, rank-64 adapter | prompt1500-thinking | 1545 | 3,079 | 6.0 | 0.38 | 581 | 634 | 0.93 | 255 | 0.65 | 0 | 22,482 |
| qwen3-1.7b | merged, LoRA disabled | prompt600-short | 589 | 5,171 | 53.9 | 3.37 | 1,981 | 2,319 | 0.93 | 254 | 0.16 | 0 | 21,772 |
| qwen3-1.7b | merged, LoRA disabled | prompt1500-thinking | 1547 | 3,226 | 6.3 | 0.39 | 609 | 706 | 0.93 | 256 | 0.62 | 0 | 21,772 |
| qwen3.5-2b | prefix match unit 544 (vLLM default) | prompt600-short | 577 | 3,965 | 41.3 | 2.58 | 1,491 | 7,347 | 0.69 | 248 | 0.42 | 0 | 24,084 |
| qwen3.5-2b | prefix match unit 544 (vLLM default) | prompt1500-thinking | 1527 | 4,663 | 9.1 | 0.57 | 869 | 4,356 | 0.68 | 252 | 0.50 | 0 | 24,086 |
| qwen3.5-2b | max_num_seqs 512, max_num_batched_tokens 8192 | prompt600-short | 578 | 5,184 | 54.0 | 3.38 | 1,952 | 3,128 | 0.90 | 489 | 0.86 | 0 | 22,686 |
| qwen3.5-2b | max_num_seqs 512, max_num_batched_tokens 8192 | prompt1500-thinking | 1523 | 4,386 | 8.6 | 0.54 | 816 | 1,098 | 0.92 | 475 | 0.99 | 436 | 22,752 |

## Server starts

| Model | Variant | Startup s | Weights GiB | KV cache GiB | KV cache tokens | max_num_seqs | max_num_batched_tokens |
|---|---|---|---|---|---|---|---|
| qwen3.5-2b | base | 107 | 4.48 | 15.53 | 929,047 | default | default |
| qwen3-1.7b | base | 136 | 3.90 | 15.65 | 146,496 | default | default |
| qwen2.5-math-1.5b | base | 132 | 3.52 | 16.09 | 602,720 | default | default |
| qwen3.5-0.8b | base | 104 | 2.18 | 17.81 | 1,064,960 | default | default |
| qwen3.5-4b | base | 278 | 9.39 | 9.24 | 213,364 | default | default |
| qwen3.5-2b | LoRA server | 106 | 4.48 | 15.53 | 929,047 | default | default |
| qwen3.5-2b | merged, LoRA disabled | 155 | 3.63 | 15.89 | 950,272 | default | default |
| qwen3-1.7b | LoRA server | 97 | 3.90 | 16.22 | 151,808 | default | default |
| qwen3-1.7b | merged, LoRA disabled | 87 | 3.22 | 16.74 | 156,752 | default | default |
| qwen3.5-2b | prefix match unit 544 (vLLM default) | 103 | 4.48 | 15.53 | 929,047 | default | default |
| qwen3.5-2b | max_num_seqs 512, max_num_batched_tokens 8192 | 106 | 4.48 | 14.95 | 894,045 | 512 | 8192 |

## Adapter load, swap and merge timings (seconds)

| Quantity | qwen3.5-2b | qwen3-1.7b |
|---|---|---|
| adapter_creation_seconds | 12.19 | 7.99 |
| base_request_seconds | 0.09 | 0.06 |
| load_adapter_seconds | 0.26 | 0.27 |
| first_adapter_request_seconds | 0.13 | 0.09 |
| swap_adapter_seconds | 0.26 | 0.26 |
| first_request_after_swap_seconds | 0.12 | 0.09 |
| merge_seconds | 24.35 | 30.03 |
| stop_server_seconds | 2.04 | 2.04 |
| merged_server_startup_seconds | 154.90 | 86.67 |
| first_merged_request_seconds | 0.68 | 0.43 |
