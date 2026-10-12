# Value v0

A LoRA adapter on the raw Qwen3.5-2B weights (served next to the policy adapter), trained one epoch on the exact
remaining steps of 134k traced train-split states (`results/phase3_value_data_v0/`, built from the 53 tracing shards
finished at the time). Zero-shot (step 0) the base model ranks remaining steps no better than chance (Spearman −0.03,
bin accuracy 27%, 68% of the next-token mass on the bin tokens); after training Spearman 0.80, bin accuracy 53%,
MAE 1.26 steps, all mass on the bins. Served through vLLM and read from its top-20 logprobs the adapter reproduces
these numbers (`served_validation_v0.md`: 52.8%, 1.263, 0.798). The "bins in top-k" column below is the share of
states whose nine bin tokens are all among the top 20; it is ~0 because without dead labels `dead` falls below the
top 20 (p_dead ≈ 1e-7), which does not affect h. Later runs report the served h error instead.

## Training run `phase3_value_v0`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-2B` |
| Data | `v0`: 134,433 train states (219 over 2,048 prompt tokens dropped), 2,566 validation states |
| LoRA | rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0002, warmup 0.03, cosine to 0.1, clip 1, 1 epoch(s), 32,768 padded tokens per micro-batch, 1 micro-batches per step |
| Loss | Gaussian smoothing sigma 0.5 bins, bin-mass weight 1 |
| Readout | 8+ = 12 steps, dead = 16 steps |
| Kernels | flash-linear-attention |

## Throughput

| Quantity | Value |
|---|---|
| Steps | 951 |
| Examples | 134,433 |
| Tokens | 28,886,816 |
| Padding overhead | 4.6% |
| Training time | 126.7 min |
| Tokens/s | 3,799 |
| Peak GPU memory | 14.8 GiB |
| Trainable parameters | 67,276,800 |

## Validation

On 2,566 held-out states. Bin accuracy: the most likely of the nine bins is the label's bin. MAE: expected steps given alive against the label (8+ read out as in the readout). Spearman: h against the exact remaining steps. Dead AUC: p_dead separating dead from exact labels. Bin mass: full-vocabulary probability of the nine bin tokens; in top-20: states whose nine bin tokens are all among the most likely tokens vLLM returns.

| Step | Loss | Bin accuracy | MAE | Spearman | Dead AUC | Bin mass | Bins in top-k |
|---|---|---|---|---|---|---|---|
| 0 | 3.2463 | 27.3% | 2.346 | -0.034 | – | 0.683 | 0.8% |
| 50 | 1.8209 | 33.5% | 2.150 | 0.572 | – | 1.000 | 0.2% |
| 100 | 1.5692 | 43.3% | 1.679 | 0.728 | – | 0.999 | 18.5% |
| 150 | 1.5146 | 44.7% | 1.509 | 0.745 | – | 0.999 | 0.2% |
| 200 | 1.5033 | 44.8% | 1.363 | 0.771 | – | 1.000 | 0.0% |
| 250 | 1.5099 | 47.1% | 1.598 | 0.752 | – | 0.999 | 0.0% |
| 300 | 1.4751 | 48.6% | 1.394 | 0.769 | – | 1.000 | 0.0% |
| 350 | 1.4952 | 47.4% | 1.434 | 0.755 | – | 1.000 | 0.0% |
| 400 | 1.4539 | 49.3% | 1.404 | 0.778 | – | 1.000 | 0.0% |
| 450 | 1.4456 | 51.1% | 1.324 | 0.785 | – | 1.000 | 0.0% |
| 500 | 1.4324 | 50.2% | 1.399 | 0.788 | – | 1.000 | 0.0% |
| 550 | 1.4385 | 51.2% | 1.347 | 0.787 | – | 1.000 | 0.0% |
| 600 | 1.4395 | 51.5% | 1.378 | 0.790 | – | 1.000 | 0.0% |
| 650 | 1.4299 | 51.1% | 1.288 | 0.794 | – | 1.000 | 0.0% |
| 700 | 1.4267 | 51.8% | 1.264 | 0.800 | – | 1.000 | 0.0% |
| 750 | 1.4209 | 52.9% | 1.318 | 0.794 | – | 1.000 | 0.2% |
| 800 | 1.4283 | 52.5% | 1.262 | 0.796 | – | 1.000 | 0.0% |
| 850 | 1.4133 | 53.7% | 1.313 | 0.799 | – | 1.000 | 0.0% |
| 900 | 1.4150 | 53.6% | 1.252 | 0.803 | – | 1.000 | 0.0% |
| 950 | 1.4240 | 53.3% | 1.260 | 0.799 | – | 1.000 | 0.0% |
| 951 | 1.4229 | 53.2% | 1.263 | 0.798 | – | 1.000 | 0.0% |

Final confusion (rows: label bin, columns: most likely bin):

| Label | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8+ | dead |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 699 | 67 | 21 | 3 | 0 | 0 | 0 | 4 | 0 |
| 2 | 157 | 290 | 62 | 15 | 1 | 0 | 0 | 10 | 0 |
| 3 | 59 | 98 | 138 | 27 | 10 | 2 | 0 | 22 | 0 |
| 4 | 39 | 39 | 56 | 73 | 11 | 6 | 0 | 19 | 0 |
| 5 | 19 | 25 | 38 | 44 | 29 | 5 | 0 | 27 | 0 |
| 6 | 10 | 14 | 23 | 27 | 25 | 18 | 0 | 25 | 0 |
| 7 | 5 | 5 | 12 | 24 | 17 | 8 | 0 | 31 | 0 |
| 8+ | 6 | 5 | 21 | 16 | 27 | 12 | 1 | 119 | 0 |
| dead | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Started 2026-10-11T22:32:31+00:00, git 5b8ef73f97; adapter `/workspace/checkpoints/phase3_value_v0/adapter`.
