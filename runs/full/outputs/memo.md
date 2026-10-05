# Decision memo: next-quarter product priority

**Recommendation** - Put next quarter's effort into billing, specifically ISS-billing-premium_restrictions_free_tier (basic features locked behind premium). It ranks first on the baseline priority score [C004]. As a secondary step, scope a fix for ISS-playback-crashes_or_wont_open and ISS-access-login_failure, which are the most severe issues.

## Why (evidence)

- **Top baseline rank.** ISS-billing-premium_restrictions_free_tier has a priority score of 160920 [C004], from 55924 complaints [C001] at a mean severity of 2.877477 [C003]. It is rank 1 [Q060]. Representative review: (review d4d75528-8b6a-4b0a-8d97-64de27d293fb), which names queue, repeat, playlist order and back as now premium.
- **Clear lead over the nearest coherent issue.** ISS-usability-ads scores 81682 [C012]. The runner-up, ISS-other-general_criticism, scores 156997 [C008], but it is a catch-all of non-specific dislike (e.g. review 9ae73a34-f3f2-4ec1-80eb-bb514a7a7082) and is hard to act on.
- **Secondary: cancellation intent.** The billing topic has 11998 cancellation-intent records [Q046], the most of any topic. For this issue alone it is 11079 [Q061]. This is expressed intent in public reviews, not observed behavior.
- **Secondary: severity mix.** The issue has 818 records at severity 4-5 [Q062]. That is far fewer than the crash and login issues, so severity does not drive this pick. Volume does. A second example: (review 6e67481f-6b1c-4154-b771-0719226b1fb8).

## Alternatives considered

- **Playback:** the topic has 44422 complaint/cancellation records [Q024] at mean severity 3.188690 [Q026]. Its best single issue, ISS-playback-general, scores 29856 [C016] and is labeled low coherence. ISS-playback-crashes_or_wont_open scores 28595 [C020] but has 5153 severity 4-5 records [Q074] (review 7b639ca7-cf2b-4086-b3ec-699d210506aa). That makes it the best candidate for a targeted reliability fix.
- **Access:** ISS-access-login_failure scores 26101 [C028], rank 7 [Q078]. It has the highest mean severity [C027] and 5751 severity 4-5 records [Q080], but only 6781 complaints [C025].
- **Usability:** ISS-usability-ads scores 81682 [C012] and ISS-usability-shuffle_and_queue scores 27092 [C024]. Both have lower mean severity [C011][C023] than billing. Part of the shuffle/queue complaint is plausibly the same premium gating (review dcef2a77-b81d-4b30-a235-de5162ce9e06), and its coherence is mixed.
- **Support:** the topic has 691 complaint/cancellation records [Q048], too small to prioritize now.
- **Other / general criticism:** ISS-other-general_criticism is rank 2 [Q063] but has only 4 severity 4-5 records [Q065] and no clear fix.

## Risks and limitations

- The reviews are self-selected, public and historical. They do not represent all users and do not show current behavior.
- Labels come from a model. A verifier compared 1000 records [Q090]. Agreement was 0.835 on topic [Q091], 0.925 on intent [Q092], 0.855 on severity [Q093] and 0.69 on all three together [Q094]. Severity mean absolute error was 0.15 [Q095].
- 31 records were quarantined [Q003]: 13 with empty text [Q004] and 18 otherwise unresolved [Q005]. This is small relative to 660591 completed records [Q002].
- The first and last months of the data may be partial.
- There is no revenue or plan-tier data. Free-tier restriction complaints cannot be tied to plan type or business impact from this evidence.
- Billing and usability overlap (ads and gating both concern the free tier), so category boundaries are imperfect.

## Next steps

- Have product and design review which gated features (queue, repeat, previous track, seek) drive ISS-billing-premium_restrictions_free_tier, and weigh the options for them.
- Join the review data to plan-tier and experiment data to check the free-tier signal before committing scope.
- Open a parallel engineering investigation into ISS-playback-crashes_or_wont_open and ISS-access-login_failure, given their severity mix.
- Manually audit a sample of ISS-other-general_criticism and ISS-playback-general, whose labels are catch-all or low coherence, before using them in planning.
