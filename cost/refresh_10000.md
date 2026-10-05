## Refresh after the 10,000-review checkpoint (`runs/analysis_10000`)

Measured: {'completed': 10000}, 8,448 distinct texts sent, wall clock 448 s (enrich stage 401 s), API cost $1.4971 recomputed from usage x rates.csv.

| stage | attempts | failed | invalid-output retries | fallbacks | USD |
|---|---|---|---|---|---|
| enrich | 195 | 0 | 23 | 3 | 1.4019 |
| verify | 4 | 0 | 0 | 0 | 0.0430 |
| group | 5 | 0 | 0 | 0 | 0.0211 |
| memo | 1 | 0 | 0 | 0 | 0.0311 |

- Enrichment cost per distinct text (standard tier, incl. retries/fallbacks): $0.000166; invalid-output retry requests per first request: 0.136; fallback requests: 3
- Enrichment throughput: 21.1 distinct texts/s at the workers used for this run
- Full-run enrichment estimate with exact-text reuse (484,189 texts): standard $80.35; Message Batches (50%) $40.17; realtime time at this throughput 6.4 h; + fixed group/memo $0.05 once; + verification of 1,000 at $0.21
- Full-run enrichment estimate no reuse (660,609 texts): standard $109.62; Message Batches (50%) $54.81; realtime time at this throughput 8.7 h; + fixed group/memo $0.05 once; + verification of 1,000 at $0.21

