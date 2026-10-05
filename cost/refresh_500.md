## Refresh after the 500-review checkpoint (`runs/checkpoint_500`)

Measured: {'completed': 500}, 479 distinct texts sent, wall clock 70 s (enrich stage 41 s), API cost $0.1290 recomputed from usage x rates.csv.

| stage | attempts | failed | invalid-output retries | fallbacks | USD |
|---|---|---|---|---|---|
| enrich | 11 | 0 | 1 | 0 | 0.0754 |
| verify | 1 | 0 | 0 | 0 | 0.0115 |
| group | 3 | 0 | 0 | 0 | 0.0107 |
| memo | 1 | 0 | 0 | 0 | 0.0314 |

- Enrichment cost per distinct text (standard tier, incl. retries/fallbacks): $0.000157; invalid-output retry requests per first request: 0.100; fallback requests: 0
- Enrichment throughput: 11.8 distinct texts/s at the workers used for this run
- Full-run enrichment estimate with exact-text reuse (484,189 texts): standard $76.18; Message Batches (50%) $38.09; realtime time at this throughput 11.4 h; + fixed group/memo $0.04 once; + verification of 1,000 at $0.23
- Full-run enrichment estimate no reuse (660,609 texts): standard $103.93; Message Batches (50%) $51.97; realtime time at this throughput 15.6 h; + fixed group/memo $0.04 once; + verification of 1,000 at $0.23

