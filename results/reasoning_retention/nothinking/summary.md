# Reasoning retention on MATH-500

200 MATH-500 problems stratified by level and subject (seed `reasoning-retention`), thinking off (empty think block), k = 4 samples at temperature 0.6 (top-p 0.95), at most 4096 generated tokens; the answer is the last \boxed{} after the thinking block. Forced answers: a sample cut off at the cap gets its thinking closed with `</think>` (if still open) and `The final answer is $\boxed{`, then at most 64 tokens to finish the box (budget forcing); this separates reasoning from stopping.

| Model | pass@1 (mean over k) | any@4 | Mean generated tokens | pass@1 with forced answers | Forced answers correct | Truncated | Thinking unfinished | No boxed answer |
|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b | 64.0% | 76.5% | 1,812 | 71.0% | 28.2% | 27.5% | 0.0% | 26.1% |
| qwen3.5-2b-sft-v2 | 60.6% | 76.5% | 1,616 | 64.8% | 19.3% | 24.6% | 0.0% | 23.8% |
| qwen3.5-2b-bootstrap-r1 | 61.4% | 76.0% | 1,180 | 63.1% | 15.4% | 13.0% | 0.0% | 12.5% |
| qwen3.5-4b | 83.0% | 91.5% | 1,435 | 87.2% | 38.8% | 14.5% | 0.0% | 12.1% |
| qwen3.5-4b-sft | 80.5% | 88.0% | 1,219 | 84.4% | 30.7% | 12.6% | 0.0% | 12.5% |
| qwen3.5-4b-student | 80.4% | 91.0% | 1,091 | 83.2% | 30.8% | 9.8% | 0.0% | 9.1% |
| qwen3.5-4b-sft-gentle | 46.9% | 69.0% | 358 | 47.0% | 4.3% | 2.9% | 0.0% | 3.2% |
| qwen3.5-4b-visible-student | 52.0% | 71.5% | 277 | 52.0% | 0.0% | 1.0% | 0.0% | 1.5% |

## Accuracy by level (pass@1)

| Model | Level 1 | Level 2 | Level 3 | Level 4 | Level 5 |
|---|---|---|---|---|---|
| qwen3.5-2b | 88.9% | 81.2% | 83.3% | 46.6% | 45.3% |
| qwen3.5-2b-sft-v2 | 94.4% | 86.1% | 75.6% | 42.6% | 37.3% |
| qwen3.5-2b-bootstrap-r1 | 90.3% | 79.9% | 79.2% | 47.1% | 38.7% |
| qwen3.5-4b | 91.7% | 91.7% | 91.7% | 77.5% | 72.6% |
| qwen3.5-4b-sft | 94.4% | 94.4% | 91.7% | 72.1% | 65.6% |
| qwen3.5-4b-student | 94.4% | 92.4% | 92.3% | 72.1% | 66.0% |
| qwen3.5-4b-sft-gentle | 70.8% | 66.7% | 63.1% | 31.4% | 27.4% |
| qwen3.5-4b-visible-student | 79.2% | 72.9% | 64.9% | 39.2% | 30.7% |

## Accuracy by level (pass@1 with forced answers)

| Model | Level 1 | Level 2 | Level 3 | Level 4 | Level 5 |
|---|---|---|---|---|---|
| qwen3.5-2b | 91.7% | 88.9% | 89.9% | 56.4% | 50.9% |
| qwen3.5-2b-sft-v2 | 95.8% | 86.8% | 81.5% | 47.5% | 42.5% |
| qwen3.5-2b-bootstrap-r1 | 90.3% | 80.6% | 81.0% | 49.5% | 41.0% |
| qwen3.5-4b | 91.7% | 95.1% | 92.9% | 82.8% | 80.2% |
| qwen3.5-4b-sft | 94.4% | 94.4% | 91.7% | 78.9% | 73.6% |
| qwen3.5-4b-student | 94.4% | 94.4% | 92.9% | 76.5% | 70.8% |
| qwen3.5-4b-sft-gentle | 70.8% | 66.7% | 63.1% | 31.4% | 27.8% |
| qwen3.5-4b-visible-student | 79.2% | 72.9% | 64.9% | 39.2% | 30.7% |

## Reasoning length (tokens before </think>)

| Model | All mean | p50 | p90 | Max | Correct mean | p50 | p90 | Max | Wrong (finished) mean | p50 | p90 | Max |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b | 1,812 | 1,024 | 4,096 | 4,096 | 956 | 662 | 1,834 | 4,096 | 1,130 | 849 | 2,639 | 3,698 |
| qwen3.5-2b-sft-v2 | 1,615 | 753 | 4,096 | 4,096 | 727 | 507 | 1,456 | 4,096 | 1,247 | 802 | 3,197 | 4,072 |
| qwen3.5-2b-bootstrap-r1 | 1,179 | 584 | 4,096 | 4,096 | 637 | 452 | 1,304 | 4,096 | 1,043 | 710 | 2,323 | 4,082 |
| qwen3.5-4b | 1,434 | 859 | 4,096 | 4,096 | 1,042 | 757 | 2,190 | 4,096 | 1,111 | 761 | 2,791 | 3,124 |
| qwen3.5-4b-sft | 1,218 | 656 | 4,096 | 4,096 | 778 | 575 | 1,577 | 4,096 | 1,129 | 751 | 2,516 | 3,281 |
| qwen3.5-4b-student | 1,090 | 632 | 3,794 | 4,096 | 756 | 553 | 1,448 | 4,096 | 992 | 744 | 1,988 | 3,241 |
| qwen3.5-4b-sft-gentle | 357 | 165 | 576 | 4,096 | 157 | 125 | 295 | 915 | 329 | 208 | 675 | 3,620 |
| qwen3.5-4b-visible-student | 276 | 156 | 512 | 4,096 | 158 | 120 | 332 | 865 | 326 | 213 | 679 | 3,414 |
