# Audio Profile Reference

Owner: Studio Documentation
Status: active
Last updated: 2026-07-08

Full numeric specification for every `AudioProfile` in
`unicornviz/audio/profiles.py`, used by the BPM detector (tempo prior +
search-range cap) and the Auto VJ profile recommender (`_profile_score()` in
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

| profile | bpm_prior_mu | σ (log2) | bpm_hint (search cap) | spectral_centroid_mu | zcr_mu | onset_density_mu | vocal_hnr_mu | vocal_fmr_mu |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `house` | 124 | 0.35 | 120-128 | 1500 | 0.060 | 2.5 | 0.35 | 0.25 |
| `tech_house` | 126 | 0.16 | 122-130 | 1700 | 0.065 | 2.8 | 0.35 | 0.25 |
| `peak_time` | 130 | 0.24 | 126-136 | 2000 | 0.072 | 3.2 | 0.35 | 0.25 |
| `trance` | 138 | 0.20 | 134-142 | 2200 | 0.080 | 3.5 | 0.35 | 0.25 |
| `psytrance` | 145 | 0.16 | 140-149 | 2500 | 0.090 | 4.0 | 0.35 | 0.25 |
| `electronic` | 125 | 0.35 | 118-132 | 1600 | 0.052 | 2.5 | 0.35 | 0.25 |
| `hardgroove` | 136 | 0.18 | 132-140 | 1800 | 0.086 | 3.2 | 0.35 | 0.25 |
| `uk_garage` | 132 | 0.20 | 128-136 | 1700 | 0.068 | 2.8 | 0.35 | 0.25 |
| `breaks` | 138 | 0.28 | 132-145 | 1900 | 0.075 | 3.5 | 0.35 | 0.25 |
| `hard_techno` | 148 | 0.22 | 142-154 | 2000 | 0.075 | 3.5 | 0.35 | 0.25 |
| `hardstyle` | 150 | 0.16 | 145-165 | 1550 | 0.130 | 4.0 | 0.35 | 0.25 |
| `drum_and_bass` | 174 | 0.18 | 168-178 | 2200 | 0.085 | 4.5 | 0.35 | 0.25 |
| `dubstep` | 140 | 0.10 | 138-142 | 950 | 0.095 | 1.8 | 0.35 | 0.25 |
| `rap` | 88 | 0.30 | 70-100 | 1600 | 0.060 | 2.0 | 0.55 | 0.50 |
| `hyphy` | 95 | 0.25 | 90-110 | 1800 | 0.068 | 2.5 | 0.55 | 0.50 |
| `r&b` | 85 | 0.30 | 75-100 | 1400 | 0.048 | 1.8 | 0.60 | 0.55 |
| `generic` | 120 | 0.55 | 108-132 | 1600 | 0.065 | 2.5 | — | — |
| `ambient` | 100 | 0.60 | 84-116 | 800 | 0.030 | 0.4 | — | — |
| `chillstep` | 95 | 0.50 | 78-112 | 900 | 0.040 | 1.5 | — | — |

`—` = uncalibrated (`None`), skipped in that scoring dimension. `bpm_hint`
hard-caps the ACF search range (`beat_grid.py`); every profile has one
except where noted historically (all 20 do as of 2026-07-08 — see the
"rap/hyphy/r&b bpm_hint gap fixed" ADR entry).

## Confusability Analysis (2026-07-08)

See `docs/adr/vj-system.md` → "Profile Confusability Pass" for methodology
and the ranked list of closest-competing profile pairs, computed directly
from the recommender's own `_profile_score()` weights and Gaussian sigmas
rather than eyeballed.
