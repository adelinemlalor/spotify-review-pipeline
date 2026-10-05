"""Stage 2 - ENRICH (model judgment, code-controlled).

Code decides what to send (pending distinct texts only), bounds each request
(<= 50 reviews), validates every returned line, retries invalid output once,
routes a capped fraction to a stronger fallback model, quarantines what is still
invalid, and saves each finished request atomically. The model only reads
language and picks labels.
"""
import json
import re
import signal
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from . import common, config, db, llm

LINE_RE = re.compile(r"^\s*(\d+)\s*\|")


# ---------------------------------------------------------------- request building
def render_reviews(items):
    return "\n".join(f'<r i="{i}">{text}</r>' for i, _rid, text in items)


def chunk_requests(pending, max_reviews, max_chars):
    """pending: list of (review_id, text). Yields lists of (idx, review_id, text)."""
    batch, chars = [], 0
    for rid, text in pending:
        if batch and (len(batch) >= max_reviews or chars + len(text) > max_chars):
            yield batch
            batch, chars = [], 0
        batch.append((len(batch) + 1, rid, text))
        chars += len(text)
    if batch:
        yield batch


# ---------------------------------------------------------------- validation
def locate_quote(quote, text):
    """Return the exact source substring for the model's quote, or None."""
    q = quote.strip()
    if q == "*":
        return text if text.strip() else None
    for cand in (q, q.strip('"“”\''), q.rstrip(".")):
        if cand and cand in text:
            return cand
    # tolerate whitespace / case drift by mapping back to the original characters
    pattern = r"\s+".join(re.escape(tok) for tok in q.strip('"“”\'').split())
    if pattern:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def parse_lines(raw, items):
    """Validate the model text against the batch. Returns (valid{idx: payload}, errors{idx: msg})."""
    by_idx = {i: (rid, text) for i, rid, text in items}
    valid, errors, seen = {}, {}, set()
    for line in (raw or "").splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        idx = int(m.group(1))
        if idx not in by_idx:
            continue  # unknown local ID: ignored (never mapped to a review)
        if idx in seen:
            errors[idx] = "duplicate line for this idx"
            valid.pop(idx, None)
            continue
        seen.add(idx)
        parts = line.strip().split("|", 7)
        if len(parts) != 8:
            errors[idx] = f"expected 8 fields, got {len(parts)}"
            continue
        _, topic, sub, intent, sent, sev, nr, quote = [p.strip() if k < 7 else p for k, p in enumerate(parts)]
        text = by_idx[idx][1]
        problems = []
        if topic not in config.TOPICS:
            problems.append(f"topic '{topic}' not allowed")
        elif sub not in config.SUBTOPICS[topic]:
            problems.append(f"subtopic '{sub}' not allowed for {topic}")
        if intent not in config.INTENTS:
            problems.append(f"intent '{intent}' not allowed")
        try:
            sentiment = round(float(sent), 2)
            if not -1 <= sentiment <= 1:
                problems.append("sentiment out of range")
        except ValueError:
            problems.append("sentiment not a number")
        if sev not in {"1", "2", "3", "4", "5"}:
            problems.append("severity not 1-5")
        if nr not in {"0", "1"}:
            problems.append("needs_review not 0/1")
        exact = locate_quote(quote, text)
        if exact is None or not exact.strip():
            problems.append("quote is not an exact substring of the review")
        if problems:
            errors[idx] = "; ".join(problems)
            continue
        severity, flags, needs_review = int(sev), [], nr == "1"
        if intent in {"praise", "request", "unclear"} and severity != 1:
            # Contract rule owned by code: no reported problem => severity 1.
            flags.append(f"rule_fix:severity_{severity}_to_1_for_{intent}")
            severity, needs_review = 1, True
        if quote.strip() != "*" and exact != quote.strip():
            flags.append("quote_normalized_to_exact_source_span")
        valid[idx] = {"topic": topic, "subtopic": sub, "intent": intent, "sentiment": sentiment,
                      "severity": severity, "entities": common.extract_entities(text), "evidence_quote": exact,
                      "needs_review": needs_review, "review_flags": flags}
    for idx in by_idx:
        if idx not in valid and idx not in errors:
            errors[idx] = "no line returned for this idx"
    return valid, errors


# ---------------------------------------------------------------- one request (worker)
class Shared:
    def __init__(self, ledger, fallback_cap, faults):
        self.ledger = ledger
        self.fallback_cap = fallback_cap
        self.fallback_used = 0
        self.lock = threading.Lock()
        self.faults = dict(faults or {})

    def take_fallback(self, n):
        with self.lock:
            if self.fallback_used + n > self.fallback_cap:
                return False
            self.fallback_used += n
            return True

    def take_fault(self, name):
        with self.lock:
            return self.faults.pop(name, None)


def process_request(client, items, shared, base, system, retry_tmpl):
    """Returns {"outcomes": {review_id: (status, payload|reason, request_id, label_config, model, attempts)},
    "calls": [...], "budget_stop": bool}. Items whose request failed outright (after bounded transient
    retries) get no outcome and stay pending for a later resume."""
    lc = config.label_config(config.ENRICH)
    ids = [rid for _, rid, _ in items]
    fault = shared.take_fault("transient_first_call")
    text, calls = llm.call(client, config.ENRICH, system, render_reviews(items), config.ENRICH["max_output_tokens"],
                           ids, shared.ledger, dict(base, label_config=lc, attempt_kind="first"), fault=fault)
    if text is None:
        return {"outcomes": {}, "calls": calls, "budget_stop": False}
    if shared.take_fault("malformed_first_response"):
        # planted malformed output (test only): junk header line and the first review's line removed
        text = "PLANTED MALFORMED OUTPUT (test)\n" + "\n".join(text.splitlines()[1:])
        calls[-1]["error"] = "planted_malformed_output_test"
    return finish_batch_items(client, items, text, calls, shared, base, system, retry_tmpl)


# ---------------------------------------------------------------- persistence
def save_request(con, run_id, phase, result, dup_index):
    """One atomic transaction per finished request: calls + results + duplicate reuse + text cache."""
    ts = common.now()
    with db.tx(con):
        for c in result["calls"]:
            db.insert_call(con, dict(c, run_id=run_id, phase=phase))
        for rid, (status, payload, req_id, lc, model, attempts) in result["outcomes"].items():
            tsha = dup_index["sha_of"][rid]
            group = [rid] + [d for d in dup_index["by_sha"][tsha] if d != rid]
            for member in group:
                if con.execute("SELECT 1 FROM results WHERE review_id=? AND status IN ('completed','quarantined')",
                               (member,)).fetchone():
                    continue
                if status == "completed":
                    con.execute(
                        "INSERT OR REPLACE INTO results(review_id,status,topic,subtopic,intent,sentiment,severity,entities,"
                        "evidence_quote,needs_review,review_flags,label_config,cache_source_id,reason,attempts,request_id,"
                        "model,run_id,phase,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (member, "completed", payload["topic"], payload["subtopic"], payload["intent"],
                         payload["sentiment"], payload["severity"], json.dumps(payload["entities"]),
                         payload["evidence_quote"], int(payload["needs_review"]), json.dumps(payload["review_flags"]),
                         lc, None if member == rid else rid, None, attempts if member == rid else 0,
                         req_id if member == rid else None, model, run_id, phase, ts))
                else:
                    reason = payload if member == rid else f"{payload} (same exact text as {rid})"
                    con.execute(
                        "INSERT OR REPLACE INTO results(review_id,status,reason,label_config,attempts,run_id,phase,updated_at)"
                        " VALUES (?,?,?,?,?,?,?,?)", (member, "quarantined", reason, lc, attempts, run_id, phase, ts))
            if status == "completed":
                con.execute("INSERT OR REPLACE INTO text_cache VALUES (?,?,?,?)",
                            (tsha, lc, rid, json.dumps(payload, ensure_ascii=False)))


def quarantine_empty(con, run_id, phase):
    ts = common.now()
    with db.tx(con):
        con.execute(
            "INSERT OR IGNORE INTO results(review_id,status,reason,attempts,run_id,phase,updated_at) "
            "SELECT review_id,'quarantined','empty_review_text',0,?,?,? FROM source WHERE is_empty=1",
            (run_id, phase, ts))


def pending_work(con, limit_ids=None):
    """Distinct pending texts with their canonical (first-seen) review ID, plus cache hits."""
    rows = con.execute(
        "SELECT s.review_id, s.text_sha, s.review_text FROM source s LEFT JOIN results r USING(review_id) "
        "WHERE s.is_empty=0 AND (r.status IS NULL OR r.status NOT IN ('completed','quarantined')) "
        "ORDER BY s.row_idx").fetchall()
    by_sha, sha_of, canonical = defaultdict(list), {}, {}
    for rid, tsha, text in rows:
        by_sha[tsha].append(rid)
        sha_of[rid] = tsha
        canonical.setdefault(tsha, (rid, text))
    return {"by_sha": by_sha, "sha_of": sha_of, "canonical": canonical, "pending_rows": len(rows)}


def apply_text_cache(con, work, run_id, phase):
    """Reuse saved validated results for exact text under the same label_config (no model call)."""
    lcs = [config.label_config(config.ENRICH), config.label_config(config.FALLBACK)]
    hits, ts = 0, common.now()
    with db.tx(con):
        for tsha in list(work["canonical"]):
            row = None
            for lc in lcs:
                row = con.execute("SELECT source_review_id, payload, label_config FROM text_cache WHERE text_sha=? AND label_config=?",
                                  (tsha, lc)).fetchone()
                if row:
                    break
            if not row:
                continue
            src, payload, lc = row[0], json.loads(row[1]), row[2]
            for member in work["by_sha"][tsha]:
                con.execute(
                    "INSERT OR REPLACE INTO results(review_id,status,topic,subtopic,intent,sentiment,severity,entities,"
                    "evidence_quote,needs_review,review_flags,label_config,cache_source_id,attempts,model,run_id,phase,updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (member, "completed", payload["topic"], payload["subtopic"], payload["intent"], payload["sentiment"],
                     payload["severity"], json.dumps(payload["entities"]), payload["evidence_quote"],
                     int(payload["needs_review"]), json.dumps(payload["review_flags"]), lc,
                     None if member == src else src, 0, None, run_id, phase, ts))
                hits += 1
            del work["canonical"][tsha]
    return hits


def snapshot(con, run_dir, run_id, label):
    ids = [r[0] for r in con.execute("SELECT review_id FROM results WHERE status='completed' ORDER BY review_id")]
    path = Path(run_dir) / "checkpoints" / f"{label}_{run_id}.json"
    common.write_json(path, {"run_id": run_id, "label": label, "taken_at": common.now(), "completed_count": len(ids),
                             "completed_ids": ids})
    return path


# ---------------------------------------------------------------- realtime driver
def run_enrich(con, run_dir, run_id, budget, workers=1, max_requests=None, phase=None, faults=None, client=None):
    prior = con.execute("SELECT COUNT(*) FROM calls WHERE role='enrich' AND outcome='succeeded'").fetchone()[0]
    phase = phase or ("resume" if prior else "initial")
    quarantine_empty(con, run_id, phase)
    work = pending_work(con)
    hits = apply_text_cache(con, work, run_id, phase)
    pending = [(rid, text) for rid, text in work["canonical"].values()]
    distinct_total = con.execute("SELECT COUNT(DISTINCT text_sha) FROM source WHERE is_empty=0").fetchone()[0]
    fb_used = con.execute("SELECT COUNT(*) FROM results WHERE model=? AND cache_source_id IS NULL",
                          (config.FALLBACK["model"],)).fetchone()[0]
    fallback_cap = max(0, int(config.FALLBACK["max_fraction"] * distinct_total) - fb_used)
    requests = list(chunk_requests(pending, config.ENRICH["max_reviews_per_request"], config.ENRICH["max_chars_per_request"]))
    if max_requests is not None:
        requests = requests[:max_requests]
    print(f"[enrich] phase={phase} pending_rows={work['pending_rows']} cache_hits={hits} "
          f"distinct_to_send={len(pending)} requests_this_run={len(requests)} workers={workers} budget=${budget:.2f}")
    if not requests:
        return {"phase": phase, "cache_hits": hits, "requests": 0, "stop_reason": "nothing_pending"}

    client = client or llm.get_client()
    system = common.load_prompt("enrich_v1.md")
    retry_tmpl = common.load_prompt("enrich_retry_v1.md")
    ledger = llm.Ledger(budget)
    shared = Shared(ledger, fallback_cap, faults)
    base = {"role": "enrich", "run_id": run_id, "phase": phase}
    stop = threading.Event()
    stop_reason = "completed"

    def on_sigint(signum, frame):
        nonlocal stop_reason
        if stop.is_set():
            raise KeyboardInterrupt
        stop_reason = "interrupted_by_user"
        stop.set()
        print("\n[enrich] interrupt received: finishing in-flight requests, saving, then stopping "
              "(press Ctrl-C again to abort hard)")

    old = signal.signal(signal.SIGINT, on_sigint)
    done_req = done_ok = done_q = 0
    t0 = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            queue = iter(requests)
            inflight = {}

            def admit():
                while not stop.is_set() and len(inflight) < workers:
                    items = next(queue, None)
                    if items is None:
                        return
                    inflight[pool.submit(process_request, client, items, shared, base, system, retry_tmpl)] = items

            admit()
            while inflight:
                finished, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for fut in finished:
                    fut_items = inflight.pop(fut)
                    try:
                        result = fut.result()
                    except llm.BudgetExceeded as e:
                        stop_reason = f"budget_cap: {e}"
                        stop.set()
                        continue
                    save_request(con, run_id, phase, result, work)
                    if result.get("budget_stop"):
                        stop_reason = "budget_cap reached during invalid-output retry"
                        stop.set()
                    if not result["outcomes"] and any(c["outcome"] == "failed" for c in result["calls"]):
                        print(f"[enrich] request failed after bounded retries; {len(fut_items)} reviews stay pending")
                    done_req += 1
                    done_ok += sum(o[0] == "completed" for o in result["outcomes"].values())
                    done_q += sum(o[0] == "quarantined" for o in result["outcomes"].values())
                    if done_req % 10 == 0 or done_req == len(requests) or len(requests) <= 50:
                        el = time.monotonic() - t0
                        print(f"[enrich] {done_req}/{len(requests)} requests saved | distinct ok={done_ok} "
                              f"quarantined={done_q} | spent ${ledger.spent_this_run:.4f} | {el:.0f}s")
                admit()
    finally:
        signal.signal(signal.SIGINT, old)
    if stop_reason == "completed" and max_requests is not None and len(requests) < len(list(chunk_requests(
            pending, config.ENRICH["max_reviews_per_request"], config.ENRICH["max_chars_per_request"]))):
        stop_reason = f"max_requests={max_requests} reached"
    snap = snapshot(con, run_dir, run_id, "after_enrich")
    print(f"[enrich] stop_reason={stop_reason}; checkpoint saved to {snap}")
    return {"phase": phase, "cache_hits": hits, "requests": done_req, "distinct_completed": done_ok,
            "distinct_quarantined": done_q, "spent_usd": ledger.spent_this_run, "stop_reason": stop_reason,
            "fallback_used": shared.fallback_used, "fallback_cap": fallback_cap, "checkpoint": str(snap)}


# ---------------------------------------------------------------- Message Batches driver
def run_enrich_batch_api(con, run_dir, run_id, budget, chunk_size=2000, poll_s=30, phase=None, client=None,
                         max_chunks=None):
    """Asynchronous Message Batches (50% price). Same prompts, same validation, same saves.

    Batch IDs and their request manifests are persisted before waiting, so an
    interrupted run re-attaches to submitted batches instead of paying twice.
    """
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    prior = con.execute("SELECT COUNT(*) FROM calls WHERE role='enrich' AND outcome='succeeded'").fetchone()[0]
    phase = phase or ("resume" if prior else "initial")
    client = client or llm.get_client()
    system = common.load_prompt("enrich_v1.md")
    retry_tmpl = common.load_prompt("enrich_retry_v1.md")
    lc = config.label_config(config.ENRICH)
    ledger = llm.Ledger(budget)
    quarantine_empty(con, run_id, phase)

    def ingest(batch_row):
        manifest = json.loads(batch_row["manifest"])
        work = pending_work(con)
        distinct_total = con.execute("SELECT COUNT(DISTINCT text_sha) FROM source WHERE is_empty=0").fetchone()[0]
        fb_used = con.execute("SELECT COUNT(*) FROM results WHERE model=? AND cache_source_id IS NULL",
                              (config.FALLBACK["model"],)).fetchone()[0]
        shared = Shared(ledger, max(0, int(config.FALLBACK["max_fraction"] * distinct_total) - fb_used), {})
        base = {"role": "enrich", "run_id": run_id, "phase": batch_row["phase"]}
        info = client.messages.batches.retrieve(batch_row["batch_id"])
        n = 0
        for res in client.messages.batches.results(batch_row["batch_id"]):
            items = [tuple(x) for x in manifest[res.custom_id]]
            items = [it for it in items if it[1] in work["sha_of"]]  # skip anything already final
            if not items:
                continue
            items = [(k + 1, rid, t) for k, (_, rid, t) in enumerate(items)]
            ids = [rid for _, rid, _ in items]
            calls = []
            if res.result.type == "succeeded":
                msg = res.result.message
                u = llm.usage_dict(msg.usage)
                calls.append(dict(base, request_id=msg.id, model=msg.model, label_config=lc,
                                  prompt_version=config.ENRICH["prompt_version"], review_ids=ids, outcome="succeeded",
                                  error=None, stop_reason=msg.stop_reason, tier="batch", attempt_kind="first", **u,
                                  cost_usd=common.call_cost(config.ENRICH["model"], u, tier="batch"),
                                  started_at=batch_row["submitted_at"], ended_at=str(info.ended_at), duration_s=None,
                                  artifact=f"{batch_row['batch_id']}:{res.custom_id}"))
                text = "".join(b.text for b in msg.content if b.type == "text")
                # validate and handle invalid lines through the same realtime retry/fallback path
                result = finish_batch_items(client, items, text, calls, shared, base, system, retry_tmpl)
            else:
                calls.append(dict(base, request_id=f"{batch_row['batch_id']}:{res.custom_id}", model=config.ENRICH["model"],
                                  label_config=lc, prompt_version=config.ENRICH["prompt_version"], review_ids=ids,
                                  outcome="failed", error=f"batch_{res.result.type}", stop_reason=None, tier="batch",
                                  attempt_kind="first", input_tokens=0, uncached_input_tokens=0, cache_write_tokens=0,
                                  cache_read_tokens=0, output_tokens=0, cost_usd=0.0,
                                  started_at=batch_row["submitted_at"], ended_at=str(info.ended_at), duration_s=None))
                result = process_request(client, items, shared, dict(base, attempt_kind="batch_errored_rerun"), system,
                                         retry_tmpl)
                result["calls"] = calls + result["calls"]
            save_request(con, run_id, batch_row["phase"], result, work)
            n += 1
        with db.tx(con):
            con.execute("UPDATE provider_batches SET processed=1, status='ended' WHERE batch_id=?", (batch_row["batch_id"],))
        print(f"[batch] ingested {n} results from {batch_row['batch_id']}")

    # 1) re-attach to anything submitted earlier (e.g. before an interruption) but not yet ingested
    for row in con.execute("SELECT * FROM provider_batches WHERE processed=0").fetchall():
        print(f"[batch] re-attaching to {row['batch_id']} submitted at {row['submitted_at']} (no resubmission)")
        wait_for(client, row["batch_id"], poll_s)
        ingest(row)

    # 2) plan all pending work once, then keep as many chunks in flight as the spend cap allows
    work = pending_work(con)
    hits = apply_text_cache(con, work, run_id, phase)
    pending = [(rid, text) for rid, text in work["canonical"].values()]
    reqs = list(chunk_requests(pending, config.ENRICH["max_reviews_per_request"], config.ENRICH["max_chars_per_request"]))
    chunks = [reqs[i:i + chunk_size] for i in range(0, len(reqs), chunk_size)]
    if max_chunks is not None:
        chunks = chunks[:max_chunks]
    print(f"[batch] phase={phase} cache_hits={hits} pending distinct={len(pending)} requests={len(reqs)} "
          f"chunks this run={len(chunks)} (chunk size {chunk_size}) budget=${budget:.2f}")
    inflight, submitted, stop_reason = [], 0, "completed"
    while chunks or inflight:
        while chunks:
            chunk = chunks[0]
            manifest, api_reqs, reserve = {}, [], 0.0
            for k, items in enumerate(chunk):
                cid = f"r{k:05d}-{uuid.uuid4().hex[:8]}"
                manifest[cid] = items
                params = llm.build_params(config.ENRICH, system, render_reviews(items), config.ENRICH["max_output_tokens"])
                api_reqs.append(Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**params)))
                reserve += llm.worst_case_cost(config.ENRICH["model"], len(system) + sum(len(t) for _, _, t in items),
                                               config.ENRICH["max_output_tokens"], tier="batch")
            try:
                ledger.reserve(reserve)
            except llm.BudgetExceeded as e:
                if not inflight:
                    stop_reason = f"budget_cap: {e}"
                    chunks = []
                break  # wait for an in-flight batch to settle, then try again
            batch = client.messages.batches.create(requests=api_reqs)
            with db.tx(con):
                con.execute("INSERT INTO provider_batches VALUES (?,?,?,?,?,?,?,0)",
                            (batch.id, run_id, phase, common.now(), batch.processing_status, json.dumps(manifest), reserve))
            inflight.append(batch.id)
            submitted += 1
            chunks.pop(0)
            print(f"[batch] submitted {batch.id}: {len(chunk)} requests, reserved worst-case ${reserve:.2f} "
                  f"(spent ${ledger.spent_this_run:.2f}, reserved ${ledger.reserved:.2f})")
        if not inflight:
            break
        ended = None
        while ended is None:
            for bid in inflight:
                b = client.messages.batches.retrieve(bid)
                if b.processing_status == "ended":
                    ended = bid
                    break
            if ended is None:
                counts = [client.messages.batches.retrieve(b).request_counts for b in inflight]
                print(f"[batch] {len(inflight)} in flight; processing={sum(c.processing for c in counts)} "
                      f"succeeded={sum(c.succeeded for c in counts)} errored={sum(c.errored for c in counts)}")
                time.sleep(poll_s)
        row = con.execute("SELECT * FROM provider_batches WHERE batch_id=?", (ended,)).fetchone()
        ledger.settle(row["reserved_usd"], 0.0)  # release reservation before realtime retries reserve their own
        ingest(row)
        actual = con.execute("SELECT COALESCE(SUM(cost_usd),0) FROM calls WHERE artifact LIKE ?", (ended + ":%",)).fetchone()[0]
        ledger.settle(0.0, actual)
        inflight.remove(ended)
        print(f"[batch] {ended} settled: actual batch cost ${actual:.4f}; run spend ${ledger.spent_this_run:.4f}")
    snap = snapshot(con, run_dir, run_id, "after_enrich")
    print(f"[batch] stop_reason={stop_reason}; checkpoint {snap}")
    return {"phase": phase, "checkpoint": str(snap), "chunks_submitted": submitted, "stop_reason": stop_reason,
            "spent_usd": ledger.spent_this_run}


def finish_batch_items(client, items, text, calls, shared, base, system, retry_tmpl):
    """Validate a batch result; reuse the realtime retry/fallback/quarantine logic for invalid lines."""
    lc = config.label_config(config.ENRICH)
    valid, errors = parse_lines(text, items)
    outcomes = {items[i - 1][1]: ("completed", p, calls[-1]["request_id"], lc, config.ENRICH["model"], 1)
                for i, p in valid.items()}
    bad = [it for it in items if it[0] in errors]
    if bad:
        sub = [(k + 1, rid, t) for k, (_, rid, t) in enumerate(bad)]
        try:
            retry = process_request_retry_only(client, sub, {rid: errors[i] for i, rid, _ in bad}, shared, base,
                                               system, retry_tmpl)
        except llm.BudgetExceeded:
            return {"outcomes": outcomes, "calls": calls, "budget_stop": True}  # bad items stay pending
        outcomes.update(retry["outcomes"])
        calls = calls + retry["calls"]
    return {"outcomes": outcomes, "calls": calls, "budget_stop": False}


def process_request_retry_only(client, sub, errors_by_rid, shared, base, system, retry_tmpl):
    """Invalid-output retry (+ capped fallback, + quarantine) for items whose first answer failed validation."""
    lc = config.label_config(config.ENRICH)
    err_txt = "\n".join(f"- review {i}: {errors_by_rid[rid]}" for i, rid, _ in sub)
    user = retry_tmpl.format(errors=err_txt) + "\n" + render_reviews(sub)
    t2, recs2 = llm.call(client, config.ENRICH, system, user, config.ENRICH["max_output_tokens"],
                         [rid for _, rid, _ in sub], shared.ledger,
                         dict(base, label_config=lc, attempt_kind="invalid_output_retry"))
    outcomes, calls = {}, list(recs2)
    v2, e2 = parse_lines(t2, sub) if t2 is not None else ({}, {i: "retry request failed" for i, _, _ in sub})
    for k, payload in v2.items():
        payload["review_flags"].append("needed_invalid_output_retry")
        outcomes[sub[k - 1][1]] = ("completed", payload, recs2[-1]["request_id"], lc, config.ENRICH["model"], 2)
    bad = [(i, rid, t) for (i, rid, t) in sub if i in e2]
    if bad and shared.take_fallback(len(bad)):
        flc = config.label_config(config.FALLBACK)
        fsub = [(k + 1, rid, t) for k, (_, rid, t) in enumerate(bad)]
        t3, recs3 = llm.call(client, config.FALLBACK, system, render_reviews(fsub), config.FALLBACK["max_output_tokens"],
                             [rid for _, rid, _ in fsub], shared.ledger,
                             dict(base, label_config=flc, attempt_kind="fallback"))
        calls += recs3
        v3, e3 = parse_lines(t3, fsub) if t3 is not None else ({}, {i: "fallback failed" for i, _, _ in fsub})
        for k, payload in v3.items():
            payload["review_flags"].append("stronger_model_fallback")
            outcomes[fsub[k - 1][1]] = ("completed", payload, recs3[-1]["request_id"], flc, config.FALLBACK["model"], 3)
        bad = [(i, rid, t) for (i, rid, t) in fsub if i in e3]
    for _, rid, _ in bad:
        tried_fallback = any(c.get("attempt_kind") == "fallback" and rid in c["review_ids"] for c in calls)
        outcomes.setdefault(rid, ("quarantined", "invalid_model_output_after_retry: " + errors_by_rid.get(rid, "")[:200],
                                  None, lc, None, 3 if tried_fallback else 2))
    return {"outcomes": outcomes, "calls": calls}


def wait_for(client, batch_id, poll_s):
    while True:
        b = client.messages.batches.retrieve(batch_id)
        if b.processing_status == "ended":
            return b
        c = b.request_counts
        print(f"[batch] {batch_id} {b.processing_status}: processing={c.processing} succeeded={c.succeeded} "
              f"errored={c.errored}")
        time.sleep(poll_s)
