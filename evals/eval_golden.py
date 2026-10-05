"""Golden-50 evaluation (offline, no model calls).

Compares saved model predictions with the HUMAN labels in evals/golden_50_human_labels.csv.
Human labels are never sent to any model; they are read only here.

    python evals/eval_golden.py --predictions grading/records.jsonl.gz --out evals/golden_eval

Predeclared tolerances (set before seeing results): sentiment is "close" when
|pred - human| <= 0.3; severity reported as exact agreement, within-1 and MAE.
Alternative accepted labels (alt_topic / alt_intent / alt_severity, '|' separated)
count as correct and are reported separately as ambiguous cases.
"""
import argparse
import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import config  # noqa: E402

SENT_TOL = 0.3


def load_preds(path):
    path = Path(path)
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as f:
        return {r["review_id"]: r for r in map(json.loads, f) if r}


def accepted(row, field):
    vals = [row[field].strip()] + [v.strip() for v in row.get(f"alt_{field}", "").split("|") if v.strip()]
    return [int(v) for v in vals] if field == "severity" else vals


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--labels", default=str(ROOT / "evals" / "golden_50_human_labels.csv"))
    p.add_argument("--predictions", required=True)
    p.add_argument("--out", default=str(ROOT / "evals" / "golden_eval"))
    a = p.parse_args()
    labels = list(csv.DictReader(open(a.labels, encoding="utf-8", newline="")))
    missing = [r["review_id"] for r in labels if not (r["topic"] and r["intent"] and r["severity"])]
    if missing:
        sys.exit(f"{len(missing)} golden rows are not hand-labeled yet (topic/intent/severity blank). Label all 50 first.")
    preds = load_preds(a.predictions)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cases, tally = [], Counter()
    conf = {f: defaultdict(Counter) for f in ("topic", "intent", "severity")}
    sev_err, sent_err = [], []
    for row in labels:
        rid = row["review_id"]
        pr = preds.get(rid)
        valid = bool(pr and pr.get("status") == "completed")
        res = {"review_id": rid, "review_text": row["review_text"], "valid_prediction": valid,
               "ambiguous": row.get("ambiguous", "").lower() in ("yes", "y", "1", "true"),
               "human": {k: row[k] for k in ("topic", "intent", "sentiment", "severity", "evidence_quote", "needs_review")},
               "predicted": {k: pr.get(k) for k in ("topic", "intent", "sentiment", "severity", "evidence_quote",
                                                    "needs_review", "entities")} if valid else None}
        tally["ambiguous"] += res["ambiguous"]
        for f in ("topic", "intent", "severity"):
            acc = accepted(row, f)
            ok = valid and pr[f] in acc
            res[f + "_correct"] = ok
            tally[f] += ok
            conf[f][str(acc[0])][str(pr[f]) if valid else "<missing>"] += 1
        res["all3_correct"] = all(res[f + "_correct"] for f in ("topic", "intent", "severity"))
        tally["all3"] += res["all3_correct"]
        if valid:
            d = abs(pr["severity"] - min(accepted(row, "severity"), key=lambda x: abs(x - pr["severity"])))
            sev_err.append(d)
            tally["severity_within_1"] += d <= 1
            if row["sentiment"].strip():
                e = abs(float(pr["sentiment"]) - float(row["sentiment"]))
                sent_err.append(e)
                tally["sentiment_close"] += e <= SENT_TOL
            res["quote_is_exact_substring"] = pr["evidence_quote"] in row["review_text"]
            tally["quote_exact"] += res["quote_is_exact_substring"]
            hn = row["needs_review"].strip().lower() in ("1", "true", "yes")
            res["needs_review_match"] = bool(pr["needs_review"]) == hn
            tally["needs_review_match"] += res["needs_review_match"]
            tally["needs_review_pred_true"] += bool(pr["needs_review"])
        cases.append(res)
    n = len(labels)
    per_topic = Counter(r["topic"] for r in labels)
    report = {
        "n": n, "valid_predictions": sum(c["valid_prediction"] for c in cases),
        "note": "Missing/quarantined predictions count as incorrect. 50 cases are a diagnostic sample, not a "
                "population accuracy estimate.",
        "agreement": {f: round(tally[f] / n, 4) for f in ("topic", "intent", "severity", "all3")},
        "severity_within_1": round(tally["severity_within_1"] / n, 4),
        "severity_mae": round(sum(sev_err) / len(sev_err), 4) if sev_err else None,
        "sentiment_mae": round(sum(sent_err) / len(sent_err), 4) if sent_err else None,
        "sentiment_within_tolerance": f"{tally['sentiment_close']}/{len(sent_err)} within +/-{SENT_TOL}",
        "quote_exact_substring": f"{tally['quote_exact']}/{n}",
        "needs_review_agreement": f"{tally['needs_review_match']}/{n}",
        "needs_review_predicted_true": tally["needs_review_pred_true"],
        "ambiguous_cases": tally["ambiguous"],
        "human_topic_counts": dict(per_topic),
        "confusion": {f: {h: dict(c) for h, c in conf[f].items()} for f in conf},
        "disagreements": [c["review_id"] for c in cases if not c["all3_correct"]],
    }
    json.dump(report, open(out / "golden_report.json", "w"), indent=1, ensure_ascii=False)
    with open(out / "golden_cases.jsonl", "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(json.dumps({k: report[k] for k in ("n", "valid_predictions", "agreement", "severity_mae", "sentiment_mae",
                                             "quote_exact_substring", "ambiguous_cases")}, indent=1))


if __name__ == "__main__":
    main()
