# Mixer-Only Mode — Boot Profile + Hosted Single-Window Plan

Owner: owner + Claude (planning)
Status: proposed — owner approved the direction (single window, hosted
mixer, alternate launch methods; **no** stripped-clone fork); this doc is
the implementation plan. Coordinates with the dj-mixer team (§9).
Last updated: 2026-07-18

---

## 0) The decision, in one paragraph

One switch boots Unicorn Viz as **a DJ mixer that happens to share the
visualizer's engine** — the main window *is* the mixing console, nothing
else loads. It is a **boot profile**, not a fork: same repo, same core,
same drop-in submodules. The mixer UI renders **into the main window**
(no second window at all), launched via config, a CLI flag, or a branded
entrypoint. The rejected alternative — cloning the project and stripping
it into a separate mixer core — was ruled out because it forks ~8-10k
lines of core (`vj_api`, MIDI transport, tooltips, GL plumbing, config,
hotkeys) that would then need every fix landed twice; this project's own
second-window saga (dj-mixer cloning control-room code and drifting by
one missing call) is the case study in what that costs.

## 1) Why this is mostly assembly, not construction

Verified against the current boot path (`App.run()`):

- **Every optional drop-in load is already individually gated** by config
  `enabled` flags, and `[dropins] safe_mode` (`app.py:394`) already
  demonstrates the "one flag gates whole load blocks" pattern. (Note:
  `safe_mode`'s gate *includes* the dj-mixer block, so it is a related
  pattern, not the mechanism itself — see §6 precedence.)
- **`[dj_mixer] start_enabled` already exists** to open the mixer at boot.
- **The startup profiler** (`_StartupProfiler`) already tells us exactly
  what each skipped phase is worth.
- The splash default is now 3s (`981684a`), so even *normal* boot is
  ~4.5s; mixer-only boot lands near **~1s**.

What does **not** exist yet — the actual work:

1. The profile switch + resolution (`§5`).
2. A splash gate (today the splash always runs if the image exists).
3. An audio-capture skip (today `AudioManager.start()` always runs).
4. The hosted-window render + input path (`§3`-`§4`) — the one real
   feature. The main loop requires ≥1 effect
   (`RuntimeError: No effects found`, `app.py:3352`) and renders one
   every frame; in mixer-only mode the mixer frame replaces that.

## 2) Goals / non-goals

Goals:

- One window. The console fills it. No audience window, no idle effect.
- Boot ~1s: no splash, no audio capture, no effect warmups, no visual
  drop-ins.
- Zero behavior change when the switch is off (default). This is a hard
  requirement — normal mode must be byte-identical.
- Mixer-related drop-ins can join the profile later via an allowlist.

Non-goals:

- **No fork / clone.** (Decision recorded above.)
- **No second process / IPC protocol.** Explicitly deferred; the future
  messaging-bus idea (§10) is the eventual enabler if a split is ever
  revisited.
- No redesign of the mixer UI itself — it renders exactly what it renders
  today, just presented by the main window.
- Not removing visual code from the binary; unused modules simply never
  load/initialize.

## 3) Design — hosted mixer window

The mixer already separates *drawing* from *window ownership*, which is
what makes this cheap:

- `MixerWindow`'s render thread rasterizes the UI with PIL and publishes
  `_frame_bytes` / `_frame_size` / `_frame_id` under `_frame_lock`.
- `SecondaryGLWindow.present()` is nothing but "upload RGBA, draw a
  textured quad" — and the main window already owns the identical
  machinery (`_present_prog` / `_present_vao`).
- `_Hit` regions, pads, drag handling, and the mixer-side tooltips are
  all in full-window pixel coordinates and don't care who presents.

**Hosted mode** (new `MixerWindow` construction flag, e.g.
`hosted=True`):

- No `SecondaryGLWindow` is created; `present()` becomes a no-op; the
  window handle/id fields refer to the **main** window.
- The render thread runs unchanged, rasterizing at the main window's
  drawable size (the `ui_scale` divisor keeps working — the app upscales
  on the GPU exactly as `SecondaryGLWindow.present()` does today).
- The app, in mixer-only mode, replaces the per-frame *effect render*
  step with: consume the latest published frame (only re-upload when
  `_frame_id` advanced — the mixer renders ~30fps, the upload is skipped
  on unchanged frames), draw it via the present pipeline. Overlays
  (flash messages, help) still composite on top afterwards, unchanged.
- Frame pacing: main loop stays vsync'd; a texture upload at ≤30fps plus
  one quad is negligible GPU load.

## 4) Design — input routing

Reuses the claimed-window mechanism verbatim, pointed at the main window:

- In hosted mode the controller calls
  `claim_window_events(main_window_id, mixer.on_sdl_event)`. Claimed
  handlers run **before** the app's main event handling and swallow the
  event (`app.py:3773`), and the mixer already forwards every key it
  doesn't handle to global hotkeys via
  `vj_api.dispatch_subwindow_keydown/keyup` — so Shift+D, H (help), and
  friends keep working with zero new plumbing.
- Mouse coordinates already match the raster (full-window pixels — the
  invariant `50a3d4b` established for `_Hit`).
- **Esc-Esc semantics change in this mode:** "close the mixer window"
  becomes "quit the app" (there is nothing to fall back to). Same
  two-press confirm UX, different final action; the footer banner text
  should say QUIT.
- Window RESIZED: forward to the hosted mixer so the raster follows the
  drawable size (same drawable-size discipline as the standalone window).
- Cursor: `is_open=True` already makes the cursor visible via the
  existing subsystem policy. Shift+D in this mode toggles nothing (the
  mixer *is* the window) — make it a no-op with a flash message, or
  leave it closing/opening the hosted view over a black window; proposed:
  no-op + flash "Mixer mode".

## 5) Design — the profile switch & launch methods

Three doors, one resolution point, resolved once and early:

1. **Config:** `[dj_mixer] mixer_only = false` (default). Core reads the
   *section* via its own config loader — reading a drop-in's config
   section is fine (config.toml is core-owned); the independence rule
   forbids importing drop-in *code*, which this never does. The profile
   must also behave sanely if dj-mixer-01 is absent: log a clear error
   ("mixer_only requires the dj-mixer-01 drop-in") and fall back to
   normal boot.
2. **CLI:** `--mixer` in `unicornviz/__main__.py` (argparse already
   exists there; the flag overrides config; wins over `mixer_only=false`).
3. **Branded entrypoint:** add `unicorn-mix = "unicornviz.__main__:main_mixer"`
   beside the existing `unicorn-viz` console script in `pyproject.toml`,
   where `main_mixer()` is a two-line wrapper that injects `--mixer`.
   Desktop launcher/icon can point at it later — its own identity, zero
   fork.

Resolved into a single `App._boot_profile: str` (`'full'` | `'mixer'`)
attribute set in `App.__init__` — every gate below reads that, never the
raw config, so precedence lives in one place.

## 6) What the mixer profile changes at boot

| Phase (profiler mark) | Normal | Mixer-only |
|---|---|---|
| SDL + main window + moderngl | ✅ | ✅ (window title "Unicorn Mix"; default windowed — `[window]` config still respected) |
| `AudioManager.start()` (capture) | ✅ | **skipped** — object constructed, never started; the loop's per-frame `get_audio_data()` (`app.py:4125`) returns silent data. No input device claimed. |
| Image/Sim/ProjectM/Media prescans | ✅ | **skipped** |
| Splash | ✅ (3s) | **skipped** (new `[splash] enabled` gate, forced off by the profile; also honored in normal mode as a standalone win) |
| MIDI (`MidiManager`) | ✅ | ✅ — REV1 transport is core-owned by policy; APC also connects (its VJ actions mostly no-op; harmless) |
| Effects discovery + warmups + Playlist | ✅ | **skipped**, including the ≥1-effect `RuntimeError` (guarded by profile) |
| Overlays | ✅ | ✅ minimal — flash messages, help overlay, tooltips config. Help sections filtered to mixer-relevant + core (see §8 risks) |
| Hotkeys | ✅ | ✅ (visual-target keys act on nothing; acceptable "it is what it is" tier) |
| Spotify / Media / Chat / webcam / postfx / color-grade / candy-frame / lyrics / auto-vj / grand-finale / CTA / banner / streaming / recording / control room / OSC(?) | ✅ | **skipped** except entries in `mixer_allow` (§7). OSC: default skip; add to `mixer_allow` if the control surface is wanted for mixing. |
| dj-mixer-01 | ✅ (idle until Shift+D) | ✅ — constructed, then **auto-opened in hosted mode** (profile implies `start_enabled` semantics) |
| Main loop | effect render + HUD | hosted-frame present + overlays |

Precedence rules (all decided here, once):

- `--mixer` > `[dj_mixer] mixer_only` > default full.
- `safe_mode=true` + mixer profile: **mixer profile wins for the mixer
  itself** (safe_mode currently gates the dj-mixer block too, which would
  make the combination boot into nothing). Everything else stays maximally
  skipped. Log the combination loudly.
- `mixer_only=true` + `dj_mixer.enabled=false`: contradiction — log error,
  boot normal mode.

## 7) Config spec (all additive; defaults preserve today's behavior)

```toml
[dj_mixer]
# mixer_only = false      # boot straight into the mixer console (single window)
# mixer_allow = []        # extra drop-ins to load in mixer-only mode, by
                          # config-section name, e.g. ["osc"]

[splash]
# enabled = true          # new gate; mixer-only forces it off
```

## 8) Risks & traps

| Risk | Notes / mitigation |
|---|---|
| Coordination with in-flight dj-mixer work | Hosted mode touches `ui.py` + `dj_mixer_controller.py` — land as a coordinated phase with the mixer team (§9), not a drive-by. The core-side profile (P1) touches neither. |
| Normal-mode regression | Hard requirement: every change is behind `_boot_profile == 'mixer'` or a new default-true config gate. Regression suites must pass untouched; add a boot-profile test that asserts the gate set for `'full'` is empty. |
| Esc-Esc now quits | Deliberate (§4); needs the footer text change + a test. Accidental-quit safety is preserved by the existing two-press confirm. |
| Help overlay advertises dead keys | Filter `CORE_HELP_SECTIONS` to a mixer-relevant subset in the profile (Help Usage + DJ Mixer + core app keys); drop-in sections only from loaded drop-ins (already implicit — unloaded drop-ins never register). |
| Shift+D identity crisis | In hosted mode the toggle is a no-op + flash (§4). |
| Now-playing banner | Freebie: overlays stay alive and the mixer registers as a now-playing source, so the track banner still works in mixer mode. Verify, don't assume. |
| `get_audio_data()` on a never-started manager | Verify it returns silent data (not an exception) — if not, a tiny null-object or started-flag guard in `AudioManager`. |
| Context menu / right-click on main window | Visual-oriented; suppress in the profile (one gate) or leave — propose suppress. |
| Recording/streaming keys | App-level recorder records the visual output — skipped in profile; the mixer's own mix recording is unaffected. |

## 9) Phasing

- **P1 — core boot profile (core repo only; no dj-mixer changes).**
  `_boot_profile` resolution (config + `--mixer`), splash gate, audio-
  capture skip, effects/playlist guard, subsystem gating + `mixer_allow`,
  help filtering, loop branch that presents black until a hosted frame
  exists. *Standalone value:* even before P2, this boots in ~1s with the
  mixer in its **existing second window** (profile auto-opens it) — fully
  usable mixer-only sessions from day one.
- **P2 — hosted mode (dj-mixer repo + small core hook).** `MixerWindow`
  `hosted=True` (skip `SecondaryGLWindow`, expose the frame), controller
  claims the main window id, app presents the frame, Esc-Esc→quit,
  RESIZE forwarding. Coordinated with the mixer team.
- **P3 — branded entrypoint.** `unicorn-mix` console script + (optional)
  desktop file/icon.
- **P4 — polish.** Window title/icon per profile, help text pass,
  `mixer_allow` documentation in the configuration reference, measure
  boot with the profiler and record it here.

## 10) Future hook (out of scope, recorded so it isn't lost)

The owner's global **messaging/dispatch bus** idea (drop-in ↔ drop-in ↔
core, centralized) is the natural next abstraction: boot profiles then
become "who subscribes", and *if* a true two-process split is ever wanted,
the bus is the seam that makes it possible without today's fork costs.
Nothing in this plan should preclude it; nothing in this plan depends on
it.

## 11) Open questions for the owner

1. **Windowed or fullscreen console by default** in mixer mode? (Proposed:
   respect `[window]` config as-is; it currently defaults fullscreen —
   confirm that's what you want for a console.)
2. **APC in mixer mode** — keep it connected (harmless no-ops on visual
   actions) or skip MIDI devices other than the REV1? (Proposed: keep —
   MidiManager stays whole; zero special-casing.)
3. **`unicorn-mix` naming** for the entrypoint — bless it or bikeshed
   later? (P3 either way.)
4. **Shift+D no-op flash** vs. letting it hide/show the console over
   black? (Proposed: no-op + flash.)
