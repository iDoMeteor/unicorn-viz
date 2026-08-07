# Auto VJ Recommender — Accuracy Tracking Spec

Status: Tier 1 implemented (auto-vj-01 1.0.0-rc.14); Tier 2 implemented
  (2026-08-07, dj-mixer-01 0.158.0 / auto-vj-01 1.0.0-rc.23 / training-kit-01
  0.10.0) -- see docs/adr/vj-system.md § "Tier 2: Genre-Tag Ground-Truth
  Accuracy Tracking" for the full record. The live-feedback direction in
  question 4 below remains its own future design pass, not part of this
  implementation.
Owner: unicorn-viz maintainers
Last updated: 2026-08-07

## Problem

There is no ground-truth "this track is actually `deep_house`" label anywhere
in the training corpus today. Every weight/sigma change this session (the
sigma-floor revert, the `centroid_fit` raise, the `breaks`/`rap`/`synthwave`
tightening — see `docs/adr/vj-system.md` and
`drop-ins/auto-vj-01/docs/weights-and-thresholds.md`) was validated against
one specific live session's known BPM range and a hand-computed cosine
similarity, not against a repeatable accuracy measurement. That doesn't
scale: the next tuning question ("which weight is actually pulling its
weight?") can't be answered from a single anecdote.

Two tiers are proposed, buildable independently.

## Tier 1 — signal activity (implemented, 2026-08-06)

**Status: shipped in `auto-vj-01` 1.0.0-rc.14.** A diagnostic proxy for "is
this term actually discriminating between candidates, or just adding noise
to every score by a constant?" Per eval cycle, for each term (`tempo_fit`,
`centroid_fit`, `band_fit`, …), `_update_profile_recommendation()` computes
the **spread** of that term's raw (pre-weight) value across all scored
candidates (`max - min`) and logs it as `term_spread` on the existing
`profile_recommendation` decision-log event. A term with near-zero spread
across candidates this cycle is contributing a constant offset to every
score, not helping distinguish psytrance from deep_house *this cycle*,
regardless of its weight.

One correction from the original proposal: `lock_rate`/`mean_conf`/
`mean_dconf` are computed once per cycle from the sample window, not per
candidate — every candidate gets the identical value, so their spread is
*structurally* always `0`. That's "not a genre-fit term", not "this weight
does nothing"; `session_scorecard.py` excludes them from activity analysis
rather than flagging them as dead.

`session_scorecard.py` rolls this up into a "Signal Activity" section: per
term, what fraction of a session's eval cycles cleared a `0.05` spread
threshold. Over many sessions this becomes a real signal for
"`kick_regularity_fit` has near-zero spread in 90% of cycles across the
last 10 sessions — its weight is currently doing nothing" without needing
to know which candidate was *correct*.

This did not require the mixer's genre tags or any owner curation — see
`drop-ins/auto-vj-01/docs/weights-and-thresholds.md`'s Changelog entry **2**
and `docs/adr/vj-system.md` § "Per-Profile Centroid Sigma + Accuracy
Tracking Tier 1" for the full implementation record.

## Tier 2 — tag-based genre as ground truth (needs curated library)

**Status: implemented, 2026-08-07.** See docs/adr/vj-system.md § "Tier 2:
Genre-Tag Ground-Truth Accuracy Tracking" for the full record. Summary
below is the original proposal; kept as-is for the design rationale.

Per the owner's plan: `drop-ins/dj-mixer-01/tags.py` already extracts a
`genre` field per track (`TAG_FIELDS`, mapped from the ID3 `GENRE` frame,
`library.py` `_FACETS`). Once the training library and playlists are kept
well-tagged, that field becomes a real, authoritative ground-truth label —
not a heuristic, not a proxy. The owner has said they intend to keep the
training library managed this way going forward.

**What this unlocks once available:**

- True accuracy, not just discrimination: for each recommender eval cycle
  where the current track has a genre tag, record `(recommended_key,
  tag_genre, hit/miss)`. Rolled up per session and across sessions, this is
  the first real accuracy number this system will have ever had.
- Per-weight sensitivity analysis becomes possible in principle (does
  raising `centroid_fit` move hit-rate up or down across a tagged corpus) —
  a proper offline fit, not a hand-picked adversarial test case like this
  session's `test_recommender_prefers_deep_house_over_psytrance_at_120_bpm`.
- A natural place to *validate* the sigma-tightening judgment calls made
  this session (breaks/rap/synthwave) instead of leaving them as an
  ad hoc ratio comparison against other profiles' spans.

**Open design questions — answered by the owner, 2026-08-06:**

1. **Genre-tag → profile-key mapping — proceed as spec'd, plus a fuzzy
   fallback.** ID3 `GENRE` strings are free text ("Progressive House",
   "Psy-Trance", "UK Garage / 2-Step") and won't map 1:1 onto the 22
   `PROFILES` keys. The owner confirmed the training library will be kept
   accurately and completely tagged, so tag *quality* isn't the risk — the
   mapping table is. Owner's addition: the library carries real house
   sub-genres with no dedicated profile (tropical house, afro house, and
   similar), and these should not fall into "unmapped" just because they
   don't match an exact/alias entry. Proposed two-pass lookup:
   - **Pass 1 — exact/alias match** against a curated table (e.g.
     "Deep House" → `deep_house`, "Psy-Trance"/"Psytrance" → `psytrance`,
     "UK Garage"/"2-Step" → `uk_garage`). Handles every tag that has a real
     dedicated profile.
   - **Pass 2 — keyword fallback.** A tag that misses pass 1 gets matched
     on its last/most-generic word against a small keyword→profile table
     (e.g. anything ending in "house" with no more specific match →
     `house`; same idea for "techno" → closest techno profile or
     `electronic`). This is what turns "Tropical House" into `house`
     instead of unmapped.
   - **Unmapped bucket** only if neither pass hits — explicit and visible,
     never a silent guess.
   **Built 2026-08-07** as `_GENRE_ALIAS_MAP`/`_GENRE_KEYWORD_MAP` in
   `package_training_set.py` -- see the ADR entry for the exact table and
   the "techno → electronic" judgment call this proposal left open.
2. **Partial/missing tags — log them.** Owner's call: don't silently skip.
   An untagged track still doesn't contribute to the hit/miss rate (no
   ground truth to compare against), but it should be visibly counted
   (e.g. "312/400 eval cycles had a usable tag this session") so a low
   accuracy sample size is never mistaken for a low accuracy score.
3. **Where the rollup lives — confirmed.** `scorecard.md` generation
   (`package_training_set.py`), alongside the existing lock/director
   quality summaries — not a new artifact type.
4. **Tag genre as a *training* signal vs. a *live* signal — owner is
   "kinda shootin' for" the live version eventually.** This is a real
   intended direction, not a hypothetical — the owner wants tag genre to
   become an actual ground-truth signal the live recommender can use, not
   just a packaging-time measurement. That's a materially bigger change
   than anything else in this spec (effectively teaching the recommender
   to trust curated metadata over its own acoustic scoring when both are
   available) and needs its own design pass once Tier 2's offline measurement
   exists and the mapping table has real mileage on it — surfacing questions
   like: does a tag match override the acoustic score outright, blend with
   it, or just raise the confirm-wins/margin bar for anything the tag
   disagrees with? Deliberately not scoped further here; revisit once Tier 2
   offline data exists to ground the decision in something other than a
   guess.

## Non-goals for this spec

- Tier 1 and Tier 2 are both done (2026-08-06 and 2026-08-07 respectively) —
  this document remains the design record for both.
- Tag genre was not fed into the live `_profile_score()` composite as part
  of Tier 2 — it remains an offline/packaging-time accuracy measurement.
  The owner has signaled that's not the end state (see question 4), but the
  live-feedback design is still its own future pass, not folded in here.
- The keyword-fallback table (`_GENRE_KEYWORD_MAP`) was written as part of
  Tier 2's implementation — see the ADR entry for its contents and the
  judgment calls made while writing it.
