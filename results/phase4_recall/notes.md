# Notes on the recall tables

- The LeanDojo rows are an upper bound. `kaiyuy/leandojo-lean4-retriever-byt5-small` was most likely trained on
  LeanDojo Benchmark 4's random split, whose training theorems include the novel-premises validation and test
  theorems, so those states are probably not held out from the checkpoint.
- The competition row is held out from the retriever entirely and matches what the search sees: traced
  validation-split competition steps (statements held out by hash) whose text names a theorem of the deployed index,
  that theorem being gold. 3,216 of 8,336 steps (39%) name one. For 22% of them a named theorem is in the top 8, for
  43% in the top 32.
- `deployed` ranks the search's index: LeanDojo premises that exist in the pinned environment plus the 25,556 added
  environment theorems (`results/phase4_premise_names/`); gold premises are restricted to existing ones.
