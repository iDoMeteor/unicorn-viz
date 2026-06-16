# Unicorn Viz — Competitive Analysis (2026-05-09)

Honest, opinionated comparison of `unicorn-viz` against well-known
open-source audio/music visualizers in the same neighborhood.

This document does not link to external repositories. Project names refer to
widely-known open-source efforts; verify current state and licensing before
drawing conclusions for production decisions.

---

## 1. Competitor set

The most relevant peers across the desktop visualizer space:

1. **projectM (libprojectM)** — C++ MilkDrop preset engine; ships with many
   front ends (standalone SDL app, plugins for media players, embedded use).
2. **Butterchurn** — JavaScript/WebGL port of MilkDrop; runs in browsers and
   Electron apps.
3. **GLava** — Lightweight GLSL spectrum visualizer for X11, optimized for
   desktop wallpaper/embed use.
4. **CAVA** — Terminal-based bar visualizer (ncurses); not GPU-shader based.
5. **Kodi/VLC built-in visualizers** — Media-player-bound visualization plugins.
6. **Web audio visualizers** (audiomotion-analyzer, etc.) — Library-focused,
   not full apps.

Unicorn Viz is closest in intent to projectM/Butterchurn (full visual show),
sits above CAVA/GLava (which are simpler bar/spectrum tools), and is more
extensible than the bundled visualizations in Kodi/VLC.

---

## 2. Where Unicorn Viz stands today

Strengths:
1. Cohesive **show framework**, not just a visualizer — playlist, transitions,
   hotkeys, MIDI, splash, ANSI integration.
2. **20+ effects** including categories competitors do not focus on
   (CP437 ANSI scene viewer, ACiD pack auto-discovery, retro demoscene tropes).
3. **First-class transition system** (12+ named transition modes with
   audio-impact-driven blending).
4. **Per-effect reactivity overrides** with absolute (not multiplicative)
   semantics and live `Ctrl+G` reset.
5. **Hotkey-rich live operation** designed for VJ-style use, not just passive
   listening (Ctrl decade for #21–30, fast scene jumps, invert).
6. **Modern Python codebase** (3.11+, type-annotated, modular `effects/`
   discovery) — easy to extend for Python-comfortable contributors.
7. **Documented standards** (`copilot-instructions.md`, `docs/`,
   `audits/`).

Gaps relative to the strongest competitors:
1. **Preset ecosystem**: projectM/Butterchurn ship hundreds of community
   MilkDrop presets. Unicorn Viz has hand-authored Python effects and no
   preset import path.
2. **Cross-platform polish**: projectM and Butterchurn have years of
   cross-OS hardening; Unicorn Viz is Linux-first.
3. **Recording/streaming integrations**: projectM has third-party paths;
   Butterchurn runs trivially in OBS via browser source.
4. **Performance ceiling**: native C++ (projectM) and tight WebGL
   (Butterchurn) generally hit higher frame rates per shader complexity than
   Python+moderngl shells.

Net positioning:
> Unicorn Viz is a **show platform** with curated effects, ANSI heritage, and
> live-control polish. Competitors are either **preset-engine focused**
> (projectM, Butterchurn) or **single-trick** (CAVA, GLava).

---

## 3. Comparative table — features

| Capability                               | Unicorn Viz | projectM | Butterchurn | GLava | CAVA |
|------------------------------------------|-------------|----------|-------------|-------|------|
| Native fullscreen GL effects             | Yes         | Yes      | WebGL       | Yes   | No (terminal) |
| Built-in effect count (curated)          | 20+         | N/A      | N/A         | Few   | 1    |
| Preset/script ecosystem                  | No          | Huge (MilkDrop) | Large (MilkDrop) | Few | None |
| Audio-reactive (FFT, beat, bands)        | Yes         | Yes      | Yes         | Yes   | Yes  |
| Beat onset detection                     | Yes         | Yes      | Yes         | Limited | Limited |
| MIDI input                               | Yes         | Limited  | No          | No    | No   |
| OSC input                                | Planned     | Limited  | No          | No    | No   |
| Hotkey-driven live control               | Yes (rich)  | Some     | Some        | Limited | Limited |
| Per-effect reactivity override           | Yes         | Per-preset | Per-preset | No    | Limited |
| Transition system                        | 12+ modes   | Crossfade-ish | Yes      | Limited | N/A |
| Playlist + auto-advance                  | Yes         | Yes      | Yes         | No    | No   |
| ANSI/CP437 art viewer                    | Yes         | No       | No          | No    | No   |
| Splash screen / branding                 | Yes         | Limited  | Limited     | No    | No   |
| Screenshot capture                       | Yes         | Varies   | Varies      | No    | No   |
| MP4/clip recording built-in              | Planned     | No       | Via OBS     | No    | No   |
| Multi-monitor support                    | Planned     | Yes      | Limited     | Yes   | N/A  |
| Wayland support                          | Yes (first) | Yes      | Browser     | X11 only | Terminal |
| Plugin/effect SDK                        | Python class | C++/preset | JS preset | GLSL | None |
| Cross-platform packaging                 | Linux       | All      | Browser/Electron | Linux | All |
| Active development today                 | Yes         | Yes      | Yes         | Lower | Yes  |

> "Planned" = present in `plan.md`. "Limited" = present but minimal vs the
> dedicated competitor in that row. Categories are intentionally coarse.

---

## 4. Comparative table — code quality / engineering posture

This is qualitative and based on widely observed properties of these
projects, not a re-audit of their current trees.

| Dimension                         | Unicorn Viz | projectM | Butterchurn | GLava | CAVA |
|-----------------------------------|-------------|----------|-------------|-------|------|
| Language                          | Python 3.11 | C++      | JavaScript  | C / GLSL | C  |
| Lines of source (rough)           | Small       | Large    | Medium      | Small | Small |
| Type annotations / typing rigor   | High (PEP 561 style) | C++ types | TS variants | C   | C    |
| Documentation                     | Good (`docs/`, instructions) | Good | Good   | OK    | OK   |
| Tests                             | Light/manual + smoke | Test suites | Some | Light | Light |
| Architecture cleanliness          | High (small modules, registry-based discovery) | Mature | Functional | Small | Small |
| Extensibility for new effects     | High (drop-in `.py`) | Preset-driven | Preset-driven | GLSL | N/A |
| Build complexity                  | Low (`pip install`) | High (CMake) | npm     | Low   | Low  |
| Runtime perf ceiling              | Medium      | High     | High        | High  | High |
| Memory footprint                  | Low–Medium  | Medium   | Medium      | Low   | Low  |
| Coding standards documented       | Yes (`.github/copilot-instructions.md`) | Yes | Mixed | Light | Light |
| Public extension point stability  | Internal-evolving | Stable preset format | Stable preset format | Stable GLSL | Stable config |
| Repo hygiene                      | Clean (no committed venv/cache) | Clean | Clean | Clean | Clean |

Highlights:
1. Python-native architecture means Unicorn Viz wins on **fast iteration**
   and **lowest-friction effect authoring**, but trails compiled engines on
   raw GPU/CPU efficiency.
2. The **registry-based effect discovery** model is unusually clean — many
   visualizers either hardcode or rely on data-format presets. Adding code
   here is `cp` + edit + run.
3. The **per-effect reactivity override** semantics are a thoughtful detail
   most competitors only express via preset-level wiring.

---

## 5. Where Unicorn Viz could "win"

If the goal is to be a credible alternative to projectM/Butterchurn for live
performance, the realistic wedges are:

1. **Live operation UX**
   - Hotkey design, MIDI/OSC parity, scene banks, beat-locked transitions,
     tap tempo. This is where projectM has historically been weak.

2. **ANSI / demoscene heritage**
   - Owning the BBS/ACiD niche is differentiated. No mainstream competitor
     even tries.

3. **Authoring ergonomics**
   - "Write a Python class, drop it in `effects/`, restart" beats authoring
     in MilkDrop's preset DSL for many devs. Doubling down on docs and a
     scaffolder is a quick advantage.

4. **Modern post-pipeline**
   - Global vignette/post-processing system (already in `plan.md`),
     effect chaining/layering, and dynamic resolution scaling could surpass
     what projectM ships out of the box.

5. **Recording / streaming integration**
   - First-class MP4 recording and PipeWire video output for OBS would close
     the gap with the browser-Electron ergonomics of Butterchurn.

---

## 6. Where Unicorn Viz will not "win" without major investment

1. Becoming a **MilkDrop preset host**. That is a multi-quarter effort and
   ports already exist. Better to interoperate (e.g., embed Butterchurn or a
   preset bridge) than rebuild.
2. Beating native engines on **raw shader complexity per frame** at low-end
   GPUs. Python overhead is small relative to fragment shader cost, but the
   ecosystem assumption "this is a Python app" caps adoption among C++/JS
   contributors.
3. Becoming a **cross-OS first-citizen** before stabilizing Linux feature
   parity.

---

## 7. Recommended strategic posture

- Position as: **"a Linux-first demoscene-flavored show framework with live
  controls, MIDI, transitions, and a tiny effect SDK in Python."**
- Avoid framing as a MilkDrop replacement.
- Compete on **show experience** and **author ergonomics**, not preset count.
- Long-term: optional **Butterchurn preset bridge** would absorb the largest
  ecosystem gap with bounded effort.

---

## 8. Quick verdict

| Use case                                                        | Best fit        |
|-----------------------------------------------------------------|-----------------|
| "I want hundreds of MilkDrop presets to react to my music"      | projectM, Butterchurn |
| "I want a tiny GPU spectrum on my desktop wallpaper"            | GLava           |
| "I want a clean terminal bar visualizer in tmux"                | CAVA            |
| "I want to perform/VJ a curated, hotkey-driven, MIDI-controlled show, mix in ANSI scene art, and write my own effects in Python" | **Unicorn Viz** |
| "I need a polished cross-OS commercial integration today"       | projectM (with caveats), Butterchurn (web) |

Unicorn Viz already owns the bottom-row use case credibly today. The
audit-listed performance and ergonomics improvements would harden that
position significantly without changing the project's core identity.
