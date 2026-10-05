"""Stage 1 - PREPARE (code only, no model calls).

Reads every row of the input CSV with a multiline-safe parser, preserves the six
original field strings, computes the contract row hash, profiles quality, finds
exact duplicate texts and loads the pending-work table.
"""
import json
from collections import Counter
from pathlib import Path

from . import common, config, db


def prepare(input_csv, run_dir, run_id):
    input_csv = Path(input_csv)
    con = db.connect(Path(run_dir) / "state.db")
    existing = con.execute("SELECT COUNT(*) FROM source").fetchone()[0]
    file_hash = common.file_sha(input_csv)
    if existing:
        stored = con.execute("SELECT detail FROM events WHERE kind='ingest' ORDER BY id DESC LIMIT 1").fetchone()
        if stored and json.loads(stored[0]).get("file_sha256") != file_hash:
            raise SystemExit("Run directory already holds a different input file; use a new --run-dir.")
        print(f"[prepare] source already loaded ({existing} rows); skipping re-ingest")
        return con, json.loads((Path(run_dir) / "ingestion_report.json").read_text())

    ratings, months, text_counts = Counter(), Counter(), Counter()
    empty_ids, missing_version, invalid_rating = [], 0, 0
    rows = []
    first = last = None
    for idx, row in enumerate(common.csv_rows(input_csv)):
        text = row["review_text"]
        is_empty = not text.strip()
        ts = row["review_timestamp"]
        first = min(first, ts) if first else ts
        last = max(last, ts) if last else ts
        ratings[row["review_rating"]] += 1
        months[ts[:7]] += 1
        if row["review_rating"] not in {"1", "2", "3", "4", "5"}:
            invalid_rating += 1
        if not row["app_version"].strip():
            missing_version += 1
        if is_empty:
            empty_ids.append(row["review_id"])
        else:
            text_counts[text] += 1
        rows.append((row["review_id"], idx, common.row_sha(row), common.text_sha(text), text, row["review_rating"],
                     row["review_likes"], row["app_version"], ts, int(is_empty)))

    ids = [r[0] for r in rows]
    dup_ids = len(ids) - len(set(ids))
    if dup_ids:
        raise SystemExit(f"{dup_ids} duplicate review IDs; refusing to continue (IDs must be unique).")
    with db.tx(con):
        con.executemany("INSERT INTO source VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    repeated = {t: c for t, c in text_counts.items() if c > 1}
    report = {
        "input_path": str(input_csv),
        "file_sha256": file_hash,
        "file_bytes": input_csv.stat().st_size,
        "matches_course_full_file": file_hash == config.FULL_SHA256,
        "parser": "python csv.DictReader(strict=True), utf-8-sig, newline='' (multiline-safe)",
        "records": len(rows),
        "duplicate_review_ids": dup_ids,
        "empty_review_text": len(empty_ids),
        "empty_review_text_ids": empty_ids,
        "nonempty_to_classify": len(rows) - len(empty_ids),
        "distinct_nonempty_texts": len(text_counts),
        "exact_duplicate_text_rows_reusable": (len(rows) - len(empty_ids)) - len(text_counts),
        "texts_repeated_more_than_once": len(repeated),
        "top_repeated_texts": [{"text": t, "rows": c} for t, c in Counter(repeated).most_common(15)],
        "missing_app_version": missing_version,
        "invalid_rating_values": invalid_rating,
        "reviews_by_rating": dict(sorted(ratings.items())),
        "reviews_by_month": dict(sorted(months.items())),
        "first_review": first,
        "last_review": last,
        "quarantine_rule": "empty/whitespace-only review_text -> status quarantined, reason empty_review_text",
        "note": "Missing app_version does not block classification; star rating is metadata only.",
    }
    common.write_json(Path(run_dir) / "ingestion_report.json", report)
    db.log_event(con, run_id, "ingest", {"file_sha256": file_hash, "records": len(rows)}, common.now())
    print(f"[prepare] {len(rows)} rows, {len(empty_ids)} empty, {len(text_counts)} distinct nonempty texts")
    return con, report
