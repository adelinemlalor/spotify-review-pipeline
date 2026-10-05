"""Write the run manifest and a consolidated full-run summary (code only, no model calls).

    python -m pipeline.manifest --run-dir runs/full --grading grading

run_manifest.json ties together: source checksum, code version (git HEAD + sha256 of every
pipeline source file), prompt files and their hashes, model IDs and settings per role,
every invocation (run ID, command, phase, timing, budget, stop reason) and output hashes.
full_run_summary.json aggregates all invocations: statuses, attempts, failures, retries,
fallbacks, usage, cost, spend limits and resume evidence.
"""
import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path

from . import common, config, db


def sha_file(p):
    return common.file_sha(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="runs/full")
    ap.add_argument("--grading", default="grading")
    a = ap.parse_args()
    rd, gd = Path(a.run_dir), Path(a.grading)
    con = db.connect(rd / "state.db")
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        head = None
    invocations = [dict(r) for r in con.execute(
        "SELECT run_id, command, mode, started_at, ended_at, wall_s, budget_usd, workers, stop_reason FROM runs ORDER BY started_at")]
    for inv in invocations:
        inv["phase"] = (con.execute("SELECT phase FROM calls WHERE run_id=? AND role='enrich' LIMIT 1", (inv["run_id"],)).fetchone()
                        or [None])[0]
    roles = {"enrich": config.ENRICH, "enrich_fallback": config.FALLBACK, "verify": config.VERIFY,
             "group": config.GROUP, "memo": config.MEMO,
             "enrich_repair": dict(config.ENRICH, prompt_version="enrich-v1-repair1")}
    served = {r[0]: r[1] for r in con.execute("SELECT DISTINCT label_config, model FROM calls WHERE outcome='succeeded'")}
    manifest = {
        "run_dir": str(rd),
        "source": {"path": "data/spotify_reviews_18months.csv", "sha256": config.FULL_SHA256, "rows": 660622,
                   "provenance": "BwandoWando, 3.4 Million Spotify Google Store Reviews v2 (CC0), course extract 2022-05-17..2023-11-17"},
        "code_version": {"git_head_at_manifest_time": head,
                         "files_sha256": {str(p.relative_to(config.ROOT)): sha_file(p)
                                          for p in sorted((config.ROOT / "pipeline").glob("*.py"))}},
        "prompts_sha256": {p.name: sha_file(p) for p in sorted(config.PROMPT_DIR.glob("*.md"))},
        "roles": {k: {kk: v[kk] for kk in ("model", "effort", "prompt_version") if kk in v} |
                  {kk: v[kk] for kk in ("schema_version", "temperature", "max_reviews_per_request", "max_output_tokens",
                                        "max_fraction", "seed") if kk in v} for k, v in roles.items()},
        "label_configs_and_served_model_ids": served,
        "sdk": "anthropic 1.11.0 (Python 3.14)",
        "invocations": invocations,
        "outputs_sha256": {str(p): sha_file(p) for p in sorted(gd.iterdir()) if p.is_file()} |
                          {str(p): sha_file(p) for p in sorted((rd / "outputs").iterdir())
                           if p.is_file() and p.suffix in (".csv", ".json", ".md", ".jsonl")},
    }
    common.write_json(rd / "run_manifest.json", manifest)

    by = defaultdict(lambda: defaultdict(float))
    for r in con.execute("SELECT role, phase, attempt_kind, outcome, tier, COUNT(*), SUM(input_tokens), SUM(uncached_input_tokens), "
                         "SUM(cache_write_tokens), SUM(cache_read_tokens), SUM(output_tokens), SUM(cost_usd) FROM calls "
                         "GROUP BY 1,2,3,4,5"):
        key = f"{r[0]}|{r[1]}|{r[2]}|{r[3]}|{r[4]}"
        for name, v in zip(("attempts", "input_tokens", "uncached_input_tokens", "cache_write_tokens",
                            "cache_read_tokens", "output_tokens", "cost_usd"), r[5:]):
            by[key][name] = round(v or 0, 6)
    statuses = dict(con.execute("SELECT status, COUNT(*) FROM results GROUP BY 1").fetchall())
    reasons = dict(con.execute("SELECT reason, COUNT(*) FROM results WHERE status='quarantined' GROUP BY 1").fetchall())
    flags = defaultdict(int)
    for (f,) in con.execute("SELECT review_flags FROM results WHERE status='completed' AND cache_source_id IS NULL"):
        for x in json.loads(f or "[]"):
            flags[x.split(":")[0]] += 1
    before = json.loads((gd / "checkpoint_before.json").read_text())["completed_ids"]
    after = json.loads((gd / "checkpoint_after.json").read_text())["completed_ids"]
    summary = {
        "record_statuses": statuses, "quarantine_reasons": reasons,
        "distinct_texts": con.execute("SELECT COUNT(DISTINCT text_sha) FROM source WHERE is_empty=0").fetchone()[0],
        "cache_reuse_records": con.execute("SELECT COUNT(*) FROM results WHERE cache_source_id IS NOT NULL").fetchone()[0],
        "direct_record_flags": dict(flags),
        "calls_by_role_phase_attempt_outcome_tier": by,
        "total_api_cost_usd": round(sum(v["cost_usd"] for v in by.values()), 6),
        "cost_basis": "provider-reported usage per call x cost/rates.csv (standard or batch tier); not reconciled to an invoice",
        "spending_limits": {inv["run_id"]: inv["budget_usd"] for inv in invocations},
        "wall_clock_s_by_invocation": {inv["run_id"]: inv["wall_s"] for inv in invocations},
        "resume_evidence": {"checkpoint_before_completed": len(before), "checkpoint_after_completed": len(after),
                            "before_is_subset_of_after": set(before) <= set(after),
                            "resume_calls_containing_checkpointed_ids": sum(
                                1 for (ids,) in con.execute("SELECT review_ids FROM calls WHERE role='enrich' AND phase='resume'")
                                if set(json.loads(ids)) & set(before)),
                            "interrupt": "SIGINT at 16:31:23 local, see terminal_initial_phase.log"},
    }
    common.write_json(rd / "full_run_summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("record_statuses", "quarantine_reasons", "total_api_cost_usd",
                                               "resume_evidence", "direct_record_flags")}, indent=1))


if __name__ == "__main__":
    main()
