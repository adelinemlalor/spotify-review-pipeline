"""Offline orchestration tests with a mock model (no API key, no spend).
Run: .venv/bin/python -m tests.test_offline
"""
import json, shutil, tempfile
from pathlib import Path
from pipeline import config, enrich, export, group, prepare, rank, db
from tests.mock_client import MockClient

def main():
    tmp = Path(tempfile.mkdtemp(prefix="a5-mock-"))
    con, rep = prepare.prepare(config.DATA_DIR / "checkpoint_500.csv", tmp, "t1")
    assert rep["records"] == 500
    mc = MockClient(drop_idx_once=True)
    i1 = enrich.run_enrich(con, tmp, "t1", budget=1.0, max_requests=2, client=mc)
    assert i1["phase"] == "initial" and i1["requests"] == 2, i1
    before = json.loads(Path(i1["checkpoint"]).read_text())["completed_ids"]
    calls_before = mc.calls
    i2 = enrich.run_enrich(con, tmp, "t2", budget=1.0, workers=2, client=mc)
    assert i2["phase"] == "resume", i2
    after = json.loads(Path(i2["checkpoint"]).read_text())["completed_ids"]
    assert set(before) < set(after)
    # no resume call contains a pre-checkpoint ID
    for (ids,) in con.execute("SELECT review_ids FROM calls WHERE phase='resume'"):
        assert not set(json.loads(ids)) & set(before)
    # invalid-output retry happened for the dropped line
    assert con.execute("SELECT COUNT(*) FROM calls WHERE attempt_kind='invalid_output_retry'").fetchone()[0] == 1
    i3 = enrich.run_enrich(con, tmp, "t3", budget=1.0, client=mc)   # warm: nothing pending
    assert i3["requests"] == 0
    recs = export.build_records(con)
    assert len(recs) == 500 and all(r["status"] in ("completed", "quarantined") for r in recs)
    members = group.build_membership(recs)
    rows = [(i, r) for i, ids in members.items() for r in ids]
    rk = rank.ranking(recs, rows)
    assert all(r["priority_score"] == r["severity_sum"] for r in rk)
    # budget cap: a fresh run with a $0.0001 cap must stop before calling
    tmp2 = Path(tempfile.mkdtemp(prefix="a5-mock-"))
    con2, _ = prepare.prepare(config.DATA_DIR / "cost_100.csv", tmp2, "b1")
    i4 = enrich.run_enrich(con2, tmp2, "b1", budget=0.0001, client=MockClient())
    assert i4["stop_reason"].startswith("budget_cap"), i4
    print("OFFLINE TESTS PASSED", {"calls": mc.calls, "before": len(before), "after": len(after),
                                   "issues": len(rk)})
    shutil.rmtree(tmp); shutil.rmtree(tmp2)

if __name__ == "__main__":
    main()
