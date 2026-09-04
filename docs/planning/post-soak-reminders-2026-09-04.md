Owner: audio/recommender
Status: active — post-soak punch list
Last updated: 2026-09-04

# Post-Soak Reminders (2026-09-04)

Deferred items from the 2026-09-04 detector-soak/spectral-shape-ribbon
session — owner: "address next week." Not urgent, not forgotten. See
[[feedback-detector-soak-freeze]] for the soak itself; this list is what
comes after it, not part of it.

## 1. Progressive Trance / Melodic Techno — a missing genre pocket

Owner: "we def run into some stuff that is pretty trancey but in high
120s/low 130s" — real material that doesn't fit the current `trance`
profile (`bpm_prior_mu=138`, hint `134-142`) or anything else in the
roster.

Two real candidate genre names, either plausible without hearing the
actual reference tracks:

- **Progressive Trance** — typically 128-132 BPM, slower and more
  house-adjacent than standard uplifting trance's 134-142. If the
  material still *feels* like trance top-to-bottom (soft kick, trance-
  style build/breakdown structure) just at a lower tempo, this is the
  more likely fit.
- **Melodic Techno** — typically 122-128 BPM, currently a very
  popular/mainstream style (Afterlife / Innervisions / Tale Of Us
  lineage) — trance-like emotional leads and breakdowns, but over a
  punchier, more techno-flavored kick than trance's softer one. If the
  low end feels more techno-hypnotic under the trance-y melodic
  elements, this is the better fit.

The real distinguishing question is kick character, not tempo alone —
worth listening for that specifically when picking real reference
material.

**Also worth checking:** `training-progressive-house-01` already exists
as a packaged training list (it came up during the same session's
spectral-shape ribbon work, provisionally pooled into `deep_house`, then
reverted — see docs/adr/vj-system.md "Data-Derived expected_bands").
Progressive house and progressive trance aren't the same genre, but
they're neighbors on the same production lineage — if a genuinely
trance-adjacent high-120s/low-130s training list gets built for this,
it's worth comparing its ribbon against both `progressive-house-01`'s
own measured fingerprint and `trance`'s, not assuming it's closer to one
or the other without checking.

**Action when picked back up:** get (or record) a real training list for
whichever genre this turns out to be, derive its ribbon (`expected_bands`/
`expected_bands_sigma`) and vocal targets the same way every other
profile in the roster was done 2026-09-03/04, and decide whether it needs
its own new profile or folds into an existing one — same evidence-based
process used for the `hyphy`/trap split, not a guess.

## 2. Ideas for the 8192-sample low-band buffer

The low-band resolution fix (2026-09-04, see docs/adr/vj-system.md
"Low-Band Resolution: Dual-Window Fix") added a persistent 8192-sample
(170.7ms at 48kHz) rolling PCM buffer + long-window FFT, currently used
only to replace the bottom 25 of the 64 perceptual bands. Owner: "we are
SO going to have to take much greater advantage of that later" — real
ideas surfaced in the same conversation, not yet scoped or built:

- **Bass note/key detection.** A note at 40 Hz has a ~25ms period — the
  short (1024-sample, 21.3ms) window can't even complete one full cycle
  of it. 170.7ms comfortably captures 6-7+ cycles even at the very
  bottom of the audible range, which is what's actually needed for
  reliable low-frequency pitch resolution. Could feed a real bass-note/
  key-detection feature that was never accurate enough to attempt on the
  short window alone.
- ~~A steadier `spectral_centroid` measurement.~~ **Superseded 2026-09-04
  (recommender rc.31) — see item 3 below.** Owner decided to remove
  `centroid_fit` outright rather than revisit it; this idea no longer
  applies.
- **A steadier input for vocal formant analysis.** `vocal_hnr`/
  `vocal_fmr` currently read the short-window spectrum; whether the
  long-window buffer's finer low-mid resolution would sharpen either
  measurement (or is irrelevant, since the vocal formant band sits well
  above where the short window already resolves fine) is an open
  question, not a known win — check before assuming.

None of these are committed work — they're flagged so the buffer's
existence doesn't get forgotten as "just the low-band fix" once the soak
ends and normal detector/recommender iteration resumes.

## 3. Full removal of all `centroid_fit` infrastructure

2026-09-04 (recommender rc.31): only the dead `_DEFAULT_RECO_WEIGHTS`
entry was removed tonight (owner picked the smallest of three offered
scopes, mid-soak). Owner, same night: "put on the list for post-soak the
full removal of all centroid stuff so it never comes back lol."

**Why it's dead, for whoever picks this up:** 2026-08-20 retirement
evidence (see docs/adr/vj-system.md) tested 57 real labeled tracks
against five different scalar brightness formulations (log-band centroid,
linear-FFT centroid, log2 centroid, ≥4kHz energy fraction, rolloff-85) —
all five agreed scalar full-mix brightness tracks mastering/loudness, not
genre. `spectral_shape_fit` (the 64-band ribbon fit) is the real
replacement — it scores the full spectral shape instead of collapsing it
to one number, and actually discriminates genre where centroid never did.

**What's left to remove, when picked back up:**
- `_profile_score()`'s `centroid_fit` computation itself
  (`drop-ins/auto-vj-01/auto_vj.py`) and its entry in the `terms` dict
  fed to `term_values_by_candidate` telemetry.
- `spectral_centroid_mu`/`spectral_centroid_sigma` fields on
  `AudioProfile` (`unicornviz/audio/profiles.py`) and every profile's
  values for them (17 profiles set these).
- The 2026-09-04 mechanical `spectral_centroid_mu` recompute note in
  profiles.py's field comment, the centroid rows in
  `weights-and-thresholds.md`'s "Audio profile centroid sigmas" table,
  and the retirement/history writeups in both that doc and
  docs/adr/vj-system.md (mark superseded, don't delete the history).
- Tests that reference `spectral_centroid_mu`/`sigma`:
  `tests/test_audio_profile_deep_house_and_disable.py`
  (`test_deep_house_is_warmer_than_house_and_tech_house`),
  `tests/test_audio_profile_synthwave.py`
  (`test_synthwave_spectral_fields_are_calibrated`), and any others a
  fresh grep turns up at the time.
- `PERC_BAND_CENTERS_HZ` (`unicornviz/audio/analyzer.py`) — check whether
  anything else still uses it before removing; as of 2026-09-04 it's only
  documented as "left in place, unused for now" infrastructure for
  centroid recalibration.

This is a real refactor with test fallout, not a one-line change —
budget accordingly when it's picked up.
