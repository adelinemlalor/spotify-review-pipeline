"""Stage 6 - RECOMMEND (model writes; code checks every citation and number).

Code builds the claims table (claim IDs for issue-level numbers), a context table
for other quantities, and a bounded evidence pack. The memo model sees only
these. Code then checks cited claim/context IDs, issue IDs, review IDs and every
number in the prose; one corrective retry is allowed, and the check result is saved.
"""
import json
import re
from pathlib import Path

from . import common, config, db, llm

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def build_inputs(rank_rows, agg, trows, totals, mapping, coverage, verify_report, top_n=10, quotes_per_issue=4):
    claims, k = [], 0
    for r in rank_rows[:top_n]:
        for metric in ("complaint_count", "severity_sum", "mean_severity", "priority_score"):
            k += 1
            claims.append({"claim_id": f"C{k:03d}", "issue_id": r["issue_id"], "metric": metric, "value": str(r[metric])})
    context, q = [], 0

    def add(label, value):
        nonlocal q
        q += 1
        context.append({"id": f"Q{q:03d}", "quantity": label, "value": str(value)})

    for key in ("source_rows", "completed", "quarantined", "empty_text_quarantined", "other_unresolved"):
        add(f"records: {key}", coverage[key])
    add("completed complaint or cancellation records", totals["complaint_or_cancellation_records"])
    for intent, n in totals["intent_counts"].items():
        add(f"completed records with intent={intent}", n)
    for t in trows:
        add(f"topic {t['topic']}: complaint/cancellation records", t["complaint_or_cancellation_records"])
        add(f"topic {t['topic']}: severity_sum", t["severity_sum"])
        if t["mean_severity"]:
            add(f"topic {t['topic']}: mean severity", t["mean_severity"])
        add(f"topic {t['topic']}: share of all complaint/cancellation records (fraction)", t["share_of_all_complaints"])
        add(f"topic {t['topic']}: cancellation-intent records", t["cancellation_records"])
        add(f"topic {t['topic']}: severity 4-5 records", t["severity_4plus_records"])
    agg_by = {a["issue_id"]: a for a in agg}
    for r in rank_rows[:top_n]:
        a = agg_by[r["issue_id"]]
        add(f"{r['issue_id']}: rank", r["rank"])
        add(f"{r['issue_id']}: cancellation-intent records", a["cancellation_count"])
        add(f"{r['issue_id']}: severity 4-5 records", a["severity_4plus_count"])
    if verify_report:
        add("verifier sample size compared", verify_report["compared"])
        for f, v in verify_report["agreement"].items():
            add(f"verifier agreement ({f}) as fraction", v)
        add("verifier severity mean absolute error", verify_report["severity_mae"])
    evidence = {}
    for r in rank_rows[:6]:
        iss = mapping["issues"].get(r["issue_id"], {})
        evidence[r["issue_id"]] = {"name": iss.get("name"), "coherence": iss.get("coherence"),
                                   "examples": [], "example_ids": iss.get("example_review_ids", [])[:quotes_per_issue]}
    return claims, context, evidence


def check_memo(memo, claims, context, evidence, issue_ids):
    claim_ids = {c["claim_id"]: c for c in claims}
    ctx_ids = {c["id"]: c for c in context}
    allowed_review_ids = {e["review_id"] for v in evidence.values() for e in v["examples"]}
    problems = []
    for cid in re.findall(r"\[(C\d{3})\]", memo):
        if cid not in claim_ids:
            problems.append(f"unknown claim id {cid}")
    for qid in re.findall(r"\[(Q\d{3})\]", memo):
        if qid not in ctx_ids:
            problems.append(f"unknown context id {qid}")
    for iid in set(re.findall(r"ISS-[a-z]+-[a-z_]+[a-z]", memo)):
        if iid not in issue_ids:
            problems.append(f"unknown issue id {iid}")
    for rid in set(UUID_RE.findall(memo)):
        if rid not in allowed_review_ids:
            problems.append(f"review id not in evidence pack {rid}")
    # every number must be a cited claim/context value (IDs, years and severity levels 1-5 exempt)
    allowed = {c["value"] for c in claims} | {c["value"] for c in context}
    scrub = UUID_RE.sub(" ", memo)
    scrub = re.sub(r"\[(?:C|Q)\d{3}\]|ISS-[a-z_-]+|\b(?:19|20)\d{2}(?:-\d{2})?\b", " ", scrub)
    unsupported = []
    for num in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", scrub):
        n = num.replace(",", "")
        if n in allowed or n in {"1", "2", "3", "4", "5"}:
            continue
        unsupported.append(num)
    if unsupported:
        problems.append(f"numbers not traceable to claims/context tables: {sorted(set(unsupported))[:20]}")
    cited = sorted(set(re.findall(r"\[(C\d{3})\]", memo)))
    return {"passed": not problems, "problems": problems, "cited_claim_ids": cited,
            "cited_context_ids": sorted(set(re.findall(r"\[(Q\d{3})\]", memo))),
            "cited_issue_ids": sorted(set(re.findall(r"ISS-[a-z]+-[a-z_]+[a-z]", memo))),
            "cited_review_ids": sorted(set(UUID_RE.findall(memo)))}


def run_memo(con, run_dir, run_id, rank_rows, agg, trows, totals, mapping, coverage, verify_report, records_by_id,
             budget, client=None):
    out = Path(run_dir) / "outputs"
    claims, context, evidence = build_inputs(rank_rows, agg, trows, totals, mapping, coverage, verify_report)
    for iid, ev in evidence.items():
        ev["examples"] = [{"review_id": rid, "quote": records_by_id[rid]["evidence_quote"][:300],
                           "severity": records_by_id[rid]["severity"], "intent": records_by_id[rid]["intent"]}
                          for rid in ev.pop("example_ids")]
    common.write_csv(out / "claims.csv", ["claim_id", "issue_id", "metric", "value"],
                     [[c["claim_id"], c["issue_id"], c["metric"], c["value"]] for c in claims])
    common.write_csv(out / "memo_context.csv", ["id", "quantity", "value"],
                     [[c["id"], c["quantity"], c["value"]] for c in context])
    names = {iid: v.get("name") for iid, v in mapping["issues"].items()}
    payload = {"claims": claims, "context": context, "evidence_pack": evidence,
               "issue_names": {r["issue_id"]: names.get(r["issue_id"]) for r in rank_rows[:10]}}
    common.write_json(out / "memo_inputs.json", payload)
    inputs_hash = common.text_sha(json.dumps(payload, sort_keys=True) + config.MEMO["prompt_version"] + config.MEMO["model"])
    memo_path, check_path = out / "memo.md", out / "memo_check.json"
    if memo_path.exists() and check_path.exists() and json.loads(check_path.read_text()).get("inputs_sha256") == inputs_hash:
        print("[memo] inputs unchanged -> reusing saved memo (0 model calls)")
        return memo_path.read_text(), json.loads(check_path.read_text()), claims

    client = client or llm.get_client()
    system = common.load_prompt("memo_v1.md")
    user = ("CLAIMS (issue-level numbers; cite as [C###]):\n" +
            "\n".join(f"{c['claim_id']} | {c['issue_id']} | {c['metric']} | {c['value']}" for c in claims) +
            "\n\nCONTEXT (other quantities; cite as [Q###]):\n" +
            "\n".join(f"{c['id']} | {c['quantity']} | {c['value']}" for c in context) +
            "\n\nISSUE NAMES (from the grouping role):\n" +
            "\n".join(f"{k}: {v}" for k, v in payload["issue_names"].items()) +
            "\n\nEVIDENCE PACK (exact quotes with review IDs):\n" + json.dumps(evidence, ensure_ascii=False, indent=1))
    ledger = llm.Ledger(budget)
    issue_ids = {r["issue_id"] for r in rank_rows}
    memo, check = None, None
    for attempt in (1, 2):
        text, recs = llm.call(client, config.MEMO, system, user, config.MEMO["max_output_tokens"], [], ledger,
                              {"role": "memo", "run_id": run_id, "phase": "memo",
                               "label_config": f"{config.MEMO['model']}+{config.MEMO['prompt_version']}",
                               "attempt_kind": "first" if attempt == 1 else "check_failed_retry",
                               "artifact": "outputs/memo_inputs.json"}, cache_system=False)
        with db.tx(con):
            for r in recs:
                db.insert_call(con, r)
        if text is None:
            break
        memo = text.strip()
        check = check_memo(memo, claims, context, evidence, issue_ids)
        if check["passed"]:
            break
        user += ("\n\nYOUR PREVIOUS DRAFT FAILED THE CODE CHECK:\n- " + "\n- ".join(check["problems"]) +
                 "\nRewrite the full memo fixing these problems. Previous draft:\n" + memo)
    check = dict(check or {"passed": False, "problems": ["memo call failed"]}, inputs_sha256=inputs_hash, attempts=attempt,
                 model=config.MEMO["model"], prompt_version=config.MEMO["prompt_version"],
                 human_review="Required: a person must read the argument; this check covers IDs and numbers only.")
    if memo:
        memo_path.write_text(memo + "\n", encoding="utf-8")
    common.write_json(check_path, check)
    print(f"[memo] check passed={check['passed']} problems={check.get('problems')}")
    return memo, check, claims
