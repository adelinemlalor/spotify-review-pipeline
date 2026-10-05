"""Stage 3 - VERIFY (independent model + code comparison).

A declared, seeded random sample of directly-classified records is re-labeled
by a different model (Sonnet 5.5) from the original text only. Code compares
the two labelings and writes a disagreement report. A separate planted-error
copy (deliberately wrong labels) checks that the comparison catches errors.
"""
import hashlib
import json
from pathlib import Path

from . import common, config, db, llm


def sample_ids(con, n):
    rows = con.execute("SELECT r.review_id FROM results r WHERE r.status='completed' AND r.cache_source_id IS NULL "
                       "AND r.request_id IS NOT NULL").fetchall()
    key = lambda rid: hashlib.sha256(f"{config.VERIFY['seed']}:{rid}".encode()).hexdigest()
    return sorted((r[0] for r in rows), key=key)[:n]


def parse_verify(raw, n):
    out = {}
    for line in (raw or "").splitlines():
        parts = [p.strip() for p in line.strip().split("|")]
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        i, topic, intent, sev = int(parts[0]), parts[1], parts[2], parts[3]
        if 1 <= i <= n and topic in config.TOPICS and intent in config.INTENTS and sev in {"1", "2", "3", "4", "5"}:
            out[i] = {"topic": topic, "intent": intent, "severity": int(sev)}
    return out


def compare(primary, verifier):
    rows, agree = [], {"topic": 0, "intent": 0, "severity": 0, "all3": 0}
    abs_err, n = 0, 0
    for rid, p in primary.items():
        v = verifier.get(rid)
        if not v:
            rows.append({"review_id": rid, "verifier": None, "status": "verifier_missing"})
            continue
        n += 1
        same = {f: p[f] == v[f] for f in ("topic", "intent", "severity")}
        for f, ok in same.items():
            agree[f] += ok
        agree["all3"] += all(same.values())
        abs_err += abs(p["severity"] - v["severity"])
        rows.append({"review_id": rid, "primary": {k: p[k] for k in ("topic", "intent", "severity")}, "verifier": v,
                     "agree": same, "status": "agree" if all(same.values()) else "disagree"})
    rates = {f: round(c / n, 4) if n else None for f, c in agree.items()}
    return {"compared": n, "agreement": rates, "severity_mae": round(abs_err / n, 4) if n else None}, rows


def run_verify(con, run_dir, run_id, n, budget, client=None):
    out_dir = Path(run_dir) / "verify"
    cache_path = out_dir / "verifier_predictions.json"
    ids = sample_ids(con, n)
    texts = {r[0]: r[1] for r in con.execute(
        f"SELECT review_id, review_text FROM source WHERE review_id IN ({','.join('?' * len(ids))})", ids)}
    cached = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    if cached.get("prompt_version") != config.VERIFY["prompt_version"] or cached.get("model") != config.VERIFY["model"]:
        cached = {"prompt_version": config.VERIFY["prompt_version"], "model": config.VERIFY["model"], "labels": {}}
    todo = [rid for rid in ids if rid not in cached["labels"]]
    print(f"[verify] declared sample={len(ids)} (seed {config.VERIFY['seed']}), already verified={len(ids) - len(todo)}")
    if todo:
        client = client or llm.get_client()
        system = common.load_prompt("verify_v1.md")
        ledger = llm.Ledger(budget)
        for start in range(0, len(todo), config.VERIFY["max_reviews_per_request"]):
            chunk = todo[start:start + config.VERIFY["max_reviews_per_request"]]
            items = [(k + 1, rid, texts[rid]) for k, rid in enumerate(chunk)]
            user = "\n".join(f'<r i="{i}">{t}</r>' for i, _, t in items)
            text, recs = llm.call(client, config.VERIFY, system, user, config.VERIFY["max_output_tokens"], chunk, ledger,
                                  {"role": "verify", "run_id": run_id, "phase": "verify",
                                   "label_config": f"{config.VERIFY['model']}+{config.VERIFY['prompt_version']}"},
                                  cache_system=False)
            with db.tx(con):
                for r in recs:
                    db.insert_call(con, r)
            got = parse_verify(text, len(items))
            for i, lab in got.items():
                cached["labels"][items[i - 1][1]] = lab
            common.write_json(cache_path, cached)
    primary = {}
    for r in con.execute(f"SELECT review_id, topic, intent, severity FROM results WHERE review_id IN "
                         f"({','.join('?' * len(ids))})", ids):
        primary[r[0]] = {"topic": r[1], "intent": r[2], "severity": r[3]}
    summary, rows = compare(primary, cached["labels"])
    for row in rows:
        row["review_text"] = texts[row["review_id"]]
    common.write_jsonl(out_dir / "verify_comparison.jsonl", rows)

    # Planted-error test: a SEPARATE copy where every 5th sampled record gets a deliberately wrong topic.
    planted = {}
    for k, (rid, p) in enumerate(sorted(primary.items())):
        q = dict(p)
        if k % 5 == 0:
            q["topic"] = next(t for t in ("billing", "downloads", "support") if t != p["topic"])
            q["planted"] = True
        planted[rid] = q
    psum, prows = compare(planted, cached["labels"])
    planted_ids = [rid for rid, q in planted.items() if q.get("planted") and rid in cached["labels"]]
    caught = sum(1 for r in prows if r["review_id"] in planted_ids and not r["agree"]["topic"])
    planted_report = {"synthetic_test": True, "excluded_from_business_aggregates": True,
                      "planted_wrong_topics": len(planted_ids), "flagged_by_comparison": caught,
                      "detection_rate": round(caught / len(planted_ids), 4) if planted_ids else None,
                      "note": "Planted errors live only in this test copy; production records are unchanged."}
    report = dict(summary, declared_sample_size=n, seed=config.VERIFY["seed"], verifier_model=config.VERIFY["model"],
                  verifier_prompt=config.VERIFY["prompt_version"], enricher_label_config=config.label_config(),
                  disagreements=sum(r["status"] == "disagree" for r in rows), planted_error_test=planted_report)
    common.write_json(out_dir / "verify_report.json", report)
    print(f"[verify] agreement {summary['agreement']}, severity MAE {summary['severity_mae']}, "
          f"planted errors caught {caught}/{len(planted_ids)}")
    return report
