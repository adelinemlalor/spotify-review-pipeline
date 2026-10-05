"""Record building and the standardized grading/ export (code only)."""
import gzip
import json
import shutil
from pathlib import Path

from . import common, config


def build_records(con):
    """Exactly one final record per source ID, in source order."""
    out = []
    q = ("SELECT s.review_id, s.row_sha, r.* FROM source s LEFT JOIN results r USING(review_id) ORDER BY s.row_idx")
    for row in con.execute(q):
        rid = row[0]
        rec = {"review_id": rid, "source_sha256": row[1]}
        status = row["status"]
        if status == "completed":
            rec.update(status="completed", topic=row["topic"], intent=row["intent"], sentiment=row["sentiment"],
                       severity=row["severity"], entities=json.loads(row["entities"]),
                       evidence_quote=row["evidence_quote"], needs_review=bool(row["needs_review"]),
                       label_config=row["label_config"], subtopic=row["subtopic"],
                       review_flags=json.loads(row["review_flags"] or "[]"))
            if row["cache_source_id"]:
                rec["cache_source_id"] = row["cache_source_id"]
        elif status == "quarantined":
            rec.update(status="quarantined", reason=row["reason"], attempts=row["attempts"])
        else:
            rec.update(status="quarantined", reason="unresolved_not_classified_in_final_run", attempts=row["attempts"] or 0)
        out.append(rec)
    return out


def write_records_gz(records, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9) as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def calls_rows(con):
    rows = []
    for c in con.execute("SELECT * FROM calls ORDER BY started_at, request_id"):
        rows.append({"request_id": c["request_id"], "role": c["role"], "review_ids": json.loads(c["review_ids"] or "[]"),
                     "model": c["model"], "phase": c["phase"], "outcome": c["outcome"], "label_config": c["label_config"],
                     "input_tokens": c["input_tokens"] or 0, "output_tokens": c["output_tokens"] or 0,
                     "uncached_input_tokens": c["uncached_input_tokens"] or 0,
                     "cache_write_tokens": c["cache_write_tokens"] or 0, "cache_read_tokens": c["cache_read_tokens"] or 0,
                     "tier": c["tier"], "attempt_kind": c["attempt_kind"], "error": c["error"],
                     "stop_reason": c["stop_reason"], "cost_usd": round(c["cost_usd"] or 0, 8), "run_id": c["run_id"],
                     "prompt_version": c["prompt_version"], "started_at": c["started_at"], "ended_at": c["ended_at"],
                     "duration_s": c["duration_s"], "input_artifact": c["artifact"]})
    return rows


def export_grading(con, run_dir, out_dir, input_csv, before_path, after_path):
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    common.write_json(out_dir / "run.json", {"version": "a5-audit-v1", "analysis_count": con.execute(
        "SELECT COUNT(*) FROM source").fetchone()[0], "analysis_sha256": common.file_sha(input_csv),
        "classification_input_fields": ["review_text"], "allow_multi_issue": False})
    print("[export] profiling full input with the provided helper ...")
    common.write_json(out_dir / "ingestion.json", common.checker.profile(input_csv))
    records = build_records(con)
    write_records_gz(records, out_dir / "records.jsonl.gz")
    for name in ("membership.csv", "ranking.csv", "claims.csv"):
        shutil.copyfile(run_dir / "outputs" / name, out_dir / name)
    calls = calls_rows(con)
    with gzip.open(out_dir / "calls.jsonl.gz", "wt", encoding="utf-8") as f:
        for c in calls:
            f.write(json.dumps(c, ensure_ascii=False, separators=(",", ":")) + "\n")
    for src, name in ((before_path, "checkpoint_before.json"), (after_path, "checkpoint_after.json")):
        snap = json.loads(Path(src).read_text())
        common.write_json(out_dir / name, {"completed_ids": snap["completed_ids"], "run_id": snap["run_id"],
                                           "taken_at": snap["taken_at"], "source_snapshot": str(src)})
    print(f"[export] wrote {out_dir} ({len(records)} records, {len(calls)} calls)")
