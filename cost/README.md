# Cost and runtime calculator (100-review pilot)

## Offline replay (default: no API key, no model calls)

```bash
.venv/bin/python cost/calculator.py                         # same as: replay
.venv/bin/python cost/calculator.py replay --rate-multiplier 2   # doubling check: API subtotal doubles; time unchanged
```

Edit [`rates.csv`](rates.csv) (dated price sources) or [`scenario.json`](scenario.json) (budget, workers, output cap,
fallback cap, verification sample, retry assumptions), then rerun replay. Importing or opening the calculator never makes
a paid call.

## Explicit paid pilot (separate command)

```bash
.venv/bin/python cost/calculator.py pilot --i-understand-this-costs-money --budget 1
```

This runs the real pipeline (enrich → verify(20) → group → rank → memo) on `data/cost_100.csv` twice. The first run
starts with an empty result cache in a fresh `runs/pilot_100`, using 1 worker. The second run reuses the same saved
cache. The pilot then saves the evidence files below and runs the replay.

## Files

| file | contents |
|---|---|
| [`pilot_records.jsonl`](pilot_records.jsonl) | 100 records (contract row hash, common labels, status), kept separate from `grading/records.jsonl.gz` |
| [`pilot_calls.jsonl`](pilot_calls.jsonl) | every attempt (cold + warm): run ID, request ID, role, exact model, tier, attempt kind, usage by billing item, timing, outcome |
| [`pilot_runs.json`](pilot_runs.json) | cold/warm clock-measured wall time, stage seconds, worker count, input checksum, per-stage config |
| [`rates.csv`](rates.csv) | editable rates in billing units, with source URL and check date; local compute is listed as **unknown** |
| [`usage.csv`](usage.csv) | one row per (call, billing item): units, rate, cost, so every charge maps back to a call in `pilot_calls.jsonl` |
| [`report.md`](report.md) | the measured-100 dashboard, full-run projection (base/conservative, with and without reuse), budget warning, and the refreshes after 500 and 10,000 |
| [`refresh_500.md`](refresh_500.md), [`refresh_10000.md`](refresh_10000.md) | refreshed estimates computed from saved checkpoint runs (`cost/refresh.py`); evidence in `refresh_*_calls.jsonl` |
| [`projection.json`](projection.json) | machine-readable projection lines (stage, model, tier, item, units, USD) |

Formula: `item_cost = billed_units × price_per_unit`, with per-1M-token prices divided by 1,000,000. The billing items
are mutually exclusive: uncached input, 5-minute cache write, cache read and output. Haiku thinking is off, so no
reasoning tokens are billed. Sonnet thinking tokens would already be included in the billed output, so they are never
added again. Batch-tier calls use the batch rows of `rates.csv`. Wall-clock time is measured by a clock. Summed call
durations are shown separately because overlapping calls make them exceed wall time.

Controls demonstrated, with evidence:
- **Spending:** one shared ledger reserves the worst-case cost before every call or batch submission. Admission stops
  when spent + reserved + the next reservation would exceed `--budget`. The mock test hits the budget cap, and the
  full run's log shows the reservations.
- **Output cap:** `max_output_tokens` per request.
- **Concurrency:** `--workers`.
- **Fallback cap:** 0.5% of distinct texts.
- **Retry:** bounded transient retries with exponential backoff and jitter, plus one invalid-output retry. See
  `evals/system_tests_report.json` for the planted transient failure and the planted malformed response.
- **Recovery:** the full-run interruption and resume. See the README section "Interruption and resume".
