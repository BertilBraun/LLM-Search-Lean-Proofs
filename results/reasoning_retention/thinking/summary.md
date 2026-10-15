# Reasoning retention on MATH-500

200 MATH-500 problems stratified by level and subject (seed `reasoning-retention`), thinking on, k = 4 samples at temperature 0.6 (top-p 0.95), at most 4096 generated tokens; the answer is the last \boxed{} after the thinking block. Forced answers: a sample cut off at the cap gets its thinking closed with `</think>` (if still open) and `The final answer is $\boxed{`, then at most 64 tokens to finish the box (budget forcing); this separates reasoning from stopping.

| Model | pass@1 (mean over k) | any@4 | Mean generated tokens | pass@1 with forced answers | Forced answers correct | Truncated | Thinking unfinished | No boxed answer |
|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b | 9.0% | 22.5% | 3,934 | 66.6% | 63.6% | 90.6% | 89.8% | 0.9% |
| qwen3.5-2b-sft-v2 | 17.0% | 33.0% | 3,733 | 67.8% | 61.6% | 82.4% | 80.4% | 2.0% |
| qwen3.5-2b-bootstrap-r1 | 47.0% | 60.0% | 2,899 | 69.2% | 44.1% | 50.5% | 48.4% | 2.2% |
| qwen3.5-4b | 22.1% | 38.0% | 3,683 | 80.9% | 76.4% | 76.9% | 73.1% | 3.8% |
| qwen3.5-4b-sft | 25.2% | 42.0% | 3,553 | 80.1% | 74.3% | 73.9% | 71.0% | 2.9% |
| qwen3.5-4b-student | 40.8% | 56.0% | 3,170 | 83.4% | 73.2% | 58.2% | 55.8% | 2.5% |
| qwen3.5-4b-visible-student | 0.0% | 0.0% | 351 | 0.2% | 12.5% | 2.0% | 100.0% | 0.0% |

## Accuracy by level (pass@1)

| Model | Level 1 | Level 2 | Level 3 | Level 4 | Level 5 |
|---|---|---|---|---|---|
| qwen3.5-2b | 26.4% | 19.4% | 7.7% | 3.9% | 1.9% |
| qwen3.5-2b-sft-v2 | 47.2% | 34.0% | 19.0% | 5.4% | 4.7% |
| qwen3.5-2b-bootstrap-r1 | 88.9% | 75.0% | 60.1% | 26.5% | 23.1% |
| qwen3.5-4b | 63.9% | 38.9% | 25.0% | 9.3% | 6.6% |
| qwen3.5-4b-sft | 56.9% | 45.8% | 31.5% | 11.8% | 8.5% |
| qwen3.5-4b-student | 88.9% | 66.0% | 44.0% | 28.4% | 16.5% |
| qwen3.5-4b-visible-student | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

## Accuracy by level (pass@1 with forced answers)

| Model | Level 1 | Level 2 | Level 3 | Level 4 | Level 5 |
|---|---|---|---|---|---|
| qwen3.5-2b | 90.3% | 84.7% | 85.1% | 46.1% | 51.4% |
| qwen3.5-2b-sft-v2 | 90.3% | 86.8% | 80.4% | 48.5% | 55.7% |
| qwen3.5-2b-bootstrap-r1 | 95.8% | 87.5% | 86.3% | 54.9% | 48.1% |
| qwen3.5-4b | 90.3% | 93.1% | 91.1% | 70.1% | 71.7% |
| qwen3.5-4b-sft | 93.1% | 93.8% | 89.9% | 67.6% | 70.8% |
| qwen3.5-4b-student | 95.8% | 95.1% | 91.7% | 71.1% | 76.4% |
| qwen3.5-4b-visible-student | 0.0% | 0.0% | 0.0% | 1.0% | 0.0% |

## Reasoning length (tokens before </think>)

| Model | All mean | p50 | p90 | Max | Correct mean | p50 | p90 | Max | Wrong (finished) mean | p50 | p90 | Max |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b | 3,893 | 4,096 | 4,096 | 4,099 | 1,930 | 2,005 | 2,955 | 3,553 | 2,452 | 2,524 | 2,596 | 2,596 |
| qwen3.5-2b-sft-v2 | 3,666 | 4,096 | 4,096 | 4,098 | 1,690 | 1,453 | 3,104 | 3,687 | 1,734 | 1,195 | 3,732 | 3,732 |
| qwen3.5-2b-bootstrap-r1 | 2,715 | 3,739 | 4,096 | 4,096 | 1,317 | 1,042 | 2,810 | 3,706 | 1,361 | 1,061 | 2,987 | 3,240 |
| qwen3.5-4b | 3,573 | 4,096 | 4,096 | 4,096 | 1,862 | 1,661 | 3,248 | 3,645 | 2,324 | 2,641 | 3,098 | 3,098 |
| qwen3.5-4b-sft | 3,441 | 4,096 | 4,096 | 4,098 | 1,617 | 1,457 | 2,769 | 3,744 | 1,664 | 1,447 | 3,107 | 3,107 |
| qwen3.5-4b-student | 2,991 | 4,096 | 4,096 | 4,096 | 1,465 | 1,235 | 2,741 | 3,650 | 1,701 | 1,631 | 3,612 | 3,612 |
| qwen3.5-4b-visible-student | 350 | 196 | 636 | 4,096 | – | – | – | – | 274 | 190 | 574 | 2,070 |
