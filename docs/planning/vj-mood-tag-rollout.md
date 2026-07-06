# VJ Mood-Tag Rollout — Spec + Verification Sheet

Owner: owner + Claude Opus (master coordinator)
Status: In progress — effect moods being confirmed via Q&A
Last updated: 2026-07-13

Authoritative spec for the mood-tag work (VJ tag fix #2 + #3). Written **before**
implementation so the applied tags can be diff-checked against it afterward — a
prior big tag update didn't fully land, so this sheet is the cross-check.

---

## 1) Mood vocabulary (low → high energy)

`chill` → `groovy` → `energetic` → `intense` → `hard`

Each rotation effect gets **exactly one** mood tag, **appended** to its existing
category/style `TAGS` (categories are not removed — the effects browser still
uses them).

---

## 2) Scene → mood mapping, per VJ mood profile

These populate the per-scene `*_effect_tags` on the VJ **mood profiles**
(`chill` / `normie` / `raver`) — distinct from the audio profiles. Cruise with an
empty set falls back to any enabled effect.

### chill
| Scene | Moods |
|-------|-------|
| cruise | chill, groovy |
| breakdown | chill |
| drop | groovy, energetic |
| impact | intense, energetic |
| climax | energetic, hard, intense |

### normie
| Scene | Moods |
|-------|-------|
| cruise | chill, groovy, energetic |
| breakdown | chill, groovy |
| drop | energetic, intense |
| impact | intense, hard |
| climax | energetic, hard, intense |

### raver
| Scene | Moods |
|-------|-------|
| cruise | groovy, energetic |
| breakdown | chill, groovy |
| drop | energetic, intense |
| impact | intense, hard |
| climax | energetic, hard, intense |

---

## 3) Effect → mood (proposed; being confirmed via Q&A)

Status legend: `proposed` (my call) → `confirmed` (owner-approved via Q&A).

| Effect | Pack | Proposed mood | Status |
|--------|------|---------------|--------|
| Cathedral of Bass | immersive-01 | hard | proposed |
| Fireworks | particles-01 | hard | proposed |
| America 250 | holiday-01 | hard | proposed |
| Cyber War | tech-01 | intense | proposed |
| Tron Grid | tech-01 | intense | proposed |
| Threat Matrix | tech-01 | intense | proposed |
| Particle Storm | particles-01 | intense | proposed |
| Psychedelic | psychedelic-01 | intense | proposed |
| Alien Invasion | cosmic-01 | intense | proposed |
| Black Hole Cathedral | cosmic-01 | intense | proposed |
| Audio Sine | core | energetic | proposed |
| Kaleidoscope | psychedelic-01 | energetic | proposed |
| Rainbow Trance | feature-01 | energetic | proposed |
| Tunnel | immersive-01 | energetic | proposed |
| Wormhole | immersive-01 | energetic | proposed |
| Disco Ball | vector-01 | energetic | proposed |
| Fractal Zoom | retro-01 | energetic | proposed |
| Hacker Terminal | tech-01 | energetic | proposed |
| Hacker Terminal 2.0 | tech-01 | energetic | proposed |
| Breakout | games-01 | energetic | proposed |
| ProjectM Presets | projectm-01 | energetic | proposed |
| Plasma | psychedelic-01 | groovy | proposed |
| Wavey Gravy | cosmic-01 | groovy | proposed |
| Hexy Stars | feature-01 | groovy | proposed |
| Metaballs | feature-01 | groovy | proposed |
| Unicorn Tears | unicorn-tears-01 | groovy | proposed |
| Copper Bars | retro-01 | groovy | proposed |
| 3D Cube | vector-01 | groovy | proposed |
| Vector | vector-01 | groovy | proposed |
| Sim Showcase | sims-01 | groovy | proposed |
| Audio Centroid | core | groovy | proposed |
| Audio Spectrum | core | groovy | proposed |
| Audio Spectrogram | core | groovy | proposed |
| Audio Waveforms | core | groovy | proposed |
| Audio Tracks | core | chill | proposed |
| Cosmos | cosmic-01 | chill | proposed |
| Starfield | particles-01 | chill | proposed |
| Dali | retro-01 | chill | proposed |
| Escher | retro-01 | chill | proposed |
| Van Gogh | retro-01 | chill | proposed |
| ANSI Viewer | retro-01 | chill | proposed |
| Image Showcase | images-01 | chill | proposed |
| Texture Showcase | textures-01 | chill | proposed |
| Video Showcase | videos-01 | chill | proposed |

Count (proposed): hard 3, intense 7, energetic 11, groovy 13, chill 10 = **44**.

---

## 4) Rollout + verification checklist

- [ ] Confirm all 44 effect moods via Q&A; mark rows `confirmed`.
- [ ] Locate the VJ mood-profile definitions (`chill`/`normie`/`raver`) and set
      their per-scene `*_effect_tags` per §2 (auto-vj-01 submodule).
- [ ] Append the mood tag to each effect's `TAGS` per §3 (per pack; some in
      submodule packs — commit/push/pointer-bump each).
- [ ] **Cross-check:** re-scan `get_effects()` and assert every rotation effect
      carries exactly one of {chill, groovy, energetic, intense, hard}, matching
      this sheet row-for-row. (This is the "did they all land?" gate.)
- [ ] Regression test: assert full mood coverage (no rotation effect without a
      mood tag) so future effects can't silently regress.
