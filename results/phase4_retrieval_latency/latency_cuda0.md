# Retrieval latency on cuda:0

miniF2F-valid root goals (mean 97 bytes, p90 164), the deployed index (199,810 premises, top 32). Encoder in the search's precision (bfloat16 on a GPU, float32 on the CPU). Medians over batches. Peak GPU memory allocated by torch: 1.86 GiB.

| Threads | Goals per batch | Encode ms | Search ms | ms per goal |
|---|---|---|---|---|
| - | 1 | 13 | 1 | 14 |
| - | 8 | 20 | 1 | 3 |
| - | 32 | 94 | 2 | 3 |
