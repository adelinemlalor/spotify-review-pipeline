"""Trace one review through every saved artifact (offline, no model calls).

    python evals/trace_review.py <review_id> [--grading grading] [--run-dir runs/full]

Source row -> enrichment record + the call that produced it -> verifier label (if sampled)
-> issue membership -> ranking row -> claims/memo citations.
"""
import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("review_id")
    p.add_argument("--grading", default=str(ROOT / "grading"))
    p.add_argument("--run-dir", default=str(ROOT / "runs" / "full"))
    a = p.parse_args()
    g, rd, rid = Path(a.grading), Path(a.run_dir), a.review_id
    out = {"review_id": rid}
    src = ROOT / "data" / "spotify_reviews_18months.csv"
    if src.exists():
        sys.path.insert(0, str(ROOT))
        from pipeline.common import csv_rows, row_sha
        for row in csv_rows(src):
            if row["review_id"] == rid:
                out["1_source_row"] = dict(row, computed_row_sha256=row_sha(row))
                break
    rec = next((r for r in jsonl_gz(g / "records.jsonl.gz") if r["review_id"] == rid), None)
    out["2_enriched_record"] = rec
    origin = rec.get("cache_source_id") or rid if rec else rid
    out["2b_producing_calls"] = [c for c in jsonl_gz(g / "calls.jsonl.gz") if origin in c["review_ids"]]
    vpath = rd / "verify" / "verify_comparison.jsonl"
    if vpath.exists():
        out["3_verification"] = next((json.loads(l) for l in open(vpath, encoding="utf-8") if rid in l), "not in verify sample")
    mem = [r for r in csv.DictReader(open(g / "membership.csv", encoding="utf-8")) if r["review_id"] == rid]
    out["4_issue_membership"] = mem
    if mem:
        iid = mem[0]["issue_id"]
        out["5_ranking_row"] = next((r for r in csv.DictReader(open(g / "ranking.csv", encoding="utf-8")) if r["issue_id"] == iid), None)
        out["6_claims"] = [r for r in csv.DictReader(open(g / "claims.csv", encoding="utf-8")) if r["issue_id"] == iid]
        memo = (rd / "outputs" / "memo.md")
        if memo.exists():
            text = memo.read_text()
            out["6_memo_mentions_issue"] = iid in text
            out["6_memo_cites_this_review"] = rid in text
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
