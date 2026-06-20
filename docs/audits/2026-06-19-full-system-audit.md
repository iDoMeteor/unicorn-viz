# Unicorn Viz — Full System Audit (2026-06-19)

Owner: owner + Claude Sonnet 4.6 (master coordinator)
Status: Complete
Last updated: 2026-06-19

Scope: Delta audit since 2026-06-17 full-system audit + first-contact whole-system
orientation for incoming master coordinator. Covers all uncommitted changes, new
features (Auto VJ training controls, timestamped corpus filenames, training
packaging tool), governance updates, test regression, and strategic suggestions.

Prior audit: [2026-06-17-full-system-audit.md](2026-06-17-full-system-audit.md)

---

## 0) Executive Summary

| Area | Grade | One-line |
|------|-------|----------|
| Architecture & module boundaries | A | No regressions from prior audit. |
| Drop-in independence & fallbacks | A | All 22 submodules wired; no bare imports added. |
| **Test suite** | **C** | **1 red test: sync_corpus_from_logs path regression (see §2).** |
| Auto VJ training controls | A- | Clean implementation; minor inconsistency in badge guard (§3). |
| Training tooling & packaging | A- | Good scorecard auto-gen; timestamping breaks test (§2). |
| Governance & docs | A | CLAUDE.md + copilot-instructions.md sync'd; VJ Training section canonical. |
| Security | A | No new risks; no shell injection in new tooling. |
| Drop-in coverage | A | 22/22 submodules registered; all directories tracked. |

**Overall: A- for this delta; one P0 red test must be resolved before commit.**

---

## 1) What Changed Since 2026-06-17

Five change clusters in the working tree:

| File / Module | Change |
|---|---|
| `drop-ins/auto-vj-01` | New training controls: `training_badge()`, `handle_key()` for `T`-family, `HELP_ENTRIES` updated |
| `unicornviz/app.py` | HUD: `auto_vj_label` + `auto_vj_training_badge` fields added to both HUD tiers |
| `unicornviz/overlays.py` | `_auto_vj_status_label()` helper; injects badge into HUD line 1 |
| `tools/training/build_corpus.py` | `_timestamped_path()`: corpus output files now include UTC timestamp in filename |
| `tools/training/sync_corpus_from_logs.py` | Same timestamping applied to corpus output path |
| `tools/package_training_set.py` | New: interactive/CLI packaging tool, scorecard auto-gen, SESSION_TRAINING_LOG.md |
| `tests/test_auto_vj_training_controls.py` | New: 5 tests for training key dispatch + overlays badge label |
| `tests/test_hotkeys_behavior.py` | Added `register_key_handler` to mock `_VJApi`; new test for `Ctrl+T` dispatch |
| `config.toml` | `live_training_enabled = false`, `sequence_training_enabled = false` |
| `CLAUDE.md` + `.github/copilot-instructions.md` | Session Review Logging rewritten; VJ Training section added |

---

## 2) P0 BUG — Red Test: sync_corpus_from_logs Timestamp Regression

**Test:** `tests/test_training_sync_corpus.py::test_sync_corpus_from_logs_populates_rows_with_spotify_metadata`
**Status:** FAILING (1 red, 170 pass)

**Root cause:** `sync_corpus_from_logs.py` was updated to apply `_timestamped_path()`
to the corpus output path before writing. The test passes `--corpus corpus.jsonl` as
the output destination, but the tool now transforms it into `corpus-20260619T123456Z.jsonl`.
When the test then reads `corpus.jsonl`, the file does not exist → `FileNotFoundError`.

**Two valid fix approaches:**

A. **Update the test** to glob for the timestamped file instead of a fixed name.
   Acceptable when the timestamping is intentional and mandatory.

B. **Opt-out flag**: Add `--no-timestamp` or skip timestamping when the `--corpus`
   flag is explicitly provided by the user (treating explicit paths as authoritative).
   This is more ergonomic for scripted callers; interactive use gets timestamps.

The owner must decide which approach to use. Per CLAUDE.md regression discipline,
this red test must be resolved or explicitly deferred before committing.

---

## 3) Auto VJ Training Controls — Code Review

### 3.1 Feature completeness

Clean implementation overall:

- `training_badge()` returns `'*'` (both on), `'+'` (live only), `'='` (sequence
  only), `''` (both off) — well-chosen symbols with visual distinction.
- `handle_key()` at `SDLK_t` handles all four modifier combos correctly.
- `HELP_ENTRIES` has all four new shortcuts; these will appear in the H overlay.
- `overlays._auto_vj_status_label()` validates badge values (`{'*', '+', '='}`)
  before rendering; strips unexpected values safely.
- `tests/test_auto_vj_training_controls.py`: 5 focused tests, all green.
- `tests/test_hotkeys_behavior.py`: new dispatch test for `Ctrl+T` proves the
  hotkey pipeline routes to the registered Auto VJ handler.

### 3.2 Minor inconsistency: badge guard in app.py

In the **full HUD** path ([app.py:3046](../../unicornviz/app.py#L3046)), the badge
is fetched safely with `getattr(self._auto_vj, 'training_badge', None)` — guards
against the method not existing on an older drop-in version.

In the **minimal HUD** path ([app.py:3157](../../unicornviz/app.py#L3157)), it
calls `self._auto_vj.training_badge()` directly (only guarded by `is not None`).
If a future or older drop-in version omits `training_badge`, this path would raise
`AttributeError`.

Recommendation: use the same `getattr` guard in the minimal path for consistency:
```python
'auto_vj_training_badge': (
    getattr(self._auto_vj, 'training_badge', lambda: '')()
    if self._auto_vj is not None else ''
),
```
Low-risk P2; not a current failure since the method exists in the live drop-in.

### 3.3 Config: training disabled in config.toml

`live_training_enabled = false` and `sequence_training_enabled = false` in the
uncommitted `config.toml`. Per CLAUDE.md policy, training is now controlled via
hotkeys (`Ctrl+T` / `Alt+T`) rather than startup config, making the "off by
default" the correct operational default.

---

## 4) Training Tooling — Code Review

### 4.1 `tools/package_training_set.py` (new)

Well-structured interactive packaging tool. Highlights:

- `_bucket_name(index)` generates `a, b, ..., z, aa, ab, ...` — correct base-26
  lexicographic sequence; handles unlimited growth.
- `_write_scorecard()` computes row counts, time range, BPM stats, beat-lock %, 
  director activity, profile mix, and ratings (1-5). Matches CLAUDE.md requirements.
- `_append_session_log()` appends a one-liner to `SESSION_TRAINING_LOG.md` without
  overwriting prior entries.
- Moves *all* files from `logs/` (not just JSONL), consistent with the new
  CLAUDE.md packaging rule.
- Uses `pathlib.Path.mkdir(parents=True, exist_ok=True)` — safe for first-run.

**One concern:** `_write_scorecard()` calls `_safe_median(conf_values)` twice
(line 202 for the rating, line 233 for the display). No bug — `_safe_median` is
pure — but could be precomputed once.

**No tests for `package_training_set.py` yet.** CLAUDE.md regression discipline
requires tests for new runtime behavior. Packaging the training set is a
write-destructive operation (moves files); at minimum a smoke test that invokes
the script with `--no-prompt --set-name` against a temp directory would be valuable.

### 4.2 Timestamped corpus filenames

The same `_timestamped_path()` helper appears in both `build_corpus.py` and
`sync_corpus_from_logs.py` — a copy-paste duplication. If the timestamp format
ever changes, both files need updating. Low priority (P3), but the function belongs
in `training_lib.py` as a shared utility.

---

## 5) Drop-In & Submodule Audit

All 22 drop-ins have matching entries in `.gitmodules`:

```
alien-invasion-01, america-250-01, auto-vj-01, banner-01, candy-frame-01,
control-room-01, cyber-war-01, disco-ball-01, grand-finale-01, hacker-terminal-01,
images-01, multi-head-01, postfx-01, projectm-01, sims-01, spotify-01,
streaming-01, textures-01, tron-grid-01, unicorn-tears-01, videos-01, webcam-01
```

Note: `.git/modules/drop-ins/` contains `spotify-pro-01` (22nd entry) rather than
`spotify-01`. This appears to be a historical rename artifact. The working directory
is `drop-ins/spotify-01` and `.gitmodules` lists it as `spotify-01`; the internal
module cache name is cosmetic and does not affect operation. No action needed.

Drop-in independence rules — no new violations found:

- No bare `drop-ins/*` imports introduced in the new code.
- Auto VJ badge access via `getattr` in the primary path; `VJApi.register_key_handler`
  used for hotkey delegation.
- `tests/test_dropin_boundary.py` still green.

---

## 6) Hotkey / Help Coverage

New keys added this cycle (all correctly documented):

| Key | Action | Help entry |
|-----|--------|------------|
| `Ctrl+T` | Turn both trainers on | ✅ HELP_ENTRIES |
| `Alt+T` | Turn both trainers off | ✅ HELP_ENTRIES |
| `Ctrl+Shift+T` | Toggle live training | ✅ HELP_ENTRIES |
| `Alt+Shift+T` | Toggle sequence training | ✅ HELP_ENTRIES |

Soft parity audit (`test_hotkey_help_audit.py`) emits 16 undocumented hotkey
warnings — same set as post-2026-06-18. No regressions. No new Easter-egg keys
added without annotation.

---

## 7) Governance & Documentation

CLAUDE.md and `.github/copilot-instructions.md` are now in sync on VJ Training.
The CLAUDE.md update:
- Removed the per-session append requirement for agents (moved responsibility to the
  separate training repository).
- Added VJ Training section with scorecard requirements, packaging rules, and
  immutability rules for runs.

All new docs/tools are consistent with the canonical governance section.

---

## 8) Prioritized Remediation

### P0 — Must fix before commit
1. **Resolve red test** `test_sync_corpus_from_logs_populates_rows_with_spotify_metadata`
   (§2) — choose fix approach A (update test to glob timestamped file) or B (opt-out
   when `--corpus` is explicit), confirm with owner.

### P1 — Fix soon
2. **Tests for `tools/package_training_set.py`** — write-destructive script with
   no test coverage (§4.1). Add a smoke test against a temp directory.
3. **Consistent `getattr` badge guard** in minimal-HUD path of `app.py` (§3.2).

### P2 — Clean up
4. **Deduplicate `_timestamped_path()`** — extract to `training_lib.py` (§4.2).
5. **Precompute `_safe_median(conf_values)`** in `_write_scorecard()` — cosmetic
   but avoids calling it twice.

### P3 — Track
6. `spotify-pro-01` internal module cache name vs `spotify-01` dir name (§5) —
   log and ignore unless a submodule operation misbehaves.

---

## 9) Deferred Items from Prior Audit (Status)

| Item | Status |
|---|---|
| Compositor dedup / `_present_back` refactor (DW-001 style cleanup) | Still open; tracked at docs/planning/compositor-dedup-implementation-plan-2026-06-18.md |
| Frame-budget CI guard | Still deferred (requires headless GL) |
| Full hotkey/help hard enforcement | Soft audit in place; hard enforcement deferred |
| Null-contract conformance tests | Done (135 tests) |
| P1: Analysis thread (double-buffer publish) | Done (2026-06-18) |
| P1: PBO async streaming readback | Done (2026-06-18); Fedora 44 fallback hardened |

---

## 10) Strategic Suggestions

### 10.1 New Drop-In Ideas

**High value / strong fit:**

- **`audio-out-01`** — Audio playback/injection drop-in (see §11 for full design).
  This directly addresses the owner's audio injection question.
- **`lyrics-01`** — Lyrics overlay via Spotify's lyrics endpoint, synchronized to
  playback position. Requires an additional Spotify API scope; pairs well with the
  existing Spotify drop-in. Spectacular live performance feature.
- **`color-grade-01`** — Post-processing LUT/color-grade overlay applied as a final
  compositing pass. Allows global tone/temperature shifts independent of per-effect
  shaders. Add to the post-FX chain.
- **`beat-flash-01`** — Strobe/flash effect drop-in with BPM-locked flash patterns,
  intensity control, and safety governor (frame-rate limiter to avoid epilepsy risk).
  Distinct from grand-finale; designed for sustained use.

**Interesting stretch goals:**

- **`ai-prompter-01`** — LLM-driven on-screen text (dynamic set title cards, crowd
  interaction prompts, AI-generated lyrics/mood labels). Uses local Ollama or Claude
  API; offline-first with API as fallback.
- **`tts-announce-01`** — Text-to-speech announcements (track names, DJ shoutouts)
  played through `audio-out-01`. Pairs with Spotify now-playing data.
- **`scene-score-01`** — Musical score display: shows current measure/bar count,
  beat position, and downbeat markers relative to detected BPM. Useful for DJ
  performance feedback.

### 10.2 Core Improvements

- **Effect parameter OSC bridge**: expose effect tweakables via OSC (Open Sound
  Control) so external tools (TouchOSC, Max/MSP, Ableton) can drive parameters.
  Lightweight: add an optional `python-osc` listener in a daemon thread.
- **Shader hot-reload**: watch `unicornviz/effects/*.py` for changes and reload
  the active effect's shader without restarting the app. Essential for live
  shader coding / demoscene performance.
- **Training replay mode**: load a packaged training set and replay the VJ director
  decisions for review/validation without live audio. Useful for offline corpus QA.

---

## 11) Audio Injection — Can We Do It?

**Short answer: yes, on PipeWire/Fedora this is straightforward.**

### 11.1 How PipeWire works here

On PipeWire (the default audio server on Fedora 34+), every audio node that writes
to the default output sink also has a corresponding **monitor source**. OBS
captures desktop audio via that monitor source — it hears everything that goes to
the speakers. So if Python outputs audio to the default PipeWire sink, OBS and the
speakers both pick it up automatically with no extra routing.

### 11.2 Minimal implementation

Since `sounddevice` is already in `requirements.txt`, the minimum viable audio
injection is a single `sounddevice.OutputStream`:

```python
import sounddevice as sd
import numpy as np

# Open output stream (default device → speakers + OBS monitor)
out_stream = sd.OutputStream(
    samplerate=48000,
    channels=2,
    dtype='float32',
    blocksize=1024,
)
out_stream.start()

# Inject a buffer
samples = np.zeros((1024, 2), dtype=np.float32)
out_stream.write(samples)
```

This creates a new PipeWire audio node. PipeWire mixes it into the default sink.
Speakers hear it. OBS captures the monitor source. Done.

### 11.3 Recommended drop-in design: `audio-out-01`

```
drop-ins/audio-out-01/
  audio_out.py          # AudioOutController — manages OutputStream + clip queue
  clips/                # WAV/FLAC audio clips (beat drops, jingles, SFX)
```

Key capabilities:

- **Clip playback**: hotkey-triggered playback of pre-loaded WAV/FLAC clips
  (e.g., air horn, drop FX, crowd samples).
- **BPM-quantized scheduling**: play a clip on the next beat or bar boundary
  (uses `auto-vj-01`'s BPM lock via VJApi).
- **Volume control**: master output volume, per-clip gain.
- **Fade-out**: graceful fade on stop so there's no click.

Implementation notes:

- Open one persistent `sounddevice.OutputStream` at startup; write silence when idle.
- Use a `threading.Thread` + queue to hand off clip buffers without blocking the
  main render loop.
- Clips are loaded into `numpy` float32 arrays at startup (no blocking I/O in the
  hot path — CLAUDE.md rule).
- Respect the `sounddevice` device selection from `config.toml [audio]` so the
  user can route to a virtual sink if desired.

### 11.4 Advanced: PipeWire virtual combined sink

For total routing flexibility (e.g., inject to a VJ mix bus that goes to a
separate hardware output than the speakers), use a PipeWire null sink:

```bash
pactl load-module module-null-sink \
  media.class=Audio/Sink \
  sink_name=unicornviz_inject \
  sink_properties='node.description=Unicorn\ Viz\ Inject'
pw-loopback --capture-props='node.name=unicornviz_inject' \
            --playback-props='node.name=alsa_output.default'
```

Then set `sounddevice` to target `unicornviz_inject`. OBS monitors the
`unicornviz_inject.monitor` source. This is useful for routing injection-only audio
to OBS without it going to the speakers, or for multi-room setups.

This complexity is probably overkill for most use cases; the default-sink approach
in §11.2 covers the stated goal (picked up by OBS + speakers/headphones).

---

## Session Log

- Date: 2026-06-19
- Reviewer: Claude Sonnet 4.6 (master coordinator, first contact)
- Scope: Delta audit vs. 2026-06-17; full drop-in/submodule count; new feature
  review (training controls, corpus timestamps, packaging tool); red test analysis;
  strategic suggestions; audio injection feasibility.
- P0: 1 red test (§2) — must be resolved before committing current working tree.
- P1: Add tests for `package_training_set.py`; fix badge guard inconsistency.
- P2: Deduplicate `_timestamped_path()`.
- No security defects found in new code.
- Audio injection via `sounddevice.OutputStream` is viable; `audio-out-01` drop-in
  design detailed in §11.
