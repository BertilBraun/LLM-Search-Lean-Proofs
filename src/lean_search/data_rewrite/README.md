# Data rewrite for the SFT stage before GRPO

The gentle fine-tune from visible student v2 (DESIGN.md, "Starting policy and the SFT stage before GRPO") trains on
rewritten data: proofs without nested `have … := by` blocks, chunks of k consecutive top-level tactics
(k ∈ {1, 3, 5, 7, rest of the proof}), some of them with a teacher-written explanation so that they train the visible
mode the GRPO loop samples in, flattened visible-reasoning examples, and, for the naming A/B, a copy with descriptive
hypothesis names. Entry point: `experiments/data_rewrite.py`; configs in `experiments/configs/data_rewrite/`.

## Running it on the node

```bash
# 0. Inputs: $LEAN_SEARCH_DATA/normalized/proofs/selected_for_tracing.jsonl (the normalization pipeline),
#    sft/4b and reasoning/visible_student_v2 (generated data), the reasoning runs' states.jsonl under $LEAN_SEARCH_RUNS
#    (phase5_visible_teacher_9b, phase5_visible_self_4b, phase5_teacher_9b; from node_backup/).
# 1. The namer: a larger model behind an OpenAI-compatible endpoint (or set `model = ""` for rule-based names only).
deployment/serve_model.sh namer Qwen/Qwen3.5-9B 0 8120
# 2. The Lean pass: flatten, re-trace, rename, replay; resumable by shard (rerun the same command after a stop).
python experiments/data_rewrite.py rewrite \
    --config experiments/configs/data_rewrite/rewrite_visible_student_v2.toml --run-name data_rewrite_v1
# 2b. The teacher: the same 9B writes the explanations of the chunks planned for the visible mode; replicas on the
#     free GPUs (explain_chunks.toml lists all four servers; drop the ones not started). Resumable by shard.
for gpu in 1 2 3; do deployment/serve_model.sh teacher-$gpu Qwen/Qwen3.5-9B $gpu $((8120 + gpu)); done
python experiments/data_rewrite.py explain --config experiments/configs/data_rewrite/explain_chunks.toml \
    --build-config experiments/configs/data_rewrite/build_named.toml
for name in namer teacher-1 teacher-2 teacher-3; do deployment/stop_model.sh $name; done
# 3. Both arms of the naming A/B (same items, chunks and explanations, only the names differ).
python experiments/data_rewrite.py build --config experiments/configs/data_rewrite/build_numbered.toml \
    --name visible_student_v3_numbered
python experiments/data_rewrite.py build --config experiments/configs/data_rewrite/build_named.toml \
    --name visible_student_v3_named
# 4. The two short fine-tunes from visible student v2.
torchrun --nproc-per-node 2 experiments/phase5_reasoning_sft.py \
    --config experiments/configs/data_rewrite/sft_numbered.toml --run-name data_rewrite_sft_numbered
torchrun --nproc-per-node 2 experiments/phase5_reasoning_sft.py \
    --config experiments/configs/data_rewrite/sft_named.toml --run-name data_rewrite_sft_named
```

`--max-proofs`, `--max-examples` and `--pool-size` override the config for a pilot (use a new run name: the shard plan
is fixed per run). Lean cost: one flat replay and one renamed replay per item, a replay of the original for flat
replays that fail, and a full verification of 10% of the renamed proofs.

## What it reports

`rewrite` writes `$LEAN_SEARCH_RUNS/<run>/{proofs,examples}/<shard>.jsonl` (`RewrittenProof`, `RewrittenExample`:
status, flat tactics with the goals before each and after the last, the named version with its renaming and states)
and `summary/{README.md,summary.json}`: counts kept and dropped per reason with a few Lean messages each, separately
for proofs and reasoning examples and for their named versions, the original-statement checks, top-level tactics
before and after flattening, and how many names the model gave and why proposals were rejected
(`experiments/data_rewrite.py summary --run-name <run>` re-renders it). After `explain` it also holds the chunk
explanations: explained / rejected / request failed, how many on the retry, every rejected reply per reason with a few
texts, and the length of the accepted explanations. `explain` writes
`$LEAN_SEARCH_RUNS/<run>/explanations/<shard>.jsonl` (`ChunkExplanation`: the chunk's position, outcome, the named
explanation, the numbered one renamed back, the rejected replies).

`build` writes `$LEAN_SEARCH_DATA/reasoning/<name>/`: `train.jsonl` and `validation.jsonl` (`ReasoningExample`, the
format `phase5_reasoning_sft.py` trains on; an explained chunk is a visible example, origin `rationalized`, the others
are non-reasoning `replay` examples; validation lists the non-visible chunks first for the trainer's greedy check,
then the visible chunks, then the reasoning examples), `math.jsonl` (the input data's math replay, copied),
`chunks_*.jsonl` (each chunk with its start and end state, start index, tactic count, drawn length and explanation)
and `README.md`/`summary.json` (the train composition and its non-visible share, the outcome of every chunk planned for
the visible mode and the teacher's rejected replies, explanation lengths, the block-length distribution of the train
visible-mode examples before and after adding the explained chunks, examples per drawn length and per tactic count,
start states dropped per reason, duplicates, token statistics per part).

An explained chunk example (illustrative), named arm (`ReasoningExample`; the numbered arm has `h₀` and `h₁` for
`hx_pos` and `hx_sq` in goals, block and explanation alike):

```json
{"proof_identifier": "…", "step_index": 2, "goals": ["x : ℝ\nhx_pos : 0 < x\n⊢ 0 < x ^ 2 + 1"],
 "tactic_block": "have hx_sq : 0 < x ^ 2\npositivity\nnlinarith [hx_sq, hx_pos]",
 "reasoning": "Since `hx_pos` makes $x$ positive, first record that $x^2 > 0$; with that fact the goal is linear in $x^2$.",
 "thinking_instruction": "", "origin": "rationalized", "visible": true}
```

It trains exactly as the loop samples: the visible prompt (`render_prompt(…, visible=True)`) and the completion
`render_visible_completion(reasoning, tactic_block)`, i.e. the explanation, a blank line, the fenced block, end of turn.

| Rejected teacher reply | Meaning |
|---|---|
| `truncated`, `empty`, `too_short`, `too_long` | cut at `max_tokens`, or outside 30–1,000 characters (the reasoning data's explanations: p1 38, p99 ~1,000) |
| `markup`, `label`, `code_block` | think or chat tags, a leading `**…**`/`#`/`Explanation:` label, a fenced block |
| `long_inline_code` | an inline code span over 80 characters or over several lines (the data's p99: 44) |
| `forbidden_token` | a forbidden tactic in inline code, or in prose where it is no English word (`native_decide`, `polyrith`, …) |
| `not_english` | Cyrillic, Arabic, Thai or CJK characters |
| `copies_block` | the whole block (24+ characters) verbatim |
| `line_by_line` | at least two and at least half of the block's tactics quoted verbatim with their arguments (12+ characters each) |
| `mentions_given_block` | "the given/provided/above tactics", … (the explanation is written before the block) |
| `stale_name`, `unrenamed_name` | the named text mentions a replaced numbered name, also as `h_0` or `h_{0}`; or a descriptive name survives the renaming back (`hx\_pos`) |

| Drop reason | Meaning |
|---|---|
| `nested_have_remains` | (reasoning examples) flattening refused a nested proof in the block (binders after the name, holes in the type, goal-list tactics such as `all_goals`, inside `cases … with \| … =>` alternatives, a bare `·` line, `:=` with `by` on the next line), so it would stay nested |
| `nested_have` (build) | a chunk containing such a tactic of a kept proof: the start state falls back to a shorter chunk or is dropped |
| `start_failed` | the statement does not elaborate |
| `original_fails` | neither the flat nor the original proof replays here |
| `flattening_changed_behaviour` | the original replays but the flat one does not, or a flattened nested proof closed its goal early, left it open or touched outer goals |
| `state_not_found`, `state_mismatch` | (reasoning examples) no run state for the example, or replaying the reference steps does not reach its prompt |
| `original_block_fails` | (reasoning examples) the sampled block no longer applies |
| `name_conflict` | (named) the statement's new name is already used in this proof |
| `replay_failed`, `states_differ` | (named) the renamed proof does not replay, or its states are not the numbered ones with the names replaced |
| `original_check_failed` | (named) the renamed proof with `rename'` does not verify against the original statement |

## Decisions

- **Flattening** is the harness's `plan_block` (`flatten_proof` is its text). The flat proof is replayed tactic by
  tactic and every flattened nested proof must keep to its goal (`segment_verdict`, the search's guard): closed exactly
  at its last tactic, outer goals untouched. A proof whose flattening changes behaviour is **dropped, not kept in its
  original form**: the original would teach exactly the nested blocks the fine-tune is meant to remove, and the
  sources are large. Where flattening refuses a nested proof, it stays inside one top-level tactic: the proof is kept
  and only the chunks containing that tactic are dropped (a reasoning example, whose block is kept whole, is
  dropped). Comments inside flattened proofs disappear; tactics after the proof is closed are cut (as in the
  tracing).
- **Chunks**: every state of a flat proof is a prompt once (as in today's one-tactic data); its chunk length is drawn
  from the configured weights by a stable hash of proof and position, clipped at the end of the proof. A chunk over the
  token caps (2,048 prompt, 512 completion: the policy writes blocks in visible mode under a 1,280-token cap) or with
  forbidden tokens falls back to the next shorter configured length. Identical (state, chunk) pairs are kept once.
- **Visible chunk examples** (the loop samples in visible mode, so block lengths taught only in the non-visible format
  might not transfer): `visible_chunk_examples_per_reasoning_example = 1` train chunks per train reasoning example (and
  500 validation chunks) are planned for the visible mode and get a teacher-written explanation. The teacher is the
  rewrite pass's namer model (Qwen3.5-9B, thinking off, temperature 0.7), shown the state and the known block, asked
  for the plan written *before* the block (what to do and why, a few sentences, no code blocks, Lean only as short
  inline names), with four real visible explanations of the reasoning data as few-shot turns (train split, sampled
  not condensed, named, flat block, one each with 1, 2, 3 and 4+ tactics; the same prefix for every request, so the
  server's prefix cache holds it). Its reply is checked (table above); a rejected reply is retried once, and a chunk
  without an accepted explanation stays a non-visible example (counted per outcome). On the 11,727 visible
  explanations of `visible_student` the checks accept 97.1% (rejected: 1.5% `copies_block`, 1.0% `too_long`, the rest
  under 0.2% each).
- **Explanations and names**: the explanation is written once, on the named chunk (the numbered one when nothing is
  renamed), and the numbered arm's text is the inverse renaming of it (whole identifiers, LaTeX-quoted ones included).
  Spellings that would escape the inverse renaming are rejected (`stale_name`, `unrenamed_name`), so the two arms'
  explanations differ in the names alone: renaming the numbered one gives the named one.
- **Mode mix**: `non_visible_share = 0.5` of the train examples are plain non-visible chunk examples, the build's share
  before the visible chunks (one per reasoning example), so the reasoning-free mode keeps its weight. With one visible
  chunk per reasoning example this doubles the train set (per reasoning example: one visible chunk, two non-visible;
  rejected explanations add to the non-visible ones); `non_visible_share = 1/3` would keep the non-visible count of
  before instead (v2 replayed 0.21 one-tactic steps per reasoning example). The validation set lists the 500
  non-visible chunks first (the trainer's greedy check reads them), then the 500 visible ones.
- **Reasoning examples are never chunked**: an explanation describes its whole block, so the block is kept whole and
  flattened and the explanation unchanged (flattening changes the layout, not what the block does). An example is
  kept only if its state rebuilds from the reasoning run's `states.jsonl` (statement plus reference steps) to exactly
  its prompt, its original block applies, and the flat block applies with the segment guards and ends in the same
  goals. The input's replay examples (one-tactic Lean steps) are replaced by chunk examples; the 10% thinking traces
  are rewritten like the visible examples.
- **What is renamed**: statement binders whose name matches `renamed_pattern` (`h`, `h₀`, `h1`, …; a bare `h` only if
  its type looks like a proposition: `h : ℝ` is a variable) and `have` names matching it anywhere in the proof text.
  Names bound by `obtain`/`intro`/`rcases` patterns have no type to name them by and stay numbered, and so does a
  `have` name bound more than once (reused in another branch, rebound by a pattern): one description would name two
  facts. A statement hypothesis is renamed everywhere, a `have` shadowing it included; every occurrence of an old
  name getting the same fresh name keeps the meaning whatever the scopes.
- **Who names**: statement hypotheses once per statement from the statement alone, exactly as at search time, shared
  by all its proofs and examples; then each text's `have`s with the renamed statement as context. The model's names
  are untrusted: ASCII snake case starting with `h`, not numbered, at most 20 characters, no keyword or root constant
  of the pinned environment, unused in the statement and proof text, distinct. A rejected proposal is replaced by the
  rule-based name (`hx_pos` for `0 < x`, `habc` for `a + b + c = 1`, `ha0` for `a 0 = 1`, `hp_prime`, …; `_2`
  appended when taken).
- **How**: renaming is textual on whole identifiers (not fields after `.`, not `h₀'` or `h₁₀`) in the statement,
  tactics and explanations; the prompts' states come from Lean, by replaying the renamed statement and proof, and must
  equal the numbered states with the names replaced (whitespace-insensitive: longer names wrap differently).
- **Same items in both arms**: an item enters the data only if it is usable numbered and named, and a chunk only if it
  fits in both, so the A/B differs in the names alone.
- **Splits**: proofs by the tracing's statement hash (`assign_split`), reasoning examples by their input file.

## Renaming at search time and the check against the original statement

A renamed statement is alpha-equivalent to the original. A proof found for it is checked against the original by
prefixing Mathlib's `rename' h₀ => hx_pos, h₁ => h_sum` (the original's root state then has the new names) and
verifying with `verify_proof` on the original statement (tested in the pinned Lean 4 v4.9.0-rc1 / Mathlib). Not
wired into the search yet; to wire it:

```python
from lean_search.data_rewrite.model_namer import open_namer
from lean_search.data_rewrite.statement_renaming import rename_statements, verify_against_original

async with open_namer(rewrite_config.namer, rewrite_config.naming) as namer:  # the data's namer and NamingConfig
    renamings = await rename_statements(statements, namer, rewrite_config.naming, reserved)
# Search renaming.statement instead of the original (same header, same theorem name). For a found proof:
verification = await verify_against_original(repl, header, renaming.original, renaming.changes, state.proof)
```

`reserved` is the root constants and keywords of `identifiers.environment_names` (as the rewrite pass uses); the
rule-based namer (`RuleBasedNamer`) needs no server. Records should keep `renaming.changes` so a proof can be mapped
back to the original statement later (`proof_of_original`).

## Local sample run (WSL, 2 REPLs, rule-based names)

240 complete proofs rebuilt from the visible runs' traced states (183 with nested `have … := by`) and 120 visible
reasoning examples (40 with nested blocks), 0.9 Lean-hours. Proofs: 239 kept, 1 `flattening_changed_behaviour` (a
flattened step hit the wall clock); 3,197 flat top-level tactics from 849 original ones; 30 kept proofs hold a tactic
flattening refused. Named, among the kept: 178 renamed, 58 nothing to rename, 2 `states_differ`, 1 `name_conflict`;
40 of 40 sampled renamed proofs verify against the original statement with `rename'`. Reasoning examples: 118 kept,
1 `nested_have_remains`, 1 `flattening_changed_behaviour` (`simp made no progress`); named: 92 renamed, 26 nothing to
rename. Build (all chunks, both arms identical): 236 proofs and 118 examples usable in both, 3,037 chunk examples
(drawn 1/3/5/7/rest: 592/625/612/620/588; by tactics in the completion 1: 834, 2: 172, 3: 662, 4: 90, 5: 504, 6: 51,
7: 526, 8+: 198); start states dropped: 90 prompt over 2,048 tokens, 46 only chunks with a refused nested proof, 3
completion over 512 tokens. Explanations rename LaTeX-quoted names too (`$h3$` becomes `$hxy_ge_2$`).

## Teacher throughput on the node (estimate, not measured)

- **Chunks in the full build**: the sample run gives 12.9 chunk examples per usable proof (3,037 from 236, about 4.0
  tactics each). With `max_proofs = 20000` and 98% usable that is about 250,000 chunk candidates, of which the build
  takes far fewer: per train reasoning example (about 9,000 from `visible_student_v2`) one visible and two non-visible
  chunks, so about 9,000 visible and 18,000 non-visible train chunk examples, plus 500 of each for validation (about
  36,000 train examples with the reasoning examples). Only the visible ones are explained: about 9,500 chunks.
- **Requests**: about 11,000 with retries (assuming 15% of first replies rejected; the checks reject 3% of the
  reasoning data's own explanations). Per request: a shared prefix of about 1,400 tokens (system prompt and four
  few-shot turns, cached by vLLM after the first request per server), about 400 uncached prompt tokens (state ~150,
  block ~130, instruction and framing ~120) and about 100 generated tokens (the data's explanations average ~70; the
  9B's visible explanations had a median of 95). In total about 4.4M uncached prompt and 1.1M generated tokens.
- **Wall time on 4× RTX 3090** (one 9B replica per GPU, bf16 weights ~19 GB, so 2–3 GB for KV and recurrent state):
  prefill at about 1,200–1,500 tokens/s per GPU (35.6 dense bf16 TFLOPS with fp32 accumulation at 50–60%, 18 GFLOP
  per token) is the larger part, about 50–60 GPU-minutes, plus about 8 GPU-minutes of decoding at the ~2,300 generated
  tokens/s per GPU measured for the visible 9B teacher: **about 1 GPU-hour, 15–20 minutes on four GPUs**, about an
  hour on the namer's GPU alone. The prefix cache matters: without it the few-shot prefix adds about 15M prompt tokens
  (3–4 hours on four GPUs). Explaining every candidate instead of the planned chunks would take about 25 times as long.
