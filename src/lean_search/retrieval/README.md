# Retrieval

Lemma lists for the policy (Phase 4, ladder row 3): a dense retriever over Mathlib premises, an applicability check
in Lean that annotates the candidates, and the lemma slot of the policy prompt. Enabled per run with
`[policy.retrieval] lemma_count = k` (0, the default, loads nothing and leaves prompts unchanged).

```
node.goals ──encode (ByT5)──▶ top N premises (N = candidate_count, default 32)
           ──exact / apply / rw on the first goal──▶ closes · leaves n goals · no match
           ──order: applicability class, then retrieval score──▶ best k as prompt lines
```

## Retriever (`encoder.py`, `index.py`, `retriever.py`)

ReProver's Lean 4 retriever `kaiyuy/leandojo-lean4-retriever-byt5-small` (revision `ebccee9`, from hf-mirror), used
off the shelf: the ByT5-small encoder (217M parameters, byte tokens, 1024 bytes at most including the end token),
masked mean pooling, unit norm; the score is the dot product. Texts are serialized exactly as ReProver trained:
premises as their declaration source with the name marked `<a>full.name</a>` (`premises.serialize_premise`), goals
as the pretty-printed goals separated by blank lines.

The premise embeddings are precomputed (`experiments/phase4_embed_premises.py`) into
`$LEAN_SEARCH_DATA/retrieval/embeddings/<retriever>/{names.txt,embeddings.npy}` (float16). The deployed index
(`load_premise_index`) keeps the premises that have a signature in the pinned environment: float32 on the CPU,
float16 on a GPU. `BatchingRetriever` serves the concurrent searches of one process: requests that arrive while a
batch is encoded form the next batch, encoded in a worker thread.

Encode on the GPU next to the vLLM server: the bfloat16 encoder and the float16 index take about 1 GiB of the 10%
vLLM leaves free. On the shared CPU of the node one goal takes ~200 ms with 8 threads and batching does not amortize
(`results/phase4_retrieval_latency/`), which competes with the Lean processes of a Lean-bound search.

## Corpus (`environment.py`, `experiments/phase4_premise_names.py`)

LeanDojo Benchmark 4 v10 lists 180,907 premises (Mathlib `29dcec07`, 19 days newer than our pin). Their names are
compared as `Name.toString` with every constant of the pinned environment and printed with `ppSignature`
(`signatures.jsonl`): 174,254 exist and print (3.7% do not exist: renamed Mathlib lemmas, newer Lean core, Aesop,
ProofWidgets).

LeanDojo's corpus only has declarations written in source files, so it lacks `to_additive` translations and
aliases, among them common competition lemmas (`add_comm`, `mul_pos`, `mul_nonneg`, `Finset.sum_range_succ`,
`abs_of_nonneg`, `sub_nonneg`): a quarter of the theorem names that traced competition steps mention. The name check
adds the environment's non-internal theorems outside LeanDojo's corpus, minus compiler-generated companions
(`proof_N`, `eq_N`, `match_N`, `sizeOf_spec`, `inj`, `injEq`) and metaprogramming namespaces (Lean, Mathlib, Aesop,
Std, Batteries, ...), with code `theorem <signature>` synthesized from the signature (`environment_premises.jsonl`):
25,556 theorems, for a deployed index of 199,810 premises.

## Applicability check (`annotation.py`)

Each candidate is tried on the node's state with `ApplicabilityConfig.tactics` (default `exact {name}`,
`apply {name}`, `rw [{name}]`, in order, stopping at the first that closes the first goal), each with 10,000
heartbeats and a 5 s wall-clock backstop, on the search's own REPL. A try counts as

- **closes**: the first goal is gone and no goal replaces it;
- **leaves n goals**: the tactic applied and n goals replace the first (`rw` usually leaves 1);
- **no match**: an error, a timeout or an infrastructure failure.

The best try wins (closes, then fewer goals, then the earlier tactic). Candidates without a match stay in the list:
they may be hints for `nlinarith`, rewrites under binders or lemmas the model applies with arguments. The shown
lemmas are the best k of the N candidates ordered by applicability class, then retrieval score.

Cost on miniF2F-valid roots and traced competition states (32 candidates, 8 processes,
`results/phase4_annotation_cost/`): ~96 tactic calls and 0.75–1.6 Lean-seconds per expansion depending on the
node's load (failing calls take 2–8 ms at the median). Every call leaves a REPL proof state, so a process reaches
the pool's restart threshold (half of 8,000 states) after about 40 expanded nodes. The row-2 search spends ~5.5
Lean-seconds per expansion, so the check adds 15–30%. These seconds are not in the search's `lean_seconds`
accounting; `policy.json` reports them under `lemmas`.

## Prompt lines

One line per lemma: the compact signature (universe parameters, instance arguments and implicit type variables
dropped, cut at `max_signature_characters` = 256) and, if it applied, a comment. The list goes into the existing
slot of the policy prompt (`policy.prompts.user_message`). The user turn for `algebra_sqineq_2unitcircatblt1` with
k = 8, as checked in Lean (the 32 candidates here are the theorems most often named in traced competition steps,
standing in for the retriever until the premise embeddings exist):

````text
Proof state:
```lean
a b : ℝ
h₀ : a ^ 2 + b ^ 2 = 2
⊢ a * b ≤ 1
```

Lemmas that may help:
```lean
mul_comm (a b : G) : a * b = b * a  -- rw: leaves 1 goal
le_of_sub_nonneg {a b : α} : 0 ≤ a - b → b ≤ a  -- apply: leaves 1 goal
sq_nonneg (a : α) : 0 ≤ a ^ 2
Real.sqrt (x : ℝ) : ℝ
mul_pos {a b : α} (ha : 0 < a) (hb : 0 < b) : 0 < a * b
mul_self_nonneg (a : α) : 0 ≤ a * a
Real.sq_sqrt {x : ℝ} (h : 0 ≤ x) : √x ^ 2 = x
div_le_div_iff {a b c d : α} (b0 : 0 < b) (d0 : 0 < d) : a / b ≤ c / d ↔ a * d ≤ c * b
```
````

On Qwen3.5-2B this zero-shot prompt is 320 tokens instead of 101; 32 lemmas make it 870 (about 25 tokens per
lemma). The list differs from node to node, so vLLM's prefix cache cannot share it.

## Configuration

```toml
[policy.retrieval]
lemma_count = 8          # 0 disables retrieval
candidate_count = 32     # retrieved and checked per expansion
device = "cuda:0"        # where goals are encoded and the index lives
cpu_threads = 8          # torch threads when device = "cpu"
max_batch_goals = 32
max_signature_characters = 256

[policy.retrieval.applicability]
tactics = ["exact {name}", "apply {name}", "rw [{name}]"]   # [] keeps the pure retrieval order
heartbeats = 10000
timeout_seconds = 5.0
```

`policy.json` gains `lemmas`: expansions, retrieval wait, check Lean-seconds and tactic calls, candidates and shown
lemmas by applicability, and the encoder's batches.

## Training data (`sft_data.py`, `experiments/phase4_sft_data.py`, `experiments/phase4_sft.py`)

The SFT policies never saw lemma lists, so the ablation uses one lemma-aware adapter for every arm: traced
competition steps whose list length is drawn from 0/4/8/16/32, with candidates retrieved and checked exactly as in
the search. Premises a step names (`premises.step_premises`) that retrieval missed replace random candidates in half
of the lists, so the policy sees listed lemmas being used. The builder runs in stages (select, retrieve on a GPU,
annotate in Lean, finish) and the adapter continues the SFT v2 adapter with the Phase 2 trainer.

## Offline evaluation (`recall.py`, `experiments/phase4_recall.py`)

Recall@k (ReProver's R@k: the mean fraction of a state's gold premises in the top k), hit rate@k and MRR on the
LeanDojo novel-premises validation and test states with at least one gold premise, ranked against all LeanDojo
premises, against the accessible ones (ReProver's protocol) and against the deployed index; and on traced
competition steps whose named premises are the gold set.
