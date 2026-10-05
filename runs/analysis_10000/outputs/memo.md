# Decision memo: next-quarter product priority

**Recommendation** - Make billing the priority area, led by ISS-billing-premium_restrictions_free_tier (free-tier features paywalled). Treat ISS-playback-crashes_or_wont_open as a secondary, targeted fix because of its severity.

## Why (evidence)

- **Billing is the top specific, actionable issue.** ISS-other-general_criticism ranks first at a priority score of 2444 [C004], but it is vague ("Bad app", review 13fce7e7-9483-452f-b14e-867ff49e2113) and has no severity 4-5 records [Q062]. ISS-billing-premium_restrictions_free_tier is second at 2250 [C008] ([Q063]), from 773 complaints [C005] at mean severity 2.910737 [C007].
- **Cancellation intent is concentrated in billing (secondary consideration).** ISS-billing-premium_restrictions_free_tier has 146 cancellation-intent records [Q064], compared with 67 for the general-criticism issue [Q061]. At topic level, billing has 157 cancellation-intent records [Q046] against 79 for usability [Q022] and 42 for playback [Q028]. Example: "Uninstalling the app because the basic features are removed for non premium users" (review f36c8b32-1f3f-491c-bbc3-6b0f2222fca2); also review 60d716c1-9e38-4609-acf7-34a67d54e806. This is expressed intent only.
- **Billing is the largest topic with concrete content.** It has 923 complaint/cancellation records [Q042] and a severity sum of 2633 [Q043], the highest of any topic. Only the vague "other" topic has more records [Q054].
- **Crashes are the severity hotspot.** ISS-playback-crashes_or_wont_open has a priority score of 466 [C020], mean severity 3.698413 [C019] and 89 severity 4-5 records [Q074]. Example: "It always crashing down; unable to play and just stop working everytime I use it" (review 8cf70f3f-cbe6-4fd1-b97b-e160950e16be).

## Alternatives considered

- **Usability:** ISS-usability-ads scores 1299 [C012] with 607 complaints [C009], but its mean severity is 2.140033 [C011] and it has no severity 4-5 records [Q068]. It is also tied to the free-tier model, so it is best addressed alongside the billing work. ISS-usability-shuffle_and_queue scores 427 [C024]; ISS-usability-ui_redesign scores 332 [C040].
- **Playback:** Its topic severity sum is 2363 [Q025] with 196 severity 4-5 records [Q029]. The largest individual issue, ISS-playback-general, scores 627 [C016] and its evidence is mixed (e.g. review 46bc9fb5-ab72-4541-b30c-b1e2eb58377e, "not login problem bro"). ISS-playback-stops_or_pauses scores 357 [C036] and ISS-playback-skips_or_wrong_song 377 [C028].
- **Access:** ISS-access-login_failure has the highest mean severity at 3.864583 [C031] and 83 severity 4-5 records [Q083], but only 96 complaints [C029] and a score of 371 [C032]. Access is 133 records at topic level [Q012]. It is severe but narrow.
- **Support:** Only 12 records [Q048], so it does not warrant a quarter of effort.

## Risks and limitations

- Reviews are self-selected and historical; they do not represent all users, and cancellation language is stated intent, not observed behavior.
- Label quality is moderate. Verifier agreement on a 200-record sample [Q090] was 0.865 for topic [Q091], 0.9 for intent [Q092], 0.865 for severity [Q093] and 0.73 for all three together [Q094]. Severity mean absolute error was 0.145 [Q095].
- Records quarantined: 0 [Q003]; other unresolved: 0 [Q005]. All 10000 source rows were completed [Q002].
- The largest issue (ISS-other-general_criticism) is vague and gives little to act on, and the "other" topic holds 1256 records [Q054].
- The first and last months of the data may be partial, and there is no revenue or plan-tier data, so the free versus paying split cannot be assessed.

## Next steps

- Have product and pricing review which free-tier restrictions drive ISS-billing-premium_restrictions_free_tier, using the quoted reviews as starting points.
- Assign engineering to a root-cause investigation of ISS-playback-crashes_or_wont_open, given its severity.
- Review the ads experience (ISS-usability-ads) together with the free-tier work.
- Re-check the labels on the billing and general-criticism issues with a larger verifier sample, and obtain plan-tier data to confirm who is affected.
