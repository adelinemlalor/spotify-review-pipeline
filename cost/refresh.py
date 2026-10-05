"""Refresh the full-run estimate from a development checkpoint run (offline, reads saved state).

    python cost/refresh.py runs/checkpoint_500 500
    python cost/refresh.py runs/analysis_10000 10000

Writes cost/refresh_<N>.md (included in cost/report.md by the replay command) and
cost/refresh_<N>_calls.jsonl (the measured per-call evidence it was computed from).
"""
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from cost.calculator import base_model, call_items, load_rates  # noqa: E402
from pipeline import export, db  # noqa: E402


def main():
    run_dir, n = Path(sys.argv[1]), int(sys.argv[2])
    rates, _ = load_rates(HERE / "rates.csv")
    con = db.connect(run_dir / "state.db")
    calls = export.calls_rows(con)
    with open(HERE / f"refresh_{n}_calls.jsonl", "w", encoding="utf-8") as f:
        for c in calls:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    summ = json.loads((run_dir / "run_summary.json").read_text())
    distinct = con.execute("SELECT COUNT(DISTINCT text_sha) FROM source WHERE is_empty=0").fetchone()[0]
    stage = {}
    for c in calls:
        s = stage.setdefault(c["role"], {"attempts": 0, "failed": 0, "retries": 0, "fallbacks": 0, "usd": 0.0,
                                         "reviews": 0, "out": 0})
        s["attempts"] += 1
        s["failed"] += c["outcome"] == "failed"
        s["retries"] += c["attempt_kind"] == "invalid_output_retry"
        s["fallbacks"] += c["attempt_kind"] == "fallback"
        s["usd"] += sum(x[3] or 0 for x in call_items(c, rates))
        s["out"] += c["output_tokens"]
        if c["attempt_kind"] == "first":
            s["reviews"] += len(c["review_ids"])
    e = stage["enrich"]
    per_distinct = e["usd"] / distinct
    full_distinct, full_rows = 484189, 660609
    enrich_s = summ["stage_seconds"]["enrich"]
    workers = json.loads(con.execute("SELECT summary FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()[0] or "{}")
    fixed = sum(stage[r]["usd"] for r in ("group", "memo") if r in stage)
    L = [f"## Refresh after the {n:,}-review checkpoint (`{run_dir}`)\n",
         f"Measured: {summ['record_statuses']}, {distinct:,} distinct texts sent, wall clock {summ['wall_clock_s']:.0f} s "
         f"(enrich stage {enrich_s:.0f} s), API cost ${sum(s['usd'] for s in stage.values()):.4f} recomputed from usage x rates.csv.\n",
         "| stage | attempts | failed | invalid-output retries | fallbacks | USD |", "|---|---|---|---|---|---|"]
    for role, s in stage.items():
        L.append(f"| {role} | {s['attempts']} | {s['failed']} | {s['retries']} | {s['fallbacks']} | {s['usd']:.4f} |")
    L.append("")
    L.append(f"- Enrichment cost per distinct text (standard tier, incl. retries/fallbacks): ${per_distinct:.6f}; "
             f"invalid-output retry requests per first request: {e['retries'] / max(1, e['attempts'] - e['retries'] - e['fallbacks']):.3f}; "
             f"fallback requests: {e['fallbacks']}")
    L.append(f"- Enrichment throughput: {distinct / enrich_s:.1f} distinct texts/s at the workers used for this run")
    for label, d in (("with exact-text reuse", full_distinct), ("no reuse", full_rows)):
        std = per_distinct * d
        L.append(f"- Full-run enrichment estimate {label} ({d:,} texts): standard ${std:.2f}; Message Batches (50%) "
                 f"${std / 2:.2f}; realtime time at this throughput {d / (distinct / enrich_s) / 3600:.1f} h; "
                 f"+ fixed group/memo ${fixed:.2f} once; + verification of 1,000 at "
                 f"${stage.get('verify', {}).get('usd', 0) / max(1, stage.get('verify', {}).get('reviews', 1)) * 1000:.2f}")
    L.append("")
    (HERE / f"refresh_{n}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
