# Decision memo: next-quarter product priority

**Recommendation** - Put the next quarter into **billing**, specifically ISS-billing-premium_restrictions_free_tier (Basic features locked behind premium). Run a smaller, parallel reliability workstream on ISS-playback-crashes_or_wont_open and ISS-access-login_failure, where severity is highest.

## Why (evidence)

- **Top baseline rank.** ISS-billing-premium_restrictions_free_tier ranks first [Q060] with a priority score of 160941 [C004], from 55931 complaints [C001] at a mean severity of 2.877492 [C003]. (review e0465e24-c900-44e3-b80c-b0423ac1428f; review 95325c7e-14cf-4e69-bccb-6dc0ca8d67d7)
- **Clear, coherent theme.** The evidence pack rates this issue's coherence as high. Reviewers name locked controls such as queue, repeat and the back option: "Most of the basic features are now premium - queue, repeat, order of playlist and back option." (review d4d75528-8b6a-4b0a-8d97-64de27d293fb)
- **Secondary: cancellation intent.** This issue has 11080 cancellation-intent records [Q061]. That is the largest figure among the ranked issues, and it is expressed intent only. The billing topic as a whole has 11999 such records [Q046].
- **Secondary: severity mix.** Billing has 818 severity 4-5 records for this issue [Q062], so severity is moderate. The top-ranked issue is a volume problem more than a severity problem.
- **Runner-up is not actionable.** ISS-other-general_criticism ranks second [Q063] with a priority score of 156997 [C008]. Its mean severity is 2.000395 [C007] and it has 4 severity 4-5 records [Q065]. Quotes like "I hate this application" (review 9ae73a34-f3f2-4ec1-80eb-bb514a7a7082) give no specific defect to fix.

## Alternatives considered

- **Usability:** ISS-usability-ads ranks third [Q066] with a priority score of 81686 [C012], well below billing. It has 38 severity 4-5 records [Q068]. ISS-usability-shuffle_and_queue (rank 6 [Q075], score 27095 [C024]) has mixed coherence and overlaps with the premium-lock complaints.
- **Playback:** The topic has 44426 complaint/cancellation records [Q024] and a mean severity of 3.188696 [Q026]. Its top issue, ISS-playback-general, ranks fourth [Q069] with a score of 29856 [C016], but its coherence is low. ISS-playback-crashes_or_wont_open has 5153 severity 4-5 records [Q074] and a score of 28595 [C020] (review 7b639ca7-cf2b-4086-b3ec-699d210506aa). It ranks lower on baseline volume but is the best candidate for a reliability track.
- **Access:** ISS-access-login_failure ranks seventh [Q078] with a score of 26101 [C028]. It has the highest mean severity of the ranked issues at 3.849137 [C027] and 5751 severity 4-5 records [Q080]. It is a smaller but acute problem, so it is a candidate for a targeted fix.
- **Support:** The topic has 691 complaint/cancellation records [Q048], so it does not warrant a quarter of effort.

## Risks and limitations

- Reviews are self-selected and historical, so they do not represent all users or current behavior.
- Label quality is imperfect. On a sample of 1000 [Q090], verifier agreement was 0.835 on topic [Q091], 0.925 on intent [Q092], 0.855 on severity [Q093] and 0.69 on all three together [Q094]. The severity mean absolute error was 0.15 [Q095].
- 13 records were quarantined [Q003], all for empty text [Q004], and 0 were otherwise unresolved [Q005].
- The first and last months of the data may be partial.
- No revenue or plan-tier data was used, so the free-versus-paid mix of these reviewers is unknown.
- Cancellation language is expressed intent, not observed behavior.

## Next steps

- Review the premium-gating decisions behind ISS-billing-premium_restrictions_free_tier, starting with queue, repeat and back controls, and decide which to restore or message differently.
- Assign a small reliability team to ISS-playback-crashes_or_wont_open and ISS-access-login_failure, using the severity 4-5 reviews.
- Split ISS-playback-general and ISS-other-general_criticism into specific, actionable sub-issues before any investment.
- Re-check the labels on the billing records with a larger human-reviewed sample before committing to scope.
