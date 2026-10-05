"""Stage 5 - RANK (code only, no model calls, fully reproducible from saved files).

priority(issue) = complaint_count x mean_severity = severity_sum (exact integers).
Sorted by descending score, then ascending issue ID. Means exported with six
decimals, decimal half-up.

Offline:  python -m pipeline rank --records grading/records.jsonl.gz --membership grading/membership.csv --out <dir>
"""
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

from . import common, config


def load_records(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_membership(path):
    with open(path, encoding="utf-8", newline="") as f:
        return [(r["issue_id"], r["review_id"]) for r in csv.DictReader(f)]


def ranking(records, membership):
    by_id = {r["review_id"]: r for r in records if r.get("status") == "completed"}
    sev = defaultdict(list)
    seen = set()
    for iid, rid in membership:
        if (iid, rid) in seen or rid not in by_id or by_id[rid]["intent"] not in ("complaint", "cancellation"):
            continue
        seen.add((iid, rid))
        sev[iid].append(by_id[rid]["severity"])
    rows = [{"issue_id": iid, "complaint_count": len(v), "severity_sum": sum(v),
             "mean_severity": common.mean_string(sum(v), len(v)), "priority_score": sum(v)} for iid, v in sev.items()]
    rows.sort(key=lambda x: (-x["priority_score"], x["issue_id"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def aggregates(records, membership, rank_rows):
    """Extra descriptive columns per issue (not part of the baseline score)."""
    by_id = {r["review_id"]: r for r in records}
    stats = defaultdict(lambda: Counter())
    sent = defaultdict(float)
    for iid, rid in membership:
        r = by_id[rid]
        s = stats[iid]
        s["cancellation"] += r["intent"] == "cancellation"
        s["sev4plus"] += r["severity"] >= 4
        s["sev5"] += r["severity"] == 5
        s["needs_review"] += bool(r["needs_review"])
        s["cache_reuse"] += bool(r.get("cache_source_id"))
        sent[iid] += r["sentiment"]
    out = []
    for r in rank_rows:
        s, n = stats[r["issue_id"]], r["complaint_count"]
        out.append(dict(r, cancellation_count=s["cancellation"], severity_4plus_count=s["sev4plus"],
                        severity_5_count=s["sev5"], needs_review_count=s["needs_review"],
                        cache_reuse_count=s["cache_reuse"], mean_sentiment=common.mean_string(round(sent[r["issue_id"]] * 100), n * 100)))
    return out


def topic_rollup(records):
    completed = [r for r in records if r.get("status") == "completed"]
    total = len(completed)
    neg = [r for r in completed if r["intent"] in ("complaint", "cancellation")]
    rows = []
    for t in config.TOPICS:
        tr = [r for r in neg if r["topic"] == t]
        sev = sum(r["severity"] for r in tr)
        rows.append({"topic": t, "complaint_or_cancellation_records": len(tr), "severity_sum": sev,
                     "mean_severity": common.mean_string(sev, len(tr)) if tr else "",
                     "cancellation_records": sum(r["intent"] == "cancellation" for r in tr),
                     "severity_4plus_records": sum(r["severity"] >= 4 for r in tr),
                     "share_of_all_complaints": common.mean_string(len(tr), len(neg)) if neg else "",
                     "all_completed_records_in_topic": sum(r["topic"] == t for r in completed)})
    intents = Counter(r["intent"] for r in completed)
    return rows, {"completed_records": total, "complaint_or_cancellation_records": len(neg),
                  "intent_counts": dict(sorted(intents.items()))}


def write_all(records, membership, out_dir):
    out_dir = Path(out_dir)
    rank_rows = ranking(records, membership)
    cols = ["rank", "issue_id", "complaint_count", "severity_sum", "mean_severity", "priority_score"]
    common.write_csv(out_dir / "ranking.csv", cols, [[r[c] for c in cols] for r in rank_rows])
    agg = aggregates(records, membership, rank_rows)
    acols = cols + ["cancellation_count", "severity_4plus_count", "severity_5_count", "needs_review_count",
                    "cache_reuse_count", "mean_sentiment"]
    common.write_csv(out_dir / "aggregates.csv", acols, [[r[c] for c in acols] for r in agg])
    trows, totals = topic_rollup(records)
    tcols = list(trows[0].keys())
    common.write_csv(out_dir / "topic_rollup.csv", tcols, [[r[c] for c in tcols] for r in trows])
    common.write_json(out_dir / "rank_totals.json", totals)
    print(f"[rank] {len(rank_rows)} issues ranked -> {out_dir / 'ranking.csv'}")
    return rank_rows, agg, trows, totals
