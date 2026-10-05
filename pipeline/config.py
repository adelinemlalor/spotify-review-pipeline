"""Central, versioned configuration for every pipeline role.

Changing any value that feeds a label_config (model, prompt version, schema
version, sampling settings) changes the cache key, so previously saved results
are NOT reused under the new configuration.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
FULL_CSV = DATA_DIR / "spotify_reviews_18months.csv"
FULL_SHA256 = "1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6"

FIELDS = ("review_id", "review_text", "review_rating", "review_likes", "app_version", "review_timestamp")
TOPICS = ("access", "usability", "playback", "downloads", "catalog", "billing", "support", "other")
INTENTS = ("complaint", "request", "praise", "cancellation", "unclear")
INTENT_PRECEDENCE = ("cancellation", "complaint", "request", "praise", "unclear")

# Fixed subtopics (our custom, richer label). The grading export only uses `topic`;
# the (topic, subtopic) pair is the candidate issue key used by the group stage.
SUBTOPICS = {
    "access": ["login_failure", "account_hacked_or_locked", "signup_or_verification", "logged_out", "general"],
    "usability": ["ads", "shuffle_and_queue", "ui_redesign", "navigation_and_controls",
                  "playlist_and_library_management", "notifications_and_widgets", "general"],
    "playback": ["crashes_or_wont_open", "stops_or_pauses", "skips_or_wrong_song", "connection_or_loading",
                 "audio_quality_or_volume", "device_bluetooth_car_cast", "performance_battery_storage", "general"],
    "downloads": ["download_failure", "downloads_lost", "offline_mode", "general"],
    "catalog": ["missing_or_removed_content", "search", "recommendations_and_discovery", "lyrics",
                "podcasts_audiobooks", "general"],
    "billing": ["price", "unauthorized_or_unexpected_charge", "premium_restrictions_free_tier",
                "subscription_or_payment_problem", "family_student_plan", "general"],
    "support": ["no_or_slow_response", "unhelpful_response", "general"],
    "other": ["general_criticism", "general_praise", "unrelated_or_unclear", "unspecified_bug", "politics_or_boycott"],
}

# ---- Model roles -----------------------------------------------------------------
# Haiku 4.5: no extended thinking (thinking param omitted = off), temperature 0.
ENRICH = {
    "role": "enrich",
    "provider": "anthropic",
    "model": "claude-haiku-4-5",
    "effort": "none (thinking off)",
    "prompt_version": "enrich-v1",
    "schema_version": "schema-v1",
    "temperature": 0.0,
    "max_reviews_per_request": 50,      # contract limit
    "max_chars_per_request": 14000,     # keeps long-review requests well inside the output cap
    "max_output_tokens": 2500,          # output-token cap per request (max observed in 10k run: 1,384)
}
# Capped stronger-model fallback for reviews that fail validation twice on Haiku.
FALLBACK = {
    "role": "enrich",
    "provider": "anthropic",
    "model": "claude-sonnet-5-5",
    "effort": "low (thinking between_tools = off)",
    "prompt_version": "enrich-v1",
    "schema_version": "schema-v1",
    "max_output_tokens": 2048,
    "max_fraction": 0.005,              # at most 0.5% of distinct texts may use the fallback
}
VERIFY = {
    "role": "verify",
    "provider": "anthropic",
    "model": "claude-sonnet-5-5",       # a different model from the enricher, for independence
    "effort": "low (thinking between_tools = off)",
    "prompt_version": "verify-v1",
    "max_reviews_per_request": 50,
    "max_output_tokens": 2048,
    "seed": "a5-verify-v1",
}
GROUP = {
    "role": "group",
    "provider": "anthropic",
    "model": "claude-haiku-4-5",
    "effort": "none (thinking off)",
    "prompt_version": "group-v1",
    "examples_per_issue": 12,
    "max_output_tokens": 4096,
}
MEMO = {
    "role": "memo",
    "provider": "anthropic",
    "model": "claude-sonnet-5-5",
    "effort": "medium (adaptive thinking)",
    "prompt_version": "memo-v1",
    "max_output_tokens": 8000,
}


def label_config(cfg=ENRICH):
    return f"{cfg['model']}+{cfg['prompt_version']}+{cfg['schema_version']}+t0"


# ---- Prices (USD per 1M tokens). Editable copy lives in cost/rates.csv. ----------------
# Source: https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-10-04)
PRICES = {
    "claude-haiku-4-5": {"input": 1.00, "cache_write_5m": 1.25, "cache_read": 0.10, "output": 5.00},
    "claude-sonnet-5-5": {"input": 2.00, "cache_write_5m": 2.50, "cache_read": 0.20, "output": 10.00},
}
BATCH_DISCOUNT = 0.5  # Message Batches API bills 50% of standard rates

# Default spend cap for a single invocation (USD); override with --budget.
DEFAULT_BUDGET_USD = 5.00
