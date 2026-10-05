# Decision memo: next-quarter product priority

**Recommendation** - Put the next quarter into **billing**, led by ISS-billing-premium_restrictions_free_tier ("Free tier features restricted, premium forced"), which ranks first on the baseline priority score. As a secondary workstream, investigate the high-severity playback and access issues (ISS-playback-crashes_or_wont_open, ISS-access-login_failure), which are smaller in volume but much more severe.

## Why (evidence)

- **Top baseline rank.** ISS-billing-premium_restrictions_free_tier has a priority score of 124 [C004], from 43 complaints [C001] at mean severity 2.883721 [C003]. It is rank 1 [Q059]. Representative reviews: (review 86adc9b6-be58-400c-9a08-aa082ff0535c), "They are literally forcing us to purchase Spotify premium." and (review 237e6174-4921-44df-828c-28f7b9d6196e).
- **Largest topic by severity sum.** The billing topic has 50 complaint/cancellation records [Q042] and a severity sum of 143 [Q043], the highest of any named topic area (playback is 139 [Q025], usability 131 [Q019]).
- **Cancellation intent (secondary).** 5 cancellation-intent records sit in this issue [Q060]. This is expressed intent in self-selected reviews, not observed churn. Severity 4-5 records are few (1 [Q061]), so the case rests on volume and consistent theme, not extreme severity.
- **Restrictions on the free tier recur.** Reviewers describe being unable to pick songs or skip, e.g. (review f9cf3b4a-c40e-4578-9f6f-358807450b0f) and (review 89ea2c30-db8b-459d-8ab7-bbcb7f92c774).
- **Severity signal for the secondary workstream.** ISS-playback-crashes_or_wont_open has mean severity 4.000000 [C019], with 8 severity 4-5 records [Q073]. Its priority score is 32 [C020]. See (review 55cc3abf-c295-4591-8c3a-78085cfdefaa).

## Alternatives considered

- **Playback:** The topic has 42 records [Q024] at mean severity 3.309524 [Q026], and 17 severity 4-5 records [Q029]. Its top issue, ISS-playback-general, scores 45 [C016], well below 124 [C004]. It is the best candidate for a targeted crash/stuck-loading fix alongside the main priority.
- **Access:** ISS-access-login_failure scores 27 [C024] from 7 complaints [C021], with mean severity 3.857143 [C023]. Volume is small (10 topic records [Q012]), but 9 are severity 4-5 [Q017]. It is a candidate for a quick fix, not a quarter-long priority.
- **Usability:** ISS-usability-ads scores 70 [C012] (33 complaints [C009]) at mean severity 2.121212 [C011]. It ranks 3 [Q065] and is related to the free-tier/premium theme, so it may be addressed in the same workstream. Severity 4-5 records in the topic: 0 [Q023].
- **Support:** 0 complaint/cancellation records [Q048], so there is no evidence for prioritising it.
- **Other:** ISS-other-general_criticism ranks 2 [Q062] with a score of 106 [C008], but it is vague (mean severity 2.000000 [C007]) and not actionable as a single product area. Its example reviews include (review 0d9c62d1-2b53-4887-8156-a28eeac86e82).

## Risks and limitations

- Reviews are self-selected and historical; they do not represent all users.
- Label quality: verifier agreement on a 50-record sample [Q089] was 0.9 for topic [Q090], 0.96 for intent [Q091], 0.86 for severity [Q092] and 0.78 for all three together [Q093]. Severity mean absolute error was 0.14 [Q094].
- Records: 500 source rows [Q001], 500 completed [Q002], 0 quarantined [Q003], 0 unresolved [Q005]. Only 238 are complaint or cancellation records [Q006].
- The first and last months of the data may be partial.
- There is no revenue or plan-tier data, so impact by customer segment cannot be assessed.
- Ranking differences between neighbouring issues may be sensitive to severity-label noise.

## Next steps

- Have product and design review the free-tier restrictions behind ISS-billing-premium_restrictions_free_tier (skip, song selection, queue limits) and decide which are intentional.
- Have engineering triage ISS-playback-crashes_or_wont_open and ISS-access-login_failure as a bounded stability track.
- Check the ads issue (ISS-usability-ads) together with the free-tier work for shared causes in user experience.
- Validate these findings against plan-tier and in-app data before committing to roadmap scope.
