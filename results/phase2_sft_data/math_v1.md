# Math worked-solution data `math_v1`

Budget 4,500,000 `Qwen/Qwen3.5-4B` tokens (prompt + solution), caps 1024 prompt and 1024 completion tokens, seed `math-mix`. 12,156 examples, 4,500,622 tokens (mean 370). Visible chat format: the problem plus the \boxed{} instruction, an empty think block, the worked solution as the completion. Contaminated: shares half of the informal 4-grams with one of the 500 MATH-500 or 488 miniF2F statements.

| Source | Candidates | Contaminated | Over length | Selected | Tokens | Solution tokens mean |
|---|---|---|---|---|---|---|
| math_train | 7,500 | 280 | 81 | 6,924 | 2,250,008 | 221 |
| numinamath_cot | 121,035 | 1,045 | 670 | 5,232 | 2,250,614 | 326 |
