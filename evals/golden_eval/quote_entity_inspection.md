# Golden 50: evidence-quote and entity inspection

Exact-substring membership is checked in code (50/50). Whether each quote *supports* the label was inspected by reading every
excerpt quote. 41/50 predictions use the whole review as the quote (`*`), which supports the label by definition but is less precise.
This inspection was done with the AI coding assistant and is listed here so the author and the grader can re-check it.

## Excerpt quotes (9)

| review | predicted topic / intent | quote | supports label? |
|---|---|---|---|
| 947821dc | playback / complaint | "wen I play my song it o ly plays a little bit then it stops" | yes |
| 723f07de | playback / praise | "with some help from Sarah I was able to get the app working again" | yes |
| 46842184 | catalog / complaint | "lirik nya kdang gaada kek mana??" | yes |
| de48c99b | catalog / praise | "Spotify gave me recommendations for an AWESOME Playlist" | yes |
| 372d4e67 | usability / complaint | "Please ye ads ko thoda kumm Karo harr ek song ke baad ad" | yes |
| 16d640e9 | billing / complaint | "everything basic features is premium" | yes |
| 215463ae | playback / complaint | "I can't even open the app.. Just showing try again??" | yes |
| 46c0b49f | usability / complaint | "Listening to music in a normal volume and suddenly an add starts and my ears feel like they explode" | yes |
| 8c0546b0 | catalog / complaint | "Lyrics not getting loaded, 2-can't go back to or start song" | yes |

## Entities: predicted (code keyword matches) vs author's entities

Predicted entities are deterministic keyword matches, so none is absent from the text (no invented entities). Differences are
mostly vocabulary: the author often wrote topic-like words (`failures`, `recs`, `controls`). Some keyword matches are
technically present but not relevant (`update` from "Update:" as a heading).

| review | predicted, not in author's list | author's entities |
|---|---|---|
| 1fc8b08f | premium | ads, preimum |
| 947821dc | update | playback |
| 723f07de | crash, update | (none) |
| de48c99b | playlist, recommendations | recs |
| 47f1406d | update | playback |
| 3ddb3f4e | premium, shuffle, subscription, update | charges, controls, crashes, failures, premium-only controls |
| 16d640e9 | premium | premium-only features |
| 8c0546b0 | lyrics, update | crashes, downloads, failures, saved |
| dceb14e7 | update | content, failures |
| 5fba12ea | playlist | recs |
| ac4e860a | offline, subscription | offline mode |
| 99b93e31 | update | (none) |
