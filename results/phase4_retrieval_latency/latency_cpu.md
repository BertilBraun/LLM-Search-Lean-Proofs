# Retrieval latency on cpu

miniF2F-valid root goals (mean 97 bytes, p90 164), a random index of the deployed shape (174,254 premises, top 32). Medians over batches.

| Threads | Goals per batch | Encode ms | Search ms | ms per goal |
|---|---|---|---|---|
| 4 | 1 | 280 | 67 | 347 |
| 4 | 8 | 3805 | 116 | 490 |
| 4 | 32 | 25050 | 179 | 788 |
| 8 | 1 | 136 | 63 | 199 |
| 8 | 8 | 1489 | 148 | 205 |
| 8 | 32 | 13594 | 187 | 431 |
