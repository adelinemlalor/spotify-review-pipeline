"""Orchestrator CLI. Code chooses every next step; models are called only inside
the enrich / verify / group / memo roles.

  python -m pipeline run --input data/cost_100.csv --run-dir runs/pilot_100 --budget 1   (PAID)
  python -m pipeline rank --records grading/records.jsonl.gz --membership grading/membership.csv --out /tmp/rerank
  python -m pipeline export --run-dir runs/full --out grading --before ... --after ...
  python -m pipeline status --run-dir runs/full
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from . import common, config, db, enrich, export, group, memo, prepare, rank, verify

STAGES = ("prepare", "enrich", "verify", "group", "rank", "memo")


def coverage(records):
    c = Counter(r["status"] for r in records)
    empty = sum(1 for r in records if r.get("reason") == "empty_review_text")
    return {"source_rows": len(records), "completed": c["completed"], "quarantined": c["quarantined"],
            "empty_text_quarantined": empty, "other_unresolved": c["quarantined"] - empty,
            "cache_reuse_records": sum(1 for r in records if r.get("cache_source_id"))}


def cmd_run(a):
    run_dir = Path(a.run_dir)
    run_id = time.strftime("%Y%m%dT%H%M%S")
    stages = a.stages.split(",") if a.stages else list(STAGES)
    t_all = time.monotonic()
    log = run_dir / "run_log.jsonl"
    timings = {}

    def log_stage(stage, t0, **info):
        timings[stage] = round(time.monotonic() - t0, 3)
        entry = {"run_id": run_id, "stage": stage, "at": common.now(), "seconds": timings[stage], **info}
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    t0 = time.monotonic()
    con, ingest = prepare.prepare(a.input, run_dir, run_id)
    log_stage("prepare", t0, records=ingest["records"], distinct=ingest["distinct_nonempty_texts"])
    with db.tx(con):
        con.execute("INSERT INTO runs(run_id, command, started_at, budget_usd, workers, mode) VALUES (?,?,?,?,?,?)",
                    (run_id, " ".join(sys.argv), common.now(), a.budget, a.workers, a.mode))
    faults = {f: True for f in (a.inject_fault or [])}
    spent_before = db.spent_usd(con)
    info = {}
    if "enrich" in stages:
        t0 = time.monotonic()
        if a.mode == "batch":
            info = enrich.run_enrich_batch_api(con, run_dir, run_id, a.budget, chunk_size=a.batch_chunk,
                                               max_chunks=a.max_chunks)
        else:
            info = enrich.run_enrich(con, run_dir, run_id, a.budget, workers=a.workers, max_requests=a.max_requests,
                                     faults=faults)
        log_stage("enrich", t0, **info)
        if info.get("stop_reason", "completed") not in ("completed", "nothing_pending") or a.stop_after_enrich:
            finish(con, run_dir, run_id, t_all, timings, spent_before, info, partial=True)
            return
    records = export.build_records(con)
    out = run_dir / "outputs"
    export.write_records_gz(records, out / "records.jsonl.gz")
    common.write_jsonl(out / "quarantine.jsonl", [r for r in records if r["status"] == "quarantined"])
    cov = coverage(records)
    verify_report = None
    if "verify" in stages:
        t0 = time.monotonic()
        verify_report = verify.run_verify(con, run_dir, run_id, a.verify_n, a.budget)
        log_stage("verify", t0, compared=verify_report["compared"], agreement=verify_report["agreement"])
    elif (run_dir / "verify" / "verify_report.json").exists():
        verify_report = json.loads((run_dir / "verify" / "verify_report.json").read_text())
    if "group" in stages:
        t0 = time.monotonic()
        mapping = group.run_group(con, run_dir, run_id, records, a.budget)
        log_stage("group", t0, issues=len(mapping["issues"]))
    if "rank" in stages:
        t0 = time.monotonic()
        rank_rows, agg, trows, totals = rank.write_all(records, rank.load_membership(out / "membership.csv"), out)
        log_stage("rank", t0, issues=len(rank_rows))
    if "memo" in stages:
        t0 = time.monotonic()
        mapping = json.loads((out / "group_mapping.json").read_text())
        _, check, _ = memo.run_memo(con, run_dir, run_id, rank_rows, agg, trows, totals, mapping, cov, verify_report,
                                    {r["review_id"]: r for r in records}, a.budget)
        log_stage("memo", t0, check_passed=check["passed"])
    finish(con, run_dir, run_id, t_all, timings, spent_before, info, partial=False, cov=cov)


def finish(con, run_dir, run_id, t_all, timings, spent_before, info, partial, cov=None):
    wall = round(time.monotonic() - t_all, 3)
    calls = con.execute("SELECT role, outcome, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd), "
                        "SUM(cache_read_tokens), SUM(cache_write_tokens) FROM calls WHERE run_id=? GROUP BY role, outcome",
                        (run_id,)).fetchall()
    statuses = dict(con.execute("SELECT COALESCE(r.status,'pending'), COUNT(*) FROM source s LEFT JOIN results r "
                                "USING(review_id) GROUP BY 1").fetchall())
    summary = {"run_id": run_id, "partial": partial, "wall_clock_s": wall, "stage_seconds": timings,
               "enrich": info, "record_statuses": statuses, "coverage": cov,
               "calls_this_invocation": [{"role": r[0], "outcome": r[1], "attempts": r[2], "input_tokens": r[3],
                                          "output_tokens": r[4], "cost_usd": round(r[5] or 0, 6),
                                          "cache_read_tokens": r[6], "cache_write_tokens": r[7]} for r in calls],
               "spend_this_invocation_usd": round(db.spent_usd(con) - spent_before, 6),
               "spend_all_invocations_usd": round(db.spent_usd(con), 6),
               "cost_basis": "computed from provider-reported usage x config.PRICES (standard or batch tier)"}
    with db.tx(con):
        con.execute("UPDATE runs SET ended_at=?, wall_s=?, stop_reason=?, summary=? WHERE run_id=?",
                    (common.now(), wall, info.get("stop_reason"), json.dumps(summary, default=str), run_id))
    common.write_json(Path(run_dir) / f"run_summary_{run_id}.json", summary)
    common.write_json(Path(run_dir) / "run_summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("run_id", "partial", "wall_clock_s", "record_statuses",
                                              "spend_this_invocation_usd")}, indent=1))


def cmd_rank(a):
    records = rank.load_records(a.records)
    rank.write_all(records, rank.load_membership(a.membership), a.out)


def cmd_export(a):
    con = db.connect(Path(a.run_dir) / "state.db")
    export.export_grading(con, a.run_dir, a.out, a.input, a.before, a.after)


def cmd_status(a):
    con = db.connect(Path(a.run_dir) / "state.db")
    print(dict(con.execute("SELECT COALESCE(r.status,'pending'), COUNT(*) FROM source s LEFT JOIN results r "
                           "USING(review_id) GROUP BY 1").fetchall()))
    print("spent_usd", round(db.spent_usd(con), 4))
    for r in con.execute("SELECT role, phase, outcome, COUNT(*), SUM(cost_usd) FROM calls GROUP BY 1,2,3"):
        print(tuple(r))


def main():
    p = argparse.ArgumentParser(prog="python -m pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run stages on an input CSV (enrich/verify/group/memo make PAID model calls)")
    r.add_argument("--input", required=True)
    r.add_argument("--run-dir", required=True)
    r.add_argument("--stages", help=f"comma list from {','.join(STAGES)} (default: all)")
    r.add_argument("--budget", type=float, default=config.DEFAULT_BUDGET_USD, help="USD spend cap per stage invocation")
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--mode", choices=("realtime", "batch"), default="realtime")
    r.add_argument("--batch-chunk", type=int, default=2000)
    r.add_argument("--max-chunks", type=int)
    r.add_argument("--max-requests", type=int, help="stop enrichment after N requests (controlled interruption)")
    r.add_argument("--stop-after-enrich", action="store_true")
    r.add_argument("--verify-n", type=int, default=20)
    r.add_argument("--inject-fault", action="append", choices=("transient_first_call", "malformed_first_response"))
    r.set_defaults(fn=cmd_run)
    k = sub.add_parser("rank", help="OFFLINE: regenerate ranking from saved records + membership (no model calls)")
    k.add_argument("--records", required=True)
    k.add_argument("--membership", required=True)
    k.add_argument("--out", required=True)
    k.set_defaults(fn=cmd_rank)
    e = sub.add_parser("export", help="write the standardized grading/ folder")
    e.add_argument("--run-dir", required=True)
    e.add_argument("--out", default="grading")
    e.add_argument("--input", default=str(config.FULL_CSV))
    e.add_argument("--before", required=True)
    e.add_argument("--after", required=True)
    e.set_defaults(fn=cmd_export)
    s = sub.add_parser("status")
    s.add_argument("--run-dir", required=True)
    s.set_defaults(fn=cmd_status)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
