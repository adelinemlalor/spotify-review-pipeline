"""100-review cost and runtime calculator.

DEFAULT (offline, no API key, no model calls):
    python cost/calculator.py                # == replay
    python cost/calculator.py replay [--rates cost/rates.csv] [--scenario cost/scenario.json] [--rate-multiplier 2]

EXPLICIT PAID PILOT (makes real API calls; needs ANTHROPIC_API_KEY in .env):
    python cost/calculator.py pilot --i-understand-this-costs-money

Replay recomputes every cost from saved per-call usage (pilot_calls.jsonl) x editable
rates (rates.csv). Importing this module never starts paid calls.
"""
import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ITEMS = ("uncached_input", "cache_write", "cache_read", "output")
USAGE_FIELD = {"uncached_input": "uncached_input_tokens", "cache_write": "cache_write_tokens",
               "cache_read": "cache_read_tokens", "output": "output_tokens"}


# ------------------------------------------------------------------ loading
def load_rates(path, multiplier=1.0):
    rates, local = {}, []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["provider"] == "local":
                local.append(r)
                continue
            per_unit = float(r["usd_per_unit"]) * multiplier
            if r["unit"] == "1M tokens":
                per_unit /= 1_000_000  # price quoted per million -> per token
            rates[(r["model"], r["tier"], r["item"])] = {"per_token": per_unit, **r}
    return rates, local


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def base_model(model_id):
    """Exact served ID (e.g. claude-haiku-4-5-20251001) -> rate-card alias (claude-haiku-4-5)."""
    import re
    return re.sub(r"-\d{8}$", "", model_id)


def call_items(call, rates):
    """Mutually exclusive billing items for one call: units x price per unit."""
    out = []
    for item in ITEMS:
        units = call.get(USAGE_FIELD[item], 0) or 0
        rate = rates.get((base_model(call["model"]), call.get("tier") or "standard", item))
        if rate is None:
            out.append((item, units, None, None))  # unknown rate -> visibly unresolved
        else:
            out.append((item, units, rate["per_token"], units * rate["per_token"]))
    return out


# ------------------------------------------------------------------ measured
def measured(calls, rates, records, runs):
    by_run_role = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    usage_rows = []
    for c in calls:
        s = by_run_role[c["pilot_run"]][c["role"]]
        s["attempts"] += 1
        s["succeeded"] += c["outcome"] == "succeeded"
        s["failed"] += c["outcome"] == "failed"
        s["retries"] += c.get("attempt_kind") in ("invalid_output_retry", "transient_retry", "check_failed_retry")
        s["fallbacks"] += c.get("attempt_kind") == "fallback"
        s["reviews_sent"] += len(c["review_ids"])
        s["call_seconds_summed"] += c.get("duration_s") or 0
        for item, units, per_token, cost in call_items(c, rates):
            s[item] += units
            if cost is None:
                s["unknown_cost_items"] += 1
            else:
                s["cost_usd"] += cost
            usage_rows.append([c["pilot_run"], c["request_id"], c["role"], c["model"], c.get("tier") or "standard", item,
                               units, "" if per_token is None else f"{per_token * 1e6:.4f}",
                               "" if cost is None else f"{cost:.8f}"])
    return by_run_role, usage_rows


# ------------------------------------------------------------------ projection
def project(calls, rates, scen, runs, n_pilot_issues):
    cold = [c for c in calls if c["pilot_run"] == "cold"]
    enrich_first = [c for c in cold if c["role"] == "enrich" and c.get("attempt_kind") == "first" and c["outcome"] == "succeeded"]
    reviews_first = sum(len(c["review_ids"]) for c in enrich_first)
    req_first = len(enrich_first)
    tok = lambda cs, f: sum(c.get(f, 0) or 0 for c in cs)
    sys_per_req = (tok(enrich_first, "cache_read_tokens") + tok(enrich_first, "cache_write_tokens")) / req_first
    unc_per_review = tok(enrich_first, "uncached_input_tokens") / reviews_first
    out_per_review = tok(enrich_first, "output_tokens") / reviews_first
    reviews_per_req = reviews_first / req_first
    retry_reviews = sum(len(c["review_ids"]) for c in cold if c.get("attempt_kind") == "invalid_output_retry")
    fb_reviews = sum(len(c["review_ids"]) for c in cold if c.get("attempt_kind") == "fallback")
    transient = sum(1 for c in cold if c["role"] == "enrich" and c["outcome"] == "failed")
    measured_rates = {"invalid_retry_rate": retry_reviews / reviews_first, "fallback_rate": fb_reviews / reviews_first,
                      "transient_failure_rate": transient / max(1, req_first)}
    enrich_secs = sum(c.get("duration_s") or 0 for c in enrich_first) or 1e-9
    per_worker_throughput = reviews_first / enrich_secs  # reviews/s for one worker (measured)

    def price(model, tier, item):
        r = rates.get((model, tier, item))
        return None if r is None else r["per_token"]

    def scenario(name, distinct):
        s = scen[name]
        tier = scen["enrich_tier"]
        rr = measured_rates["invalid_retry_rate"] if s.get("invalid_retry_rate") == "measured" else \
            max(s["invalid_retry_rate_min"], measured_rates["invalid_retry_rate"] * s["invalid_retry_multiplier"])
        fr = measured_rates["fallback_rate"] if s.get("fallback_rate") == "measured" else s["fallback_rate"]
        fr = min(fr, scen["max_fallback_fraction"])
        wf = s["cache_write_requests_fraction"]
        omult = s.get("output_tokens_multiplier", 1.0)
        requests = math.ceil(distinct / reviews_per_req)
        retry_requests = math.ceil(distinct * rr / 2)  # retries carry ~2 reviews each
        m = "claude-haiku-4-5"
        lines = []

        def add(stage, model, tier_, item, units):
            p = price(model, tier_, item)
            lines.append({"stage": stage, "model": model, "tier": tier_, "item": item, "units": round(units),
                          "usd": None if p is None else units * p})

        add("enrich", m, tier, "uncached_input", distinct * unc_per_review)
        add("enrich", m, tier, "cache_read", requests * sys_per_req * (1 - wf))
        add("enrich", m, tier, "cache_write", requests * sys_per_req * wf)
        add("enrich", m, tier, "output", distinct * out_per_review * omult)
        # invalid-output retries run realtime (standard tier) with the cached system prompt
        add("enrich_retry", m, "standard", "uncached_input", distinct * rr * unc_per_review * 1.3)
        add("enrich_retry", m, "standard", "cache_read", retry_requests * sys_per_req)
        add("enrich_retry", m, "standard", "output", distinct * rr * out_per_review * omult)
        fb = "claude-sonnet-5-5"
        fb_reviews_n = distinct * fr
        add("enrich_fallback", fb, "standard", "cache_write", math.ceil(fb_reviews_n / 2) * sys_per_req)
        add("enrich_fallback", fb, "standard", "uncached_input", fb_reviews_n * unc_per_review)
        add("enrich_fallback", fb, "standard", "output", fb_reviews_n * out_per_review * 1.5)
        # verification: cost per verified review measured in the pilot x declared full-run sample
        v = [c for c in cold if c["role"] == "verify" and c["outcome"] == "succeeded"]
        v_reviews = sum(len(c["review_ids"]) for c in v) or 1
        for item in ITEMS:
            add("verify", "claude-sonnet-5-5", "standard", item, tok(v, USAGE_FIELD[item]) / v_reviews * scen["verify_sample_full_run"])
        # group: per-request usage x requests needed for all candidate issues (fixed taxonomy, 10 issues/request)
        g = [c for c in cold if c["role"] == "group" and c["outcome"] == "succeeded"]
        g_req_full = math.ceil(46 / 10)
        for item in ITEMS:
            add("group", "claude-haiku-4-5", "standard", item, (tok(g, USAGE_FIELD[item]) / max(1, len(g))) * g_req_full)
        # memo: fixed overhead, once (not multiplied by reviews)
        mm = [c for c in cold if c["role"] == "memo"]
        for item in ITEMS:
            add("memo", "claude-sonnet-5-5", "standard", item, tok(mm, USAGE_FIELD[item]) * (1 if name == "base" else 2))
        total = sum(x["usd"] for x in lines if x["usd"] is not None)
        unknown = [x for x in lines if x["usd"] is None]
        # time: realtime estimate is MODELED (measured 1-worker throughput x workers, linear assumption)
        workers = scen["max_workers"]
        rt_hours = distinct / (per_worker_throughput * workers) / 3600 * (1 + rr + measured_rates["transient_failure_rate"])
        return {"scenario": name, "distinct_texts_sent": distinct, "enrich_requests": requests,
                "assumed_retry_rate": round(rr, 5), "assumed_fallback_rate": round(fr, 5), "cache_write_fraction": wf,
                "lines": lines, "total_usd": total, "unknown_items": len(unknown),
                "exceeds_budget": total > scen["budget_usd"],
                "modeled_realtime_hours": round(rt_hours, 2), "workers": workers}

    out = {"pilot_derived": {"reviews_per_request": reviews_per_req, "system_tokens_per_request": sys_per_req,
                             "uncached_input_tokens_per_review": unc_per_review, "output_tokens_per_review": out_per_review,
                             "measured_rates": measured_rates, "one_worker_reviews_per_second": per_worker_throughput},
           "scenarios": []}
    for distinct, label in ((scen["distinct_nonempty_texts"], "with exact-text reuse"), (scen["nonempty_rows"], "no reuse")):
        for name in ("base", "conservative"):
            s = scenario(name, distinct)
            s["reuse"] = label
            out["scenarios"].append(s)
    return out


# ------------------------------------------------------------------ report
def fmt(x, d=4):
    return "unknown" if x is None else f"{x:,.{d}f}"


def replay(args):
    rates, local = load_rates(args.rates, args.rate_multiplier)
    scen = json.loads(Path(args.scenario).read_text())
    calls = load_jsonl(HERE / "pilot_calls.jsonl")
    records = load_jsonl(HERE / "pilot_records.jsonl")
    runs = json.loads((HERE / "pilot_runs.json").read_text())
    by, usage_rows = measured(calls, rates, records, runs)
    with open(HERE / "usage.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["pilot_run", "request_id", "role", "model", "tier", "item", "units", "usd_per_1M", "usd"])
        w.writerows(usage_rows)
    proj = project(calls, rates, scen, runs, None)
    ids_csv = [r["review_id"] for r in csv.DictReader(open(ROOT / "data" / "cost_100.csv", encoding="utf-8", newline=""))]
    texts = {r["review_id"]: r["review_text"] for r in csv.DictReader(open(ROOT / "data" / "cost_100.csv", encoding="utf-8", newline=""))}
    completed = sum(r["status"] == "completed" for r in records)
    quarantined = sum(r["status"] == "quarantined" for r in records)
    L = []
    L.append("# 100-review cost and runtime report\n")
    L.append(f"Generated by `python cost/calculator.py replay` (offline; no API key; rate multiplier = {args.rate_multiplier}).\n")
    L.append("## Measured pilot (real calls on data/cost_100.csv)\n")
    cold_run = next(r for r in runs if r["run"] == "cold")
    L.append(f"- Input: `data/cost_100.csv`, sha256 `{cold_run['input_sha256']}` "
             f"(manifest match: {cold_run['input_sha256'] == 'c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e'})")
    L.append(f"- Saved pilot IDs = cost_100.csv IDs: {sorted(ids_csv) == sorted(r['review_id'] for r in records)} "
             f"({len(records)} records)")
    L.append(f"- Completed {completed}, quarantined {quarantined}, unique texts {len(set(texts.values()))}, "
             f"result-cache hits (cache_source_id) {sum(1 for r in records if r.get('cache_source_id'))}")
    L.append("")
    L.append("| run | wall-clock s | enrich calls | verify calls | group calls | memo calls | API cost USD |")
    L.append("|---|---|---|---|---|---|---|")
    for r in runs:
        roles = by.get(r["run"], {})
        cost = sum(v["cost_usd"] for v in roles.values())
        L.append(f"| {r['run']} | {r['wall_clock_s']:.2f} | " +
                 " | ".join(str(int(roles.get(k, {}).get('attempts', 0))) for k in ("enrich", "verify", "group", "memo")) +
                 f" | {cost:.6f} |")
    L.append("")
    L.append("### Per stage (cold run)\n")
    L.append("| stage | provider / exact model ID(s) served | effort | prompt / schema | batch size / workers | attempts | ok | failed | retries | fallbacks | "
             "reviews sent | uncached in | cache write | cache read | output | call-s summed | USD |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    cfg = runs[0]["config"]
    cold_total = 0.0
    for role in ("enrich", "verify", "group", "memo"):
        s = by["cold"].get(role)
        if not s:
            continue
        c = cfg[role]
        cold_total += s["cost_usd"]
        served = ", ".join(sorted({x["model"] for x in calls if x["pilot_run"] == "cold" and x["role"] == role}))
        L.append(f"| {role} | anthropic / {served} | {c['effort']} | {c['prompt_version']} / {c.get('schema_version', 'line format')} | {c.get('batch', '-')} / 1 | "
                 f"{int(s['attempts'])} | {int(s['succeeded'])} | {int(s['failed'])} | {int(s['retries'])} | "
                 f"{int(s['fallbacks'])} | {int(s['reviews_sent'])} | {int(s['uncached_input'])} | {int(s['cache_write'])} | "
                 f"{int(s['cache_read'])} | {int(s['output'])} | {s['call_seconds_summed']:.2f} | {s['cost_usd']:.6f} |")
    cold_wall = cold_run["wall_clock_s"]
    L.append("")
    L.append(f"- Cold API cost: **${cold_total:.6f}**; per 1,000 input rows: ${cold_total / 100 * 1000:.4f}; "
             f"per completed record: ${cold_total / max(1, completed):.6f}")
    L.append(f"- Cold end-to-end wall clock: {cold_wall:.2f} s (clock-measured; summed call durations are reported separately "
             f"and can exceed wall time when calls overlap). Throughput: {100 / cold_wall:.2f} rows/s end-to-end.")
    warm = next((r for r in runs if r["run"] == "warm"), None)
    if warm:
        wroles = by.get("warm", {})
        L.append(f"- Warm rerun (same saved result cache, unchanged settings): {warm['wall_clock_s']:.2f} s, "
                 f"new enrichment calls = {int(wroles.get('enrich', {}).get('attempts', 0))}, downstream calls = "
                 f"{int(sum(v['attempts'] for k, v in wroles.items() if k != 'enrich'))}, incremental cost "
                 f"${sum(v['cost_usd'] for v in wroles.values()):.6f}")
    L.append(f"- Local compute: {local[0]['usd_per_unit'] if local else 'unknown'} ({local[0]['notes'] if local else ''}); "
             "not included in API subtotals.")
    L.append("\nRaw usage per billing item: [usage.csv](usage.csv) · rates: [rates.csv](rates.csv) · "
             "calls: [pilot_calls.jsonl](pilot_calls.jsonl) · records: [pilot_records.jsonl](pilot_records.jsonl)\n")
    L.append("Formula: `item_cost = billed_units x price_per_unit` (per-1M prices divided by 1,000,000); items are "
             "mutually exclusive (uncached input, cache write, cache read, output); `total = sum(item_cost)`.\n")
    L.append("## Full-run projection (estimates, not measurements)\n")
    d = proj["pilot_derived"]
    L.append(f"Derived from the cold pilot: {d['reviews_per_request']:.1f} reviews/request, "
             f"{d['system_tokens_per_request']:.0f} system tokens/request, {d['uncached_input_tokens_per_review']:.1f} "
             f"uncached input tokens/review, {d['output_tokens_per_review']:.1f} output tokens/review, measured "
             f"invalid-retry rate {d['measured_rates']['invalid_retry_rate']:.4f}, fallback rate "
             f"{d['measured_rates']['fallback_rate']:.4f}, transient failure rate {d['measured_rates']['transient_failure_rate']:.4f}, "
             f"1-worker throughput {d['one_worker_reviews_per_second']:.2f} reviews/s.\n")
    L.append(f"Scope: {scen['full_rows']:,} rows -> {scen['nonempty_rows']:,} nonempty classifications + "
             f"{scen['empty_quarantines']} empty-text quarantines. Enrichment tier: **{scen['enrich_tier']}**; "
             f"budget ${scen['budget_usd']:.2f}; output cap {scen['output_token_cap_per_request']} tokens/request; "
             f"max workers {scen['max_workers']}; max fallback fraction {scen['max_fallback_fraction']}; "
             f"verification sample {scen['verify_sample_full_run']:,}.\n")
    L.append("| scenario | reuse | distinct sent | requests | retry rate | fallback rate | enrich | retry | fallback | verify | group | memo | total USD | budget | modeled realtime h |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for s in proj["scenarios"]:
        st = defaultdict(float)
        for x in s["lines"]:
            st[x["stage"]] += x["usd"] or 0
        flag = "**EXCEEDS BUDGET**" if s["exceeds_budget"] else "within"
        L.append(f"| {s['scenario']} | {s['reuse']} | {s['distinct_texts_sent']:,} | {s['enrich_requests']:,} | "
                 f"{s['assumed_retry_rate']} | {s['assumed_fallback_rate']} | {st['enrich']:.2f} | {st['enrich_retry']:.2f} | "
                 f"{st['enrich_fallback']:.2f} | {st['verify']:.2f} | {st['group']:.2f} | {st['memo']:.2f} | "
                 f"**{s['total_usd']:.2f}** | {flag} | {s['modeled_realtime_hours']} |")
    L.append("\nGroup and memo are fixed overhead counted once (memo doubled in the conservative case for a check-failure "
             "retry); they are never multiplied per review. Realtime hours are MODELED from 1-worker measured throughput x "
             "workers (linear; rate limits can make this slower). Message Batches turnaround is provider-controlled "
             "(most batches finish within 1 hour, max 24 hours) and is reported from the actual run, not modeled here.\n")
    cap = scen["output_token_cap_per_request"]
    max_out = max((c["output_tokens"] for c in calls if c["role"] == "enrich"), default=0)
    L.append(f"Output-token cap check: largest enrichment response in the pilot = {max_out} tokens vs cap {cap} "
             f"({'OK' if max_out < cap else '**AT/ABOVE CAP: raise the cap or shrink requests**'}).\n")
    actual = ROOT / "runs" / "full" / "full_run_summary.json"
    if actual.exists():
        a = json.loads(actual.read_text())
        base = next(s for s in proj["scenarios"] if s["scenario"] == "base" and s["reuse"] == "with exact-text reuse")
        L.append("## Estimate vs actual (full run, measured afterwards)\n")
        L.append(f"- Pilot-based base estimate (batch tier, with reuse): **${base['total_usd']:.2f}**; 10k refresh estimate: "
                 f"$40.17 enrichment (batch) + ~$0.26 fixed/verify; **actual: ${a['total_api_cost_usd']:.2f}** "
                 f"(recomputed from logged usage x rates; includes a realtime initial phase before the interruption, "
                 f"invalid-output retries, 122 fallback reviews and an 18-review repair pass).")
        L.append(f"- Actual statuses: {a['record_statuses']}; quarantine reasons: {a['quarantine_reasons']}.")
        L.append(f"- Actual wall clock by invocation (s): {a['wall_clock_s_by_invocation']}; spending limits (USD): "
                 f"{a['spending_limits']}. Source: [runs/full/full_run_summary.json](../runs/full/full_run_summary.json).\n")
    for extra in ("refresh_500", "refresh_10000"):
        p = HERE / f"{extra}.md"
        if p.exists():
            L.append(p.read_text())
    (HERE / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    json.dump(proj, open(HERE / "projection.json", "w"), indent=1, default=str)
    print("\n".join(L[:40]))
    print(f"... full report written to {HERE / 'report.md'}")


# ------------------------------------------------------------------ paid pilot
def pilot(args):
    if not args.i_understand_this_costs_money:
        sys.exit("Refusing: the pilot makes paid API calls. Re-run with --i-understand-this-costs-money.")
    sys.path.insert(0, str(ROOT))
    from pipeline import common, config, db, export
    run_dir = ROOT / "runs" / "pilot_100"
    if run_dir.exists():
        shutil.move(str(run_dir), str(run_dir) + f".old-{int(time.time())}")
    inp = ROOT / "data" / "cost_100.csv"
    runs = []
    for label in ("cold", "warm"):
        t0 = time.monotonic()
        subprocess.run([sys.executable, "-m", "pipeline", "run", "--input", str(inp), "--run-dir", str(run_dir),
                        "--budget", str(args.budget), "--verify-n", "20"], cwd=ROOT, check=True)
        wall = time.monotonic() - t0
        summary = json.loads((run_dir / "run_summary.json").read_text())
        runs.append({"run": label, "run_id": summary["run_id"], "wall_clock_s": round(wall, 3),
                     "pipeline_wall_clock_s": summary["wall_clock_s"], "stage_seconds": summary["stage_seconds"],
                     "workers": 1, "input_sha256": common.file_sha(inp), "result_cache": "empty" if label == "cold" else "warm",
                     "config": {"enrich": dict(config.ENRICH, batch="<=50 reviews"), "verify": dict(config.VERIFY, batch="<=50"),
                                "group": dict(config.GROUP, batch="<=10 issues"), "memo": dict(config.MEMO, batch="1")}})
    con = db.connect(run_dir / "state.db")
    run_label = {r["run_id"]: r["run"] for r in runs}
    calls = []
    for c in export.calls_rows(con):
        c["pilot_run"] = run_label.get(c["run_id"], "unknown")
        calls.append(c)
    common.write_jsonl(HERE / "pilot_calls.jsonl", calls)
    common.write_jsonl(HERE / "pilot_records.jsonl", export.build_records(con))
    common.write_json(HERE / "pilot_runs.json", runs)
    print("pilot saved; running offline replay ...")
    replay(args)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", nargs="?", default="replay", choices=("replay", "pilot"))
    p.add_argument("--rates", default=str(HERE / "rates.csv"))
    p.add_argument("--scenario", default=str(HERE / "scenario.json"))
    p.add_argument("--rate-multiplier", type=float, default=1.0, help="scale all API rates (e.g. 2 to test doubling)")
    p.add_argument("--budget", type=float, default=1.0, help="pilot spend cap (USD) per stage invocation")
    p.add_argument("--i-understand-this-costs-money", action="store_true")
    a = p.parse_args()
    replay(a) if a.command == "replay" else pilot(a)


if __name__ == "__main__":
    main()
