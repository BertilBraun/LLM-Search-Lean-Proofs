# miniF2F (Lean 4)

`minif2f.jsonl` is `datasets/minif2f.jsonl` from
[DeepSeek-Prover-V1.5](https://github.com/deepseek-ai/DeepSeek-Prover-V1.5) at commit `2c4ba9119eef`, unchanged
(SHA-256 `d6654c88476ff14db19d57dea25bd955a240525fb52171e460f89d98f83d7dd5`).

488 problems (244 `valid`, 244 `test`), one JSON object per line with `name`, `split`, `informal_prefix`,
`formal_statement` (ends with `:= by\n`), `goal` (DeepSeek's pretty-printed initial goal) and `header` (the same for
all problems; note `set_option maxHeartbeats 0`).

Loaded by `lean_search.data.load_minif2f`.

## License and provenance

miniF2F (Zheng, Han and Polu, 2021, [openai/miniF2F](https://github.com/openai/miniF2F)); its Lean statements are
released under the Apache License 2.0. The Lean 4 port ([yangky11/miniF2F-lean4](https://github.com/yangky11/miniF2F-lean4))
is MIT licensed, as is the DeepSeek-Prover-V1.5 code and data repository (`LICENSE-CODE`).
