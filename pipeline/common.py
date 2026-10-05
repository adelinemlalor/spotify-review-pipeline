"""Shared helpers: hashing (via the course-provided helper), IO, entities, cost arithmetic."""
import csv
import hashlib
import importlib.util
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import config

# Use the course-provided row_sha/profile so serialization matches the checker exactly.
_spec = importlib.util.spec_from_file_location("check_submission", config.DATA_DIR / "check_submission.py")
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)
row_sha = checker.row_sha
file_sha = checker.sha
csv_rows = checker.csv_rows
mean_string = checker.mean_string


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_json(path, value):
    """Atomic JSON write (temp file + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
    os.replace(tmp, path)


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    os.replace(tmp, path)


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_csv(path, header, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, path)


def load_prompt(name):
    return (config.PROMPT_DIR / name).read_text(encoding="utf-8")


# ---- Deterministic entity extraction --------------------------------------------
# Entities are explicit feature terms matched in the review text by code, so every
# entity is supported by the text by construction (no model-invented entities).
ENTITY_TERMS = {
    "ads": r"\bads?\b|\badvert\w*|\bcommercials?\b",
    "shuffle": r"\bshuffl\w*",
    "skip": r"\bskip\w*",
    "playlist": r"\bplay ?lists?\b",
    "queue": r"\bqueue\w*",
    "download": r"\bdownload\w*",
    "offline": r"\boffline\b",
    "lyrics": r"\blyric\w*",
    "podcast": r"\bpodcasts?\b",
    "audiobook": r"\baudio ?books?\b",
    "premium": r"\bpremium\b",
    "subscription": r"\bsubscri\w*",
    "price": r"\bprices?\b|\bpricing\b|\bexpensive\b",
    "login": r"\blog ?in\b|\blogin\w*|\bsign ?in\b|\bpassword\b",
    "account": r"\baccounts?\b",
    "bluetooth": r"\bbluetooth\b",
    "android auto": r"\bandroid auto\b",
    "car": r"\bcar\b",
    "widget": r"\bwidgets?\b",
    "lock screen": r"\block ?screen\b",
    "search": r"\bsearch\w*",
    "recommendations": r"\brecommend\w*",
    "dj": r"\bdj\b",
    "smart shuffle": r"\bsmart shuffle\b",
    "crash": r"\bcrash\w*",
    "update": r"\bupdat\w*",
    "wear os": r"\bwear ?os\b|\bsmart ?watch\b|\bwatch app\b",
    "chromecast": r"\bchrome ?cast\b|\bcast(?:ing)?\b",
    "family plan": r"\bfamily (?:plan|account|premium)\b",
    "student plan": r"\bstudent\b",
    "customer support": r"\bcustomer (?:service|support)\b|\bsupport team\b",
    "refund": r"\brefund\w*",
}
_ENTITY_RE = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in ENTITY_TERMS.items()]


def extract_entities(text):
    return [name for name, rx in _ENTITY_RE if rx.search(text)]


# ---- Cost arithmetic ---------------------------------------------------------------
def call_cost(model, usage, tier="standard", prices=None):
    """Cost of one call from mutually exclusive usage categories.

    usage: uncached_input_tokens, cache_write_tokens, cache_read_tokens, output_tokens.
    Each item = billed units x (USD per 1M / 1,000,000); batch tier applies the 50% discount.
    """
    p = (prices or config.PRICES)[model]
    mult = config.BATCH_DISCOUNT if tier == "batch" else 1.0
    items = {
        "uncached_input": usage.get("uncached_input_tokens", 0) * p["input"] / 1e6,
        "cache_write": usage.get("cache_write_tokens", 0) * p["cache_write_5m"] / 1e6,
        "cache_read": usage.get("cache_read_tokens", 0) * p["cache_read"] / 1e6,
        "output": usage.get("output_tokens", 0) * p["output"] / 1e6,
    }
    return sum(items.values()) * mult
