"""Model-call wrapper shared by all roles: one place for usage capture, bounded
retries with backoff + jitter, spend reservations and per-attempt call records.

Keys are read from the environment (.env via python-dotenv) and never logged.
"""
import os
import random
import threading
import time
import uuid

from . import common, config

TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


class BudgetExceeded(Exception):
    pass


class Ledger:
    """Single spend ledger shared by every worker.

    Before dispatch a worker reserves the worst-case cost of its call; admission
    stops when spent + reserved + next reservation would exceed the cap.
    """

    def __init__(self, budget_usd, already_spent=0.0):
        self.budget = budget_usd
        self.spent_this_run = 0.0
        self.prior = already_spent
        self.reserved = 0.0
        self.lock = threading.Lock()

    def reserve(self, amount):
        with self.lock:
            if self.spent_this_run + self.reserved + amount > self.budget:
                raise BudgetExceeded(
                    f"spent {self.spent_this_run:.4f} + reserved {self.reserved:.4f} + next {amount:.4f} > cap {self.budget:.2f}")
            self.reserved += amount
            return amount

    def settle(self, reserved, actual):
        with self.lock:
            self.reserved -= reserved
            self.spent_this_run += actual


def worst_case_cost(model, input_chars, max_tokens, system_tokens=6000, tier="standard"):
    """Upper bound: all input billed as a 5-minute cache write, output at the cap."""
    p = config.PRICES[model]
    est_in = system_tokens + input_chars / 2.5
    cost = est_in * p["cache_write_5m"] / 1e6 + max_tokens * p["output"] / 1e6
    return cost * (config.BATCH_DISCOUNT if tier == "batch" else 1.0)


def usage_dict(usage):
    uncached = getattr(usage, "input_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    return {"input_tokens": uncached + cw + cr, "uncached_input_tokens": uncached, "cache_write_tokens": cw,
            "cache_read_tokens": cr, "output_tokens": out}


def get_client():
    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key "
                         "(paid stages only; offline replay needs no key).")
    import anthropic
    # SDK retries disabled: we retry ourselves so that every attempt is logged.
    return anthropic.Anthropic(max_retries=0, timeout=180.0)


def build_params(cfg, system, user, max_tokens, cache_system=True):
    system_block = [{"type": "text", "text": system}]
    if cache_system:
        system_block[0]["cache_control"] = {"type": "ephemeral"}
    params = {"model": cfg["model"], "max_tokens": max_tokens, "system": system_block,
              "messages": [{"role": "user", "content": user}]}
    if cfg["model"].startswith("claude-haiku"):
        params["temperature"] = cfg.get("temperature", 0.0)  # thinking omitted = off
    elif "low" in cfg.get("effort", ""):
        params["output_config"] = {"effort": "low"}
        params["thinking"] = {"type": "between_tools"}  # Sonnet 5.5: thinking off
    elif "medium" in cfg.get("effort", ""):
        params["output_config"] = {"effort": "medium"}
        params["thinking"] = {"type": "adaptive"}
    return params


def call(client, cfg, system, user, max_tokens, review_ids, ledger, base_record, max_attempts=4,
         fault=None, cache_system=True):
    """Run one logical request with bounded retries. Returns (text|None, [attempt records]).

    `fault` lets tests inject a transient failure on the first attempt (planted error test).
    """
    import anthropic
    params = build_params(cfg, system, user, max_tokens, cache_system)
    records = []
    for attempt in range(1, max_attempts + 1):
        try:
            reserved = ledger.reserve(worst_case_cost(cfg["model"], len(system) + len(user), max_tokens))
        except BudgetExceeded:
            if attempt == 1:
                raise
            return None, records  # keep the logged failed attempts; items stay pending
        rec = dict(base_record, model=cfg["model"], prompt_version=cfg["prompt_version"], review_ids=review_ids,
                   tier="standard", attempt_kind=base_record.get("attempt_kind", "first") if attempt == 1 else "transient_retry",
                   started_at=common.now())
        t0 = time.monotonic()
        try:
            if fault and attempt == 1:
                import httpx2
                raise anthropic.APIConnectionError(
                    message="PLANTED transient failure (test)",
                    request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
            send = dict(params)
            if "temperature" in send:  # SDK 1.x dropped the kwarg; Haiku 4.5 still honours it via the body
                send["extra_body"] = {"temperature": send.pop("temperature")}
            msg = client.messages.create(**send)
        except anthropic.APIStatusError as e:
            rec.update(request_id=getattr(e, "request_id", None) or f"local-{uuid.uuid4()}", outcome="failed",
                       error=f"http_{e.status_code}: {str(e)[:200]}", stop_reason=None, **_zero_usage(), cost_usd=0.0)
            transient = e.status_code in TRANSIENT_STATUS
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
            # A timeout may still be billed by the provider; flagged for reconciliation.
            rec.update(request_id=f"local-{uuid.uuid4()}", outcome="failed",
                       error=f"{type(e).__name__} (charge unknown, reconcile with console): {str(e)[:150]}",
                       stop_reason=None, **_zero_usage(), cost_usd=0.0)
            transient = True
        else:
            u = usage_dict(msg.usage)
            cost = common.call_cost(cfg["model"], u)
            text = "".join(b.text for b in msg.content if b.type == "text")
            rec.update(request_id=msg.id, model=msg.model, outcome="succeeded", error=None, stop_reason=msg.stop_reason, **u,
                       cost_usd=cost, ended_at=common.now(), duration_s=round(time.monotonic() - t0, 3))
            ledger.settle(reserved, cost)
            records.append(rec)
            if msg.stop_reason == "refusal":
                rec["outcome"] = "failed"
                rec["error"] = "refusal"
                return None, records
            return text, records
        rec.update(ended_at=common.now(), duration_s=round(time.monotonic() - t0, 3))
        ledger.settle(reserved, 0.0)
        records.append(rec)
        if not transient or attempt == max_attempts:
            return None, records
        time.sleep(min(60, 2 ** attempt) * (0.5 + random.random()))  # exponential backoff + jitter
    return None, records


def _zero_usage():
    return {"input_tokens": 0, "uncached_input_tokens": 0, "cache_write_tokens": 0, "cache_read_tokens": 0,
            "output_tokens": 0}
