# Decision memo: next-quarter product priority

**Recommendation** - Put the next quarter into **billing**, starting with ISS-billing-premium_restrictions_free_tier (free-tier features restricted behind a paywall). Treat ISS-playback-crashes_or_wont_open as a smaller, parallel stability fix because of its severity.

## Why (evidence)
- **Top baseline rank.** ISS-billing-premium_restrictions_free_tier has a priority score of 29 [C004] (rank 1 [Q059]), from 10 complaints [C001] at mean severity 2.900000 [C003]. Representative reviews: 89ea2c30-db8b-459d-8ab7-bbcb7f92c774 and d146397f-4a94-4980-be00-ae9212eca3a7 (the latter describes being unable to pick a specific song and being limited in skips).
- **Coherent theme.** The issue is rated high coherence in the evidence pack. Reviews repeatedly describe skipping, song choice and shuffle being restricted, e.g. a78d831a-69f4-428a-9235-cfdd9775c509: "forcing you to pay premium for basic things like just listening to music."
- **Topic-level confirmation.** The billing topic has 10 complaint/cancellation records [Q042] and a severity sum of 29 [Q043], which is 0.200000 of all such records [Q045]. Of those, 1 has cancellation intent [Q046] (review 88439ec2-7c49-4c57-bedb-c5e098692aff). This is a secondary consideration.
- **Related pressure in usability.** ISS-usability-ads scores 16 [C012] from 7 complaints [C009]. It shares the free-versus-premium friction theme and could be scoped alongside billing (review 85383985-844d-4f9b-bcd9-d6016ac35f6b).
- **Severity secondary signal.** ISS-playback-crashes_or_wont_open has the highest severity mix: mean severity 4.000000 [C015] from 3 complaints [C013], with 3 severity 4-5 records [Q070] (reviews 66a29b3c-c14d-440e-b722-b23e0c99ae82, 55cc3abf-c295-4591-8c3a-78085cfdefaa). Its priority score is 12 [C016], rank 4 [Q068].

## Alternatives considered
- **Usability:** topic severity sum 30 [Q019] across 12 records [Q018] is larger than billing's 29 [Q043] at topic level. It is split across ISS-usability-ads (16 [C012]) and the low-coherence ISS-usability-navigation_and_controls (9 [C024]), so no single usability fix outranks the billing issue. It has 3 cancellation-intent records [Q022]. It is the closest alternative.
- **Playback:** 9 records [Q024], severity sum 29 [Q025], 2 cancellation-intent records [Q028]. ISS-playback-general is low coherence and scores 11 [C020]. The crash issue is severe but small, so it is a targeted fix rather than the headline.
- **Access:** ISS-access-login_failure scores 8 [C028] from 2 complaints [C025] at mean severity 4.000000 [C027]. Volume is too low to lead; monitor.
- **Support:** 0 records [Q048]; no evidence here.
- **Other areas:** ISS-other-general_criticism ranks 2 with a score of 18 [C008], but its reviews are non-specific (e.g. "Worst app", review 06a45bd5-3ed9-43af-b7f2-8b9487e2ffff), so it gives nothing to act on. Catalog (ISS-catalog-missing_or_removed_content score 5 [C032]) and downloads (ISS-downloads-offline_mode score 4 [C040]) rank lower.

## Risks and limitations
- Reviews are self-selected and historical; they do not represent all users. Cancellation language is expressed intent only, not observed churn.
- The sample is small: 50 complaint/cancellation records [Q006] out of 100 source rows [Q001]. Rank gaps between neighbouring issues are modest.
- Label quality: the verifier compared 20 records [Q089], with topic agreement 0.85 [Q090], intent 0.9 [Q091], severity 0.9 [Q092], and all three fields 0.85 [Q093]. Severity mean absolute error was 0.1 [Q094].
- Unresolved or quarantined records: 0 quarantined [Q003] and 0 other unresolved [Q005].
- Partial first and last months may skew the picture.
- There is no revenue or plan-tier data, so we cannot tell free from paying reviewers or size the business impact.

## Next steps
- Scope a review of free-tier restrictions (skip limits, song selection, shuffle-only behaviour) with product and monetization owners, including options that preserve basic control.
- Assess free-tier ad load together with the billing work as one free-versus-premium experience question.
- Assign engineering to triage the crash and launch-failure reports under ISS-playback-crashes_or_wont_open.
- Re-run the ranking on a larger and more recent review sample, with plan-tier data where available, before committing the full quarter.
