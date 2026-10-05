"""SQLite run state. One database per run directory.

Writes for one enrichment batch happen inside a single transaction, so an
interruption can never leave a half-saved batch; the main thread is the only
writer, so parallel workers cannot overwrite or double-count results.
"""
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS source (
    review_id TEXT PRIMARY KEY, row_idx INTEGER NOT NULL, row_sha TEXT NOT NULL, text_sha TEXT NOT NULL,
    review_text TEXT NOT NULL, review_rating TEXT, review_likes TEXT, app_version TEXT,
    review_timestamp TEXT, is_empty INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS source_text ON source(text_sha);
CREATE TABLE IF NOT EXISTS results (
    review_id TEXT PRIMARY KEY, status TEXT NOT NULL, topic TEXT, subtopic TEXT, intent TEXT,
    sentiment REAL, severity INTEGER, entities TEXT, evidence_quote TEXT, needs_review INTEGER,
    review_flags TEXT, label_config TEXT, cache_source_id TEXT, reason TEXT, attempts INTEGER,
    request_id TEXT, model TEXT, run_id TEXT, phase TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS results_status ON results(status);
CREATE TABLE IF NOT EXISTS text_cache (
    text_sha TEXT NOT NULL, label_config TEXT NOT NULL, source_review_id TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY (text_sha, label_config));
CREATE TABLE IF NOT EXISTS calls (
    request_id TEXT PRIMARY KEY, run_id TEXT, role TEXT, phase TEXT, attempt_kind TEXT, model TEXT,
    label_config TEXT, prompt_version TEXT, review_ids TEXT, outcome TEXT, error TEXT, stop_reason TEXT,
    tier TEXT, input_tokens INTEGER, uncached_input_tokens INTEGER, cache_write_tokens INTEGER,
    cache_read_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, started_at TEXT, ended_at TEXT,
    duration_s REAL, artifact TEXT);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, command TEXT, phase TEXT, started_at TEXT, ended_at TEXT, wall_s REAL,
    budget_usd REAL, workers INTEGER, mode TEXT, stop_reason TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS provider_batches (
    batch_id TEXT PRIMARY KEY, run_id TEXT, phase TEXT, submitted_at TEXT, status TEXT, manifest TEXT,
    reserved_usd REAL, processed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, at TEXT, kind TEXT, detail TEXT);
"""


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    return con


class tx:
    """BEGIN IMMEDIATE ... COMMIT, rolled back on any exception."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, exc_type, exc, tb):
        self.con.execute("COMMIT" if exc_type is None else "ROLLBACK")
        return False


def log_event(con, run_id, kind, detail, at):
    con.execute("INSERT INTO events(run_id, at, kind, detail) VALUES (?,?,?,?)",
                (run_id, at, kind, json.dumps(detail, ensure_ascii=False)))


def insert_call(con, c):
    cols = ["request_id", "run_id", "role", "phase", "attempt_kind", "model", "label_config", "prompt_version",
            "review_ids", "outcome", "error", "stop_reason", "tier", "input_tokens", "uncached_input_tokens",
            "cache_write_tokens", "cache_read_tokens", "output_tokens", "cost_usd", "started_at", "ended_at",
            "duration_s", "artifact"]
    vals = [json.dumps(c[k]) if k == "review_ids" else c.get(k) for k in cols]
    con.execute(f"INSERT OR REPLACE INTO calls({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)


def spent_usd(con):
    return con.execute("SELECT COALESCE(SUM(cost_usd),0) FROM calls").fetchone()[0]
