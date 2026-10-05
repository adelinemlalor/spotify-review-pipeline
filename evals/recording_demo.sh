#!/bin/bash
# Screen-recorded interruption/resume demo on 500 development reviews (PAID, about $0.08).
# The operator presses Ctrl-C once during the first run; the second run resumes.
cd "$(dirname "$0")/.." || exit 1
RUN=runs/recording_demo_500
rm -rf "$RUN"
py=.venv/bin/python
status() {
  sqlite3 "$RUN/state.db" "select '  completed records: '||count(*) from results where status='completed'; select '  enrichment calls so far: '||count(*) from calls where role='enrich';"
}
echo "=== RUN 1 (initial): 500 reviews, 1 worker ==="
echo ">>> Press Enter after a few requests are saved to INTERRUPT the run (sends SIGINT, the same signal as Ctrl-C)."
PYTHONUNBUFFERED=1 $py -m pipeline run --input data/checkpoint_500.csv --run-dir "$RUN" --stages prepare,enrich --workers 1 --budget 0.5 &
PID=$!
read -r _
if kill -0 "$PID" 2>/dev/null; then
  echo ">>> $(date '+%H:%M:%S') operator interrupt: sending SIGINT to pipeline process $PID"
  kill -INT "$PID"
fi
wait "$PID"
echo; echo "=== SAVED STATE AFTER INTERRUPTION ==="; status
BEFORE=$(ls -t "$RUN"/checkpoints/after_enrich_*.json | head -1); echo "  checkpoint: $BEFORE"
read -r -p "Press Enter to resume... " _
echo "=== RUN 2 (resume): only pending reviews are sent ==="
PYTHONUNBUFFERED=1 $py -m pipeline run --input data/checkpoint_500.csv --run-dir "$RUN" --stages prepare,enrich --workers 1 --budget 0.5
echo; echo "=== FINAL STATE ==="; status
AFTER=$(ls -t "$RUN"/checkpoints/after_enrich_*.json | head -1)
$py - "$RUN" "$BEFORE" "$AFTER" <<'PY'
import json, sqlite3, sys
run, b, a = sys.argv[1:]
before = set(json.load(open(b))["completed_ids"]); after = set(json.load(open(a))["completed_ids"])
con = sqlite3.connect(f"{run}/state.db")
rows = con.execute("select phase, review_ids from calls where role='enrich'").fetchall()
resent = sum(1 for ph, ids in rows if ph == "resume" and before & set(json.loads(ids)))
print(f"  completed before interruption: {len(before)}  after resume: {len(after)}  before ⊂ after: {before < after}")
print(f"  enrichment calls: initial={sum(p=='initial' for p,_ in rows)} resume={sum(p=='resume' for p,_ in rows)}; "
      f"resume calls containing already-completed IDs: {resent}")
PY
echo "=== DEMO COMPLETE ==="
