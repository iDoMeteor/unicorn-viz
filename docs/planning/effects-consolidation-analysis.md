---
Owner: System Architecture
Status: draft
Last updated: 2026-06-16
---

# Effects Consolidation Analysis

## Current State

### Core effects (29)
Visuals: alien_biome, ansi_viewer, breakout, cosmos, cube_3d, crystal_pyramids, escher, dali, fractal_zoom, kaleidoscope, metaballs, particle_storm, plasma, psychedelic, sine_scroller, starfield, tunnel, van_gogh, vector

Audio-reactive: audio_spectrogram, audio_spectrum, audio_tracks, audio_waveforms

System: copper_bars, fireworks, system_monitor

### Drop-in effects (14)
Visuals: alien-invasion-01, candy-frame-01, cyber-war-01, disco-ball-01, grand-finale-01, hacker-terminal-01, tron-grid-01, unicorn-tears-01

Media: images-01, sims-01, textures-01, videos-01

External: projectm-01

Overlay: webcam-01

### Infrastructure drop-ins (8+)
Automation: auto-vj-01

UI/Control: banner-01, control-room-01

System: multi-head-01, postfx-01

Integration: spotify-01, streaming-01

---

## Option A: Create `effects-bulk-01` Drop-in

Move all core effects + all effect drop-ins into a single drop-in submodule.

### Structure
```
drop-ins/effects-bulk-01/
├── effects/
│   ├── core/          # Move unicornviz/effects/* here
│   │   ├── alien_biome.py
│   │   ├── audio_spectrum.py
│   │   └── ...
│   ├── alien_invasion/
│   ├── candy_frame/
│   ├── cyber_war/
│   ├── images/
│   ├── projectm/
│   ├── sims/
│   ├── textures/
│   ├── tron_grid/
│   ├── unicorn_tears/
│   ├── videos/
│   └── webcam/
├── __init__.py        # Provides effect discovery/registration
└── README.md
```

### Pros

✅ **Clear separation:** Core effects separate from infrastructure (control-room, multi-head, postfx, banner)

✅ **Reduced core bloat:** unicornviz/ becomes lighter, focused on runtime + infrastructure only

✅ **Consistent pattern:** All effects follow same contribution model (submodule-based)

✅ **Easier to disable:** Can exclude `effects-bulk-01` to run with zero effects (debugging infrastructure)

✅ **Simpler distribution:** Ship effects as optional feature set vs. mandatory

✅ **Cleaner git history:** Core repo only tracks infrastructure changes; effect development in submodule

✅ **Standardized docs:** All effects follow same structured-docs template

✅ **Faster core install:** unicornviz package smaller for headless/API deployments

### Cons

❌ **Monolithic submodule:** Single large submodule may become unwieldy over time (43 effects in one repo)

❌ **Reduced modularity:** Can't independently version individual effects (all effects versioned together)

❌ **Harder selective loading:** If you want only Image/Video effects, must load entire bulk

❌ **Development friction:** Contributors adding one effect must clone massive submodule

❌ **One-offs get buried:** Small specialized effects (coffee-cup, screensaver) less discoverable

❌ **Configuration complexity:** Need to remap config sections from `[effects.EffectName]` → `[effects_bulk_01.EffectName]`

❌ **Break existing configs:** Existing `config.toml` entries invalid until migration

---

## Option B: Move All Effect Drop-ins Into Core

Integrate alien-invasion-01, candy-frame-01, … videos-01 directly into `unicornviz/effects/`.

### Structure
```
unicornviz/effects/
├── alien_biome.py           # Existing core effects
├── audio_spectrum.py
├── van_gogh.py
├── ...
├── alien_invasion/          # Drop-in effects become subdirectories
│   ├── __init__.py
│   ├── alien_invasion_effect.py
│   └── README.md
├── candy_frame/
├── cyber_war/
├── grand_finale/
├── hacker_terminal/
├── images/
├── projectm/
├── sims/
├── textures/
├── tron_grid/
├── unicorn_tears/
├── videos/
└── webcam/
```

### Pros

✅ **Single flat namespace:** All effects in one place, no discovery mechanism needed

✅ **Simpler imports:** `from unicornviz.effects import VanGogh, AlienInvasion`

✅ **No submodule overhead:** No git submodule complexity, all code in main repo

✅ **Easier dependency management:** Can pin dependencies once; easier to share libraries

✅ **Unified testing:** Single test suite for all effects

✅ **Reduced complexity:** Registry just scans `effects/` — no dropin discovery fallback

✅ **Better IDE support:** Single codebase means better autocomplete/refactoring

✅ **Config unchanged:** No migration needed; `[effects.EffectName]` continues working

### Cons

❌ **Core bloat:** unicornviz/ grows to ~43 effects + docs + 100K+ LOC

❌ **Monolithic releases:** Can't ship core without all effects; must version together

❌ **No independent iteration:** Effect bug fixes require main release cycle

❌ **Coupling risk:** Infrastructure changes can break effects; effects can impact core stability

❌ **Community friction:** Harder to accept community effect contributions (larger review scope)

❌ **Distribution:** Users installing unicornviz for API/headless work get unnecessary effect code

❌ **Maintenance burden:** Core team responsible for all effect code

❌ **Git history complexity:** 43 effects' history tangled with infrastructure changes

---

## Recommendation Matrix

| Factor | Option A | Option B |
| --- | --- | --- |
| **Core maintainability** | ⭐⭐⭐⭐ Best | ⭐⭐ Harder |
| **Distribution size** | ⭐⭐⭐⭐⭐ Best | ⭐⭐ Large |
| **Modularity** | ⭐⭐⭐ OK | ⭐⭐⭐⭐⭐ Best |
| **Ease of use** | ⭐⭐⭐ OK | ⭐⭐⭐⭐ Better |
| **Development speed** | ⭐⭐⭐ OK | ⭐⭐⭐⭐ Better |
| **Independent versioning** | ⭐⭐⭐⭐⭐ Best | ⭐⭐ Together |
| **Configuration friction** | ⭐⭐⭐ Needs migration | ⭐⭐⭐⭐⭐ None |
| **Community contributions** | ⭐⭐⭐ Easier | ⭐⭐ Harder |

---

## Hybrid Option C: Mini-Bulk Drop-ins by Category

Group effects into category-focused drop-ins:
- `effects-visuals-01` (alien-invasion, candy-frame, cyber-war, disco-ball, grand-finale, hacker-terminal, tron-grid)
- `effects-media-01` (images, sims, textures, videos)
- `effects-audio-reactive-01` (core audio effects + webcam)
- Core keeps foundational effects (plasma, kaleidoscope, escher, etc.)

### Hybrid Pros
- Balanced: Reduce core without huge monolith
- Selective: Load only category-relevant effects
- Discoverable: Smaller focused repos

### Hybrid Cons
- Still requires submodule infrastructure
- Arbitrary categorization may not fit future effects
- More maintenance than Option A or B

---

## Decision Framework

**Choose Option A if:**
- You want a lean, infrastructure-focused core
- You're comfortable managing a large effects repository
- You want future infrastructure changes isolated from effect development
- You plan to ship headless/API deployments often

**Choose Option B if:**
- Developer experience and simplicity are priorities
- Monolithic releases are acceptable
- You want unified testing and dependency management
- Most users will always load all effects anyway

**Choose Option C if:**
- You want a middle ground with some modularity
- Users often want specific effect categories
- You can commit to stable categorization

---

## Implementation Effort

**Option A:**
- ~4h: Create submodule structure & move files
- ~2h: Update registry to handle mixed core+dropin
- ~2h: Config validation/migration
- ~1h: Update docs/build scripts

**Option B:**
- ~3h: Integrate drop-in files into core structure
- ~1h: Update import paths in registry
- ~30m: Update tests/CI

**Option C:**
- ~6h: Three submodules + categorization
- ~2h: Registry updates
- ~2h: Config handling
