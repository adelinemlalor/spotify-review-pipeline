# Shared labels, examples and output schema

The common labels are copied from `data/GRADING_CONTRACT.md` and are used unchanged in the grading export.
The model-facing wording, including all worked examples, is the versioned prompt
[`pipeline/prompts/enrich_v1.md`](../pipeline/prompts/enrich_v1.md).

## Topics (exact primary labels)

| topic | definition | our subtopics (custom, used as the issue key) |
|---|---|---|
| access | Login, signup, password or account access | login_failure, account_hacked_or_locked, signup_or_verification, logged_out, general |
| usability | Navigation, controls, layout, queue/playlist management, ad interruptions | ads, shuffle_and_queue, ui_redesign, navigation_and_controls, playlist_and_library_management, notifications_and_widgets, general |
| playback | Playback failure, crashes, lag, connection failures, audio quality, resource use | crashes_or_wont_open, stops_or_pauses, skips_or_wrong_song, connection_or_loading, audio_quality_or_volume, device_bluetooth_car_cast, performance_battery_storage, general |
| downloads | Downloading, saved music, offline listening, disappearing downloads | download_failure, downloads_lost, offline_mode, general |
| catalog | Missing songs/artists, search/discovery, recommendations, lyrics availability | missing_or_removed_content, search, recommendations_and_discovery, lyrics, podcasts_audiobooks, general |
| billing | Price, charges, subscriptions, paywalls, premium entitlement; explicitly premium-only controls | price, unauthorized_or_unexpected_charge, premium_restrictions_free_tier, subscription_or_payment_problem, family_student_plan, general |
| support | Contacting support and the support response | no_or_slow_response, unhelpful_response, general |
| other | General praise/criticism, unrelated content, no supported specific topic | general_criticism, general_praise, unrelated_or_unclear, unspecified_bug, politics_or_boycott |

Rules applied: highest supported severity wins, ties go to the first specific problem mentioned. For praise, the first
specific praised feature is used, and general praise is `other`. A paid-plan mention alone is not `billing`.
Free-tier restrictions such as forced shuffle and skip limits are explicitly premium-only controls, so they are
`billing/premium_restrictions_free_tier`. Too many ads is `usability/ads`.

## Intent (precedence cancellation > complaint > request > praise > unclear)

Bare boycott/political slogans are `unclear` unless they also contain a product complaint or an explicit personal
departure. Cancellation is *expressed intent*, not observed churn.

## Severity (shared scale)

| severity | meaning | how we applied it (examples) |
|---|---|---|
| 1 | no reported problem: praise, unclear, pure request | "Good", "pls add a sleep timer", "🔥🔥🔥" |
| 2 | dislike, generic criticism, annoyance, cosmetic | "Worst app ever. Uninstalling." (cancellation does not raise severity), "Too many ads", "new home screen is ugly", "Premium is too expensive" |
| 3 | degraded / restricted function, some use remains | "can't choose songs without premium, only shuffle", "music stops when screen turns off, have to reopen", "lyrics missing for most songs" |
| 4 | clearly blocked core task | "app crashes every time I open it", "can't login even after resetting password", "paid for premium but still on free plan" |
| 5 | explicit serious financial, privacy or data harm | "charged my card twice", "charged after I cancelled", "account hacked, playlists gone" |

Code-owned rule: if the model returns intent praise, request or unclear with severity other than 1, code sets the
severity to 1, sets `needs_review=true` and records `rule_fix:...` in `review_flags`.

## Output schema

### Model line format (enrichment, schema-v1)

`idx|topic|subtopic|intent|sentiment|severity|needs_review|quote`. Here `idx` is the 1-50 position inside the request.
Code maps it back to the original `review_id` and rejects unknown, duplicate or missing positions. `quote` is either `*`
(the whole review) or an exact excerpt.

### Validated record (`records.jsonl.gz`, one per source ID)

| field | type | source |
|---|---|---|
| review_id | str | original ID (code) |
| source_sha256 | str | contract row hash via the provided `row_sha` (code) |
| status | `completed` / `quarantined` | code |
| topic, intent | enum | model, validated by code |
| subtopic | enum (custom) | model, validated against the topic's list |
| sentiment | float -1..1 | model, range-checked |
| severity | int 1..5 | model, plus the code rule above |
| entities | list[str] | **code**: deterministic feature-term matches in the text (`pipeline/common.py`), so every entity is supported by the text |
| evidence_quote | str | model quote, checked to be an exact source substring (whitespace/case drift is mapped back to the exact source span and flagged) |
| needs_review | bool | model prediction (plus code flags) |
| review_flags | list[str] | code: retries, fallbacks, rule fixes, quote normalization |
| label_config | str | `model+prompt+schema+t0`, the exact cache key |
| cache_source_id | str (optional) | code: direct original with identical text and label_config |
| reason | str | quarantined rows only |
