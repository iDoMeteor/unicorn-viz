# VJ Mood-Tag Rollout — Spec + Verification Sheet

Owner: owner + Claude Opus (master coordinator)
Status: Complete — tag fixes #2 and #3 both landed and cross-checked
Last updated: 2026-07-13

Authoritative spec for the mood-tag work (VJ tag fix #2 + #3). Written **before**
implementation so the applied tags can be diff-checked against it afterward — a
prior big tag update didn't fully land, so this sheet is the cross-check.

---

## 1) Mood vocabulary (low → high energy)

`chill` → `groovy` → `energetic` → `intense` → `hard`

Each rotation effect gets **one or more** mood tags (owner chose multi-mood so
versatile effects span scenes — e.g. Psychedelic is `chill` *and* `intense`),
**appended** to its existing category/style `TAGS` (categories are not removed —
the effects browser still uses them).

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

## 3) Effect → mood(s) — CONFIRMED via Q&A (2026-07-13)

Authoritative assignment. Moods are **appended** to each effect's existing tags.

| Effect | Pack | Moods (confirmed) |
|--------|------|-------------------|
| Cathedral of Bass | immersive-01 | hard |
| Fireworks | particles-01 | energetic |
| America 250 | holiday-01 | energetic |
| Cyber War | tech-01 | intense |
| Tron Grid | tech-01 | intense |
| Threat Matrix | tech-01 | hard |
| Particle Storm | particles-01 | intense |
| Psychedelic | psychedelic-01 | chill, intense |
| Alien Invasion | cosmic-01 | groovy |
| Black Hole Cathedral | cosmic-01 | chill, energetic, hard |
| Audio Sine | core | groovy, intense, hard |
| Kaleidoscope | psychedelic-01 | groovy, intense |
| Rainbow Trance | feature-01 | chill, groovy, energetic, intense |
| Tunnel | immersive-01 | intense |
| Wormhole | immersive-01 | chill, energetic, intense |
| Disco Ball | vector-01 | chill, groovy, intense |
| Fractal Zoom | retro-01 | chill, groovy |
| Hacker Terminal | tech-01 | energetic, intense |
| Hacker Terminal 2.0 | tech-01 | energetic, intense |
| Breakout | games-01 | groovy |
| ProjectM Presets | projectm-01 | chill, groovy, energetic, intense, hard |
| Plasma | psychedelic-01 | intense |
| Wavey Gravy | cosmic-01 | groovy, intense |
| Hexy Stars | feature-01 | energetic, hard |
| Metaballs | feature-01 | energetic, intense, hard |
| Unicorn Tears | unicorn-tears-01 | chill, groovy, intense, hard |
| Copper Bars | retro-01 | chill, groovy, energetic, intense |
| 3D Cube | vector-01 | chill, groovy, intense |
| Vector | vector-01 | chill, groovy, intense |
| Sim Showcase | sims-01 | groovy, intense |
| Audio Centroid | core | groovy, intense, hard |
| Audio Spectrum | core | chill, groovy, energetic, intense |
| Audio Spectrogram | core | groovy, intense |
| Audio Waveforms | core | energetic, intense |
| Audio Tracks | core | chill, energetic, intense |
| Cosmos | cosmic-01 | groovy, intense |
| Starfield | particles-01 | energetic, intense |
| Dali | retro-01 | chill, groovy, intense |
| Escher | retro-01 | groovy, intense |
| Van Gogh | retro-01 | groovy, energetic, intense |
| ANSI Viewer | retro-01 | groovy, intense |
| Image Showcase | images-01 | chill, groovy, energetic, intense, hard |
| Texture Showcase | textures-01 | groovy |
| Video Showcase | videos-01 | chill, groovy, energetic, intense, hard |

Mood coverage (effects carrying each): **chill 16, groovy 24, energetic 17,
intense 34, hard 11** — every scene now draws from a healthy spread (no more
5-effect drop lock-in).

---

## 4) Rollout + verification checklist

- [x] Confirm all 44 effect moods via Q&A; mark rows `confirmed`.
- [x] Locate the VJ mood-profile definitions (`chill`/`normie`/`raver`) and set
      their per-scene `*_effect_tags` per §2 (auto-vj-01 submodule, commit
      `196b5db`). Discovered the profiles already override the scene tags (the
      constructor fallback in §1's original diagnosis never fires); the *live*
      tag lists were a different, mostly-dead vocabulary (`ambient`, `audio`,
      `futuristic` all resolved to 0 effects) — replaced with the mood
      vocabulary per §2.
- [x] Append the mood tag to each effect's `TAGS` per §3 (16 packs + core;
      commit/push/pointer-bump each — main repo `ead2908`/`813c4fc`/`cb5d04c`,
      auto-vj-01 pointer `6f23430`). `projectm-01` needed a one-off fix: an
      orphaned stray `main` branch blocked a push; the real default branch
      (`master`) fast-forwarded cleanly with no history rewrite.
- [x] **Cross-check:** scripted apply + immediate re-scan confirmed all 44
      effects match this sheet row-for-row (`tests/test_effect_mood_coverage.py`
      + a one-off verification script both green). Zero drift.
- [x] Regression test: `tests/test_effect_mood_coverage.py` asserts every
      rotation effect carries ≥1 mood tag and all five moods are represented.

**Verified scene coverage after both fixes** (effects matched per scene, out of
44): chill profile 16–40, normie 29–40, raver 29–40 — up from ~5 for every
drop/impact/climax before this work.
