# Auto VJ Recommender — Accuracy Tracking Spec

Status: proposed, not yet implemented
Owner: unicorn-viz maintainers
Last updated: 2026-08-06

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

## Tier 1 — signal activity (buildable now, no ground truth needed)

A diagnostic proxy for "is this term actually discriminating between
candidates, or just adding noise to every score by a constant?" Per eval
cycle, for each term (`tempo_fit`, `centroid_fit`, `band_fit`, …), compute
the **spread** of that term's raw (pre-weight) value across all scored
candidates — e.g. `max - min`, or standard deviation across the candidate
set. A term with near-zero spread across candidates this cycle is
contributing a constant offset to every score, not helping distinguish
psytrance from deep_house *this cycle*, regardless of its weight.

Logged per cycle to the existing decision-log JSONL (same file
`profile_auto_reco_*` events already land in), then rolled up by
`session_scorecard.py` / `package_training_set.py` (training-kit-01) into a
per-term "activity score" for the session: what fraction of cycles did this
term have non-trivial spread. Over many sessions this becomes a real signal
for "`kick_regularity_fit` has near-zero spread in 90% of cycles across the
last 10 sessions — its weight is currently doing nothing" without needing
to know which candidate was *correct*.

This does not require the mixer's genre tags, does not require the owner to
curate anything, and could ship as a training-kit-01 change alone.

## Tier 2 — tag-based genre as ground truth (needs curated library)

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

**Open design questions, not yet resolved:**

1. **Genre-tag → profile-key mapping.** ID3 `GENRE` strings are free text
   ("Progressive House", "Psy-Trance", "UK Garage / 2-Step") and won't map
   1:1 onto the 21 `PROFILES` keys. Needs a lookup table (probably
   many-to-one, several tag strings mapping to the same profile key) plus
   an explicit "unmapped, skip this track for accuracy purposes" bucket
   rather than guessing.
2. **Partial/missing tags.** Not every track in a library will be tagged,
   especially older or less-curated portions. Tier 2 must degrade
   gracefully per-track (skip untagged tracks for accuracy purposes,
   don't block or warn) rather than assume full coverage.
3. **Where the rollup lives.** Likely a new section in the existing
   `scorecard.md` generation (`package_training_set.py`), alongside the
   existing lock/director quality summaries — not a new artifact type.
4. **Tag genre as a *training* signal vs. a *live* signal.** This spec is
   about post-hoc accuracy measurement during packaging/review, not about
   feeding the tag back into the live recommender at runtime (that would be
   a much bigger change — effectively a ground-truth override — and is out
   of scope here unless the owner wants to open it).

## Non-goals for this spec

- Not building either tier yet — this document is the spec for review.
- Not proposing to feed tag genre into the live `_profile_score()` composite
  as a term; Tier 2 is an offline/packaging-time accuracy measurement.
- Not proposing a specific genre-tag taxonomy/lookup table yet — question 1
  above needs an answer before that table can be written.
