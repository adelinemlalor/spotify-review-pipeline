# Golden label corrections (disclosed)

All labels are the author's own hand labels. Versions kept for transparency:

1. `golden_50_human_labels_v1_as_first_labeled.csv`: as first labeled. Its evaluation is saved as
   `golden_eval/golden_report_v1_as_first_labeled.json`.
2. Author rechecked 5 rows that broke the shared severity rule (likely number-key slips) and changed:
   #13 intent unclear -> complaint; #31 severity 1 -> 2; #38 intent praise -> complaint (plus its alternatives).
   #32 and #33 were rechecked and deliberately kept as `request` with severity > 1. Saved as
   `golden_50_human_labels_v2_before_alt_conversion.csv`.
3. Mechanical conversion, with the author's approval: menu numbers typed into the "other acceptable" columns were mapped
   to label words using the same menus shown during labeling. A stray entry was removed. No primary labels changed:

- #6 alt_topic: removed 'Sentiment: -1' (not a topic)
- #12 alt_topic: 3 -> playback
- #12 alt_intent: 5 -> unclear
- #24 alt_intent: 5 -> unclear
- #25 alt_topic: 2 -> usability
- #25 alt_intent: 3 -> request
- #27 alt_intent: 2 -> complaint
- #28 alt_intent: 5 -> unclear
- #29 alt_topic: 3 -> playback
- #33 alt_topic: 3 -> playback
- #33 alt_intent: 2 -> complaint
- #38 alt_topic: 2 -> usability
- #38 alt_intent: 3 -> request
- #41 alt_topic: 5 -> catalog
- #41 alt_intent: 2 -> complaint
- #43 alt_topic: 5 -> catalog
- #43 alt_intent: 3 -> request
- #44 alt_topic: 5 -> catalog
- #47 alt_topic: 6 -> billing

No label was changed to match a model prediction; the changes in step 2 were made after seeing the v1 results, which is why the v1 report is kept.
