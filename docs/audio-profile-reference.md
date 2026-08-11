# Audio Profile Reference

Owner: Studio Documentation
Status: active
Last updated: 2026-08-11

Full numeric specification for every `AudioProfile` in
`unicornviz/audio/profiles.py`, used by the BPM detector (tempo prior) and
the Auto VJ profile recommender (`_profile_score()` in
`drop-ins/auto-vj-01/auto_vj.py`).

See `unicornviz/audio/profiles.py`'s module docstring for the research
grounding behind the spectral fingerprints (`expected_bands`) — synthesized
from AcousticBrainz, GTZAN (Tzanetakis & Cook, 2002), FMA (Defferrard et al.,
2017), and EDM classification literature (Sturm 2012; Bonnin & Jannach 2014;
Schedl et al. 2018).

`vocal_hnr_mu` / `vocal_fmr_mu` are a 2026-07-08 addition and are first-pass,
unvalidated starting values — see the "Vocal-Presence Heuristics" ADR entry
in `docs/adr/vj-system.md` for what they measure and their known limits.

## Full Table

Regenerated 2026-08-11 directly from `unicornviz/audio/profiles.py` (16
profiles, down from 20 as of the last full regen — `uk_garage`, `breaks`,
`generic`, and `hardgroove` all eliminated entirely since, each for the
same reason: zero validated library examples plus heavy overlap with
better-populated neighbors; see `docs/adr/vj-system.md`). `electronic`'s
display name is "Dance" (dict key kept for backward compatibility);
`hyphy`'s is "Hyphy / Trap" and it is currently **disabled**
(`enabled=False`, still directly resolvable via `get_profile('hyphy')`)
pending real trap/hyphy library material. `tech_house` is also currently
**disabled** (`enabled=False`, still directly resolvable via
`get_profile('tech_house')`) as of 2026-08-11, pending a library with
enough tech_house-specific material to recalibrate `spectral_centroid_mu`
against a real measured average — see `docs/adr/vj-system.md` § "Recommender
centroid_fit Weight Cut + tech_house Disabled".

| profile | bpm_prior_mu | σ (log2) | bpm_hint (display range) | spectral_centroid_mu | zcr_mu | onset_density_mu | vocal_hnr_mu | vocal_fmr_mu |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `house` | 122 | 0.10 | 118-126 | 2650 | 0.060 | 2.5 | 0.35 | 0.25 |
| `deep_house` | 115 | 0.10 | 112-118 | 1250 | 0.048 | 2.0 | — | — |
| `tech_house` *(disabled)* | 130.5 | 0.09 | 127-134 | 2900 | 0.065 | 2.8 | 0.35 | 0.25 |
| `peak_time` | 130 | 0.24 | 126-136 | 2350 | 0.072 | 3.2 | 0.35 | 0.25 |
| `trance` | 138 | 0.20 | 134-142 | 2000 | 0.080 | 3.5 | 0.35 | 0.25 |
| `psytrance` | 145 | 0.16 | 140-149 | 2150 | 0.090 | 4.0 | 0.35 | 0.25 |
| `electronic` ("Dance") | 122 | 0.10 | 118-126 | 2650 | 0.060 | 2.5 | 0.05 | 0.05 |
| `hard_techno` | 148 | 0.22 | 142-154 | 2450 | 0.075 | 3.5 | 0.35 | 0.25 |
| `hardstyle` | 150 | 0.16 | 145-165 | 1550 | 0.130 | 4.0 | 0.35 | 0.25 |
| `drum_and_bass` | 174 | 0.18 | 168-178 | 1700 | 0.085 | 4.5 | 0.35 | 0.25 |
| `dubstep` | 140 | 0.10 | 138-142 | 950 | 0.095 | 1.8 | 0.35 | 0.25 |
| `rap_rnb` | 85 | 0.20 | 70-100 | 1300 | 0.054 | 1.9 | 0.58 | 0.53 |
| `hyphy` *(disabled)* | 109 | 0.15 | 100-118 | 2400 | 0.068 | 2.5 | 0.55 | 0.50 |
| `ambient` | 100 | 0.60 | 84-116 | 1250 | 0.030 | 0.4 | — | — |
| `chillstep` | 95 | 0.50 | 78-112 | 1700 | 0.040 | 1.5 | — | — |
| `synthwave` | 100 | 0.34 | 85-118 | 1700 | 0.050 | 1.9 | — | — |

`—` = uncalibrated (`None`), skipped in that scoring dimension. `bpm_hint`
is a display label + scorecard metric **only** — it has **no live effect**
on the detector's ACF search range or the recommender's scoring; the
detector's search is shaped by `bpm_prior_mu`/`bpm_prior_sigma` (a soft
log2-Gaussian prior) alone. This corrects an earlier (2026-07-08) version
of this doc that described `bpm_hint` as hard-capping the search range —
that hard clamp was found and removed on 2026-08-04 (see "BPM Detector
Audit — Hard Clamp Removal" in `docs/adr/vj-system.md`), and `bpm_hint`'s
independence from `bpm_prior_mu`/`sigma` was reaffirmed deliberately on
2026-08-10 rather than derived from it (see "House-Family Consolidation").

## Confusability Analysis (2026-07-08)

See `docs/adr/vj-system.md` → "Profile Confusability Pass" for methodology
and the ranked list of closest-competing profile pairs, computed directly
from the recommender's own `_profile_score()` weights and Gaussian sigmas
rather than eyeballed.
