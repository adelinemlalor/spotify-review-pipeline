"""Interactive terminal helper for hand-labeling the golden 50 (no model calls).

    .venv/bin/python evals/label_golden.py

Shows one review at a time with the shared definitions, saves after every review,
and resumes where you stopped. Press Enter on a prompt to keep the current value.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "evals" / "golden_50_human_labels.csv"
TOPICS = ["access", "usability", "playback", "downloads", "catalog", "billing", "support", "other"]
INTENTS = ["cancellation", "complaint", "request", "praise", "unclear"]
HELP = """
TOPIC  1 access (login/account) 2 usability (controls/navigation/layout/ads) 3 playback (failures/crashes/lag/audio)
       4 downloads (offline/saved) 5 catalog (content/search/recs/lyrics) 6 billing (price/charges/premium-only controls)
       7 support (contacting support) 8 other (general praise/criticism, unrelated)
INTENT (first that applies) 1 cancellation 2 complaint 3 request 4 praise 5 unclear
SEVERITY 1 no problem/praise/unclear/pure request  2 annoyance/generic criticism  3 degraded, workaround remains
         4 core task blocked  5 explicit serious financial/privacy/data harm
SENTIMENT -1.0 .. 1.0   QUOTE: exact text copied from the review (Enter = whole review)
"""


def ask(prompt, current, options=None, cast=str):
    while True:
        shown = f" [{current}]" if current else ""
        raw = input(f"{prompt}{shown}: ").strip()
        if not raw:
            if current:
                return current
            continue
        if options and raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if options and raw not in options:
            print("  choose a number or one of:", ", ".join(options))
            continue
        try:
            cast(raw)
            return raw
        except ValueError:
            print("  invalid value")


def main():
    rows = list(csv.DictReader(open(PATH, encoding="utf-8", newline="")))
    cols = list(rows[0].keys())

    def save():
        tmp = PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        tmp.replace(PATH)

    if len(sys.argv) > 1 and "," in sys.argv[1]:
        order = [int(x) - 1 for x in sys.argv[1].split(",")]  # recheck only these review numbers
    else:
        start = int(sys.argv[1]) - 1 if len(sys.argv) > 1 else next(
            (i for i, r in enumerate(rows) if not (r["topic"] and r["intent"] and r["severity"])), 0)
        order = range(start, len(rows))
    print(HELP)
    for i in order:
        r = rows[i]
        print("=" * 100)
        print(f"#{i + 1}/50  id={r['review_id']}  (stars hidden on purpose: label the text)\n")
        print(r["review_text"], "\n")
        r["topic"] = ask("topic 1-8", r["topic"], TOPICS)
        r["intent"] = ask("intent 1-5", r["intent"], INTENTS)
        r["severity"] = ask("severity 1-5", r["severity"], ["1", "2", "3", "4", "5"])
        r["sentiment"] = ask("sentiment -1..1", r["sentiment"], cast=float)
        q = input(f"evidence quote [{'whole review' if not r['evidence_quote'] else r['evidence_quote']}]: ").strip()
        if q:
            if q not in r["review_text"]:
                print("  ! not an exact substring; keeping whole review")
                q = r["review_text"]
            r["evidence_quote"] = q
        elif not r["evidence_quote"]:
            r["evidence_quote"] = r["review_text"]
        r["entities"] = input(f"entities, ';' separated [{r['entities']}]: ").strip() or r["entities"]
        r["needs_review"] = ask("needs_review (true/false)", r["needs_review"] or "false", ["true", "false"])
        r["ambiguous"] = ask("ambiguous (yes/no)", r["ambiguous"] or "no", ["yes", "no"])
        if r["ambiguous"] == "yes":
            r["alt_topic"] = input("  other acceptable topics, '|' separated (optional): ").strip() or r["alt_topic"]
            r["alt_intent"] = input("  other acceptable intents (optional): ").strip() or r["alt_intent"]
            r["alt_severity"] = input("  other acceptable severities (optional): ").strip() or r["alt_severity"]
        r["notes"] = input(f"notes [{r['notes']}]: ").strip() or r["notes"]
        save()
    print("Done. Saved to", PATH)


if __name__ == "__main__":
    main()
