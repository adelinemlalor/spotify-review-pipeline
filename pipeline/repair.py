"""Declared repair pass for model-output quarantines (not empty texts).

First-pass failures were reviews whose quote never matched the source exactly (stylized
Unicode letters, Bengali script, curly quotes). The repair asks Haiku to label them again
with one extra instruction: the quote field must be `*` (the whole review, an exact
substring by construction). It is a separate prompt version, so it gets its own
label_config. Calls are logged as role=enrich, phase=resume. Anything still invalid
stays quarantined.

    python -m pipeline repair --run-dir runs/full --budget 0.25
"""
import json
from pathlib import Path

from . import common, config, db, enrich, llm

REPAIR = dict(config.ENRICH, prompt_version="enrich-v1-repair1")
NOTE = ("These reviews previously failed validation because the quote was not copied exactly. For every review "
        "below, put * in the quote field (meaning the whole review). Label them with the same rules otherwise. "
        "Return one line per review: idx|topic|subtopic|intent|sentiment|severity|needs_review|*\n")


def run_repair(con, run_dir, run_id, budget, client=None):
    rows = con.execute(
        "SELECT r.review_id, s.review_text, s.text_sha, r.reason FROM results r JOIN source s USING(review_id) "
        "WHERE r.status='quarantined' AND r.reason LIKE 'invalid_model_output%' AND r.cache_source_id IS NULL "
        "AND r.reason NOT LIKE '%(same exact text as%' ORDER BY s.row_idx").fetchall()
    print(f"[repair] {len(rows)} model-output quarantines to retry with {REPAIR['prompt_version']}")
    if not rows:
        return {"repaired": 0}
    client = client or llm.get_client()
    system = common.load_prompt("enrich_v1.md")
    lc = config.label_config(REPAIR)
    ledger = llm.Ledger(budget)
    items = [(k + 1, r["review_id"], r["review_text"]) for k, r in enumerate(rows)]
    text, calls = llm.call(client, REPAIR, system, NOTE + enrich.render_reviews(items), REPAIR["max_output_tokens"],
                           [rid for _, rid, _ in items], ledger,
                           {"role": "enrich", "run_id": run_id, "phase": "resume", "label_config": lc,
                            "attempt_kind": "quarantine_repair"})
    valid, errors = enrich.parse_lines(text, items) if text is not None else ({}, {})
    ts, repaired = common.now(), []
    with db.tx(con):
        for c in calls:
            db.insert_call(con, c)
        for idx, p in valid.items():
            rid = items[idx - 1][1]
            prev = next(r["reason"] for r in rows if r["review_id"] == rid)
            p["review_flags"] += ["quarantine_repair_pass", "first_pass: " + prev[:120]]
            con.execute(
                "UPDATE results SET status='completed', topic=?, subtopic=?, intent=?, sentiment=?, severity=?, "
                "entities=?, evidence_quote=?, needs_review=?, review_flags=?, label_config=?, reason=NULL, "
                "attempts=attempts+1, request_id=?, model=?, run_id=?, phase='resume', updated_at=? WHERE review_id=?",
                (p["topic"], p["subtopic"], p["intent"], p["sentiment"], p["severity"], json.dumps(p["entities"]),
                 p["evidence_quote"], int(p["needs_review"]), json.dumps(p["review_flags"]), lc,
                 calls[-1]["request_id"], calls[-1]["model"], run_id, ts, rid))
            con.execute("INSERT OR REPLACE INTO text_cache VALUES (?,?,?,?)",
                        (con.execute("SELECT text_sha FROM source WHERE review_id=?", (rid,)).fetchone()[0], lc, rid,
                         json.dumps(p, ensure_ascii=False)))
            repaired.append(rid)
    report = {"prompt_version": REPAIR["prompt_version"], "label_config": lc, "attempted": len(rows),
              "repaired": len(repaired), "still_quarantined": [r["review_id"] for r in rows if r["review_id"] not in repaired],
              "errors": {items[i - 1][1]: e for i, e in errors.items()}, "request_ids": [c["request_id"] for c in calls],
              "cost_usd": sum(c.get("cost_usd") or 0 for c in calls), "run_id": run_id}
    common.write_json(Path(run_dir) / "repair_report.json", report)
    enrich.snapshot(con, run_dir, run_id, "after_repair")
    print(f"[repair] repaired {len(repaired)}/{len(rows)}; cost ${report['cost_usd']:.4f}")
    return report
