"""System tests (PAID, very small): prompt-injection and odd-input cases, a planted
transient API failure, and a planted malformed model response.

    python evals/run_system_tests.py --i-understand-this-costs-money

All cases are synthetic (IDs start with SYNTH-), run in their own run directory
(runs/system_tests), and are excluded from every business aggregate and from grading/.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import common, enrich, export, prepare  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--i-understand-this-costs-money", action="store_true")
    a = p.parse_args()
    if not a.i_understand_this_costs_money:
        sys.exit("Refusing: makes a few paid API calls. Add --i-understand-this-costs-money.")
    run_dir = ROOT / "runs" / "system_tests"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    con, _ = prepare.prepare(ROOT / "evals" / "synthetic_cases.csv", run_dir, "systest")
    info = enrich.run_enrich(con, run_dir, "systest", budget=0.25, workers=1,
                             faults={"transient_first_call": True, "malformed_first_response": True})
    recs = {r["review_id"]: r for r in export.build_records(con)}
    calls = export.calls_rows(con)
    expected = json.loads((ROOT / "evals" / "synthetic_expected.json").read_text())
    results = {}
    for rid, exp in expected.items():
        if rid.startswith("_"):
            continue
        r = recs[rid]
        checks = {}
        if "expect_status" in exp:
            checks["status"] = r["status"] == exp["expect_status"] and r.get("reason") == exp.get("expect_reason")
        if r["status"] == "completed":
            for k in ("topic", "intent", "severity"):
                if f"expect_{k}_in" in exp:
                    checks[k] = r[k] in exp[f"expect_{k}_in"]
            for k, v in exp.get("must_not", {}).items():
                checks[f"not_{k}_{v}"] = r[k] != v
            if "expect_needs_review" in exp:
                checks["needs_review"] = r["needs_review"] == exp["expect_needs_review"]
            checks["quote_exact"] = r["evidence_quote"] in next(
                row["review_text"] for row in common.csv_rows(ROOT / "evals" / "synthetic_cases.csv") if row["review_id"] == rid)
        results[rid] = {"record": r, "checks": checks, "passed": all(checks.values())}
    report = {"synthetic_test": True, "excluded_from_business_aggregates": True, "enrich_info": info,
              "fault_injection": {
                  "transient_first_call": [c for c in calls if c["attempt_kind"] in ("first", "transient_retry")][:3],
                  "malformed_first_response": [c for c in calls if c.get("error") == "planted_malformed_output_test"
                                               or c["attempt_kind"] == "invalid_output_retry"]},
              "cases": results, "passed": sum(v["passed"] for v in results.values()), "total": len(results),
              "calls": calls}
    common.write_json(ROOT / "evals" / "system_tests_report.json", report)
    for rid, v in results.items():
        print(rid, "PASS" if v["passed"] else "FAIL", v["checks"],
              {k: v["record"].get(k) for k in ("topic", "intent", "severity", "needs_review", "reason")})
    print(f"{report['passed']}/{report['total']} synthetic cases passed; report -> evals/system_tests_report.json")


if __name__ == "__main__":
    main()
