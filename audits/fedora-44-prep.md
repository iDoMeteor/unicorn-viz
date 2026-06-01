# Unicorn Viz — Fedora 44 Migration Prep

Owner: Engineering
Status: active
Last updated: 2026-06-01

Scope: Full system and codebase review against the Fedora 44 dev machine.
Covers Python environment, system libraries, drop-in submodule status, known
compatibility risks, and a prioritized action list.

This document supersedes the earlier `2026-05-26-fedora44-compat-audit.md`
from the f33 development branch. That audit identified issues; this document
reflects the current machine state as of the worktree migration and adds
actionable detail for each item.

---

## 1. Machine Snapshot

| Component           | Installed Version         | Status |
|---------------------|---------------------------|--------|
| OS                  | Fedora 44 (fc44.x86_64)   | ✅     |
| Kernel              | 7.0.10-201.fc44.x86_64    | ✅     |
| Python (system)     | 3.14.5                    | ✅ ¹   |
| Mesa / OpenGL       | 26.0.7                    | ✅     |
| libglvnd            | 1.7.0                     | ✅     |
| PipeWire            | 1.6.6 + pipewire-pulseaudio | ✅   |
| ALSA lib            | 1.2.15.3                  | ✅     |
| PortAudio           | 19.7.0                    | ✅     |
| libsndfile          | 1.2.2                     | ✅     |
| ffmpeg              | 8.1.1-1.fc44              | ✅     |
| SDL (system)        | sdl2-compat 2.32.68 (SDL3-backed) | ⚠️ ² |
| libprojectM 4       | not installed             | ❌     |

¹ Project requires Python ≥ 3.11; 3.14 works, see §3.1 below.
² SDL2-compat is a compatibility shim over SDL3; see §3.2 below.

---

## 2. Python venv Status

The active venv lives at `/home/jj/Repos/unicorn-viz/.venv` (Python 3.14.5).
**All packages import cleanly and were manually verified on this machine.**

| Package                    | Version   | Status |
|----------------------------|-----------|--------|
| moderngl                   | 5.12.0    | ✅     |
| pysdl2                     | 0.9.17    | ✅     |
| pysdl2-dll                 | 2.32.0    | ✅ ³   |
| numpy                      | 2.4.4     | ✅     |
| scipy                      | 1.17.1    | ✅     |
| sounddevice                | 0.5.5     | ✅     |
| python-rtmidi              | 1.5.8     | ✅     |
| Pillow                     | 12.2.0    | ✅     |
| psutil                     | 7.2.2     | ✅     |
| opencv-python-headless     | 4.13.0.92 | ✅     |
| spotipy                    | not installed | ❌ ⁴ |
| requests                   | (system)  | ✅     |

³ pysdl2-dll ships its own SDL2 binaries; at runtime the app logs
  "Using SDL2 binaries from pysdl2-dll 2.32.0" and bypasses the system
  sdl2-compat entirely. SDL2-compat is therefore a non-issue for the venv path.

⁴ Required by `spotify-pro-01`. Install: `.venv/bin/pip install spotipy`.

### 2.1 Worktree venv

The worktree `agents-full-system-review-fedora-44` **has no `.venv`**.
The `run.sh` launcher will fail with an immediate error.

**Fix:** Create and populate the worktree venv:

```bash
cd /home/jj/Repos/unicorn-viz.worktrees/agents-full-system-review-fedora-44
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# For webcam support:
.venv/bin/pip install opencv-python-headless
# For spotify-pro-01:
.venv/bin/pip install spotipy
```

---

## 3. Fedora 44 Compatibility Notes

### 3.1 Python 3.14 — No Blocking Issues Found

Python 3.14 introduced no breaking changes for this codebase.
All `from __future__ import annotations` guards are in place.
`tomllib` is stdlib (added 3.11). `match`/`case` syntax works.
The venv packages were compiled against 3.14 and import correctly.

**Watch item:** Python 3.14 deprecated some internal C-API paths used by
older C extension wheels. The installed packages (numpy 2.4, scipy 1.17,
moderngl 5.12, sounddevice 0.5, rtmidi 1.5) are all recent enough to be
3.14-clean. If any package is downgraded or re-pinned, re-verify import.

### 3.2 SDL2-compat (SDL3-backed SDL2 shim)

Fedora 44 ships SDL3 as primary and provides `sdl2-compat-2.32.68` as a
backward-compat shim. **This does not affect the app** because `pysdl2-dll`
bundles its own SDL2 shared library (2.32.0) which is used at runtime.
No system SDL2 path is loaded.

If someone removes `pysdl2-dll` from the venv and relies on the system
library, sdl2-compat should still work for basic usage, but multi-head
window placement and Wayland EGL behavior may differ vs. native SDL2.

**Recommendation:** Keep `pysdl2-dll` in requirements.txt. Do not rely on the
system SDL2-compat for correctness.

### 3.3 PipeWire 1.6.6 — Verified Compatible

`sounddevice` on this machine correctly enumerates PipeWire devices via the
PulseAudio compatibility layer. The capture code in `unicornviz/audio/capture.py`
deliberately skips raw ALSA hostapi devices and targets PulseAudio/PipeWire —
this is the right path on Fedora 44.

No changes required. ALSA fallback opt-in (F44-06 from previous audit) remains
a future quality-of-life item, not a blocker.

### 3.4 Mesa 26.0.7 — OpenGL 3.3 Core Fully Supported

Mesa 26 supports OpenGL 4.6. All effects use `#version 330` shaders.
No compat issues expected.

### 3.5 ffmpeg 8.1.1 — Already Installed

ffmpeg is present (RPM Fusion). Recording and streaming pipelines should work.
The F44-05 concern from the previous audit ("ffmpeg may be unavailable") is
resolved on this machine. The runtime preflight should confirm the binary is
found before recording/streaming starts — that behavior exists in `recording.py`.

### 3.6 Wayland Multi-Head Placement (F44-03 — still open)

Multi-head (`span_all`, `mirror_all`) under GNOME Wayland remains
compositor-dependent for window placement. The existing X11 fallback behavior
and the operator warning guidance from F44-03 still apply. This is a known
limitation, not a regression from the Fedora 44 move.

**Mitigation:** Document the `window.force_x11_for_multihead` config knob
once implemented (see §6 action items), and test on the compositor matrix
from the previous audit.

---

## 4. Missing System Libraries

### 4.1 libprojectM 4 — CRITICAL for projectm-01

**Status:** Not installed. No Fedora 44 RPM exists in standard or RPM Fusion
repos (as of 2026-06-01).

**Effect:** `projectm-01` drop-in falls back to its internal shader (the
swirling palette fallback defined in `projectm_effect.py`). The app
continues running; no crash. But MilkDrop preset playback is completely
disabled.

**Install path (build from source):**

```bash
# Install build dependencies
sudo dnf install -y cmake gcc-c++ glm-devel mesa-libGL-devel \
    mesa-libEGL-devel libGL-devel llvm-devel

# Clone and build projectM 4
git clone --recurse-submodules https://github.com/projectM-visualizer/projectm.git
cd projectm
mkdir build && cd build
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DENABLE_SDL=OFF \
    -DENABLE_TESTING=OFF \
    -DCMAKE_INSTALL_PREFIX=/usr/local
make -j$(nproc)
sudo make install
sudo ldconfig
```

After install, verify: `ldconfig -p | grep projectM`

The drop-in looks for `libprojectM-4.so` or `libprojectM.so` automatically.
Use `projectm_library` config key for a non-standard path.

**Note on v3 vs v4:** The projectm-01 Phase 1 implementation targets the
projectM **4** C API (`projectm_create_with_opengl_load_proc`). The v3 API
is different and will not work. On older Fedora (≤37) only v3 may have been
available in repos. This machine should use v4 built from source.

---

## 5. Drop-in Submodule Status

### 5.1 Main repo (`unicorn-viz`)

Run from `/home/jj/Repos/unicorn-viz`:

| Drop-in             | Submodule Initialized | Notes |
|---------------------|-----------------------|-------|
| alien-invasion-01   | ✅                    |       |
| cyber-war-01        | ✅                    |       |
| disco-ball-01       | ✅                    |       |
| hacker-terminal-01  | ✅                    |       |
| images-01           | ✅                    |       |
| multi-head-01       | ✅                    |       |
| textures-01         | ✅                    |       |
| tron-grid-01        | ✅                    |       |
| unicorn-tears-01    | ✅                    |       |
| videos-01           | ✅                    |       |
| webcam-01           | ✅                    |       |
| auto-vj-01          | ❌ empty              | Content in f33 repo; push to remote needed |
| candy-frame-01      | ❌ empty              | Content in f33 repo; push to remote needed |
| control-room-01     | ❌ empty              | Content in f33 repo; push to remote needed |
| grand-finale-01     | ❌ empty              | Content in f33 repo; push to remote needed |
| postfx-01           | ❌ empty              | Content in f33 repo; push to remote needed |
| projectm-01         | ❌ empty              | Content in f33 repo; push to remote needed |
| sims-01             | ❌ empty              | Content in f33 repo; push to remote needed |
| spotify-pro-01      | ❌ empty              | Content in f33 repo; push to remote needed |
| streaming-01        | ❌ empty              | Content in f33 repo; push to remote needed |

All 9 uninitialized drop-ins have content in `/home/jj/Repos/unicorn-viz-f33/drop-ins/`
and need to be:
1. Committed and pushed to their respective private GitHub repos.
2. Initialized in the main repo with `git submodule update --init drop-ins/<name>`.

### 5.2 Worktree (`agents-full-system-review-fedora-44`)

**All 20 submodules are uninitialized** in this worktree. To run the full
system in this branch:

```bash
cd /home/jj/Repos/unicorn-viz.worktrees/agents-full-system-review-fedora-44
git submodule update --init --recursive
```

Note: Submodules that haven't been pushed to GitHub yet (the 9 listed above)
will fail. Initialize only the ones with remote content, or push them first.

---

## 6. Asset Gaps

### 6.1 Fonts (F44-02 — still open)

| Asset                    | Present | Used by |
|--------------------------|---------|---------|
| `assets/fonts/font8x8.bin`  | ✅      | ANSI renderer (fallback) |
| `assets/fonts/font8x16.bin` | ❌      | ANSI renderer (preferred) |
| `assets/fonts/ui-font.ttf`  | ❌      | Overlays HUD (preferred) |

Both the main repo and this worktree have the same gap: only `font8x8.bin`.

**Fix options:**
- `font8x16.bin`: Extract a CP437 8×16 VGA font from the public domain
  (e.g., from the BIOS or from the `vgabios` package: `rpm2cpio vgabios*.rpm | cpio -i`).
  Alternative: use `tools/` to convert from `.psf` font via `pyftsubset`.
- `ui-font.ttf`: Bundle a freely-licensed monospace TTF (e.g., JetBrains Mono,
  Source Code Pro, or Inconsolata).

Until resolved, ANSI rendering uses 8×8 (coarser glyphs) and the HUD uses a
system font fallback.

---

## 7. Open Items from Previous Fedora 44 Audit

Items from `2026-05-26-fedora44-compat-audit.md`, updated:

| ID     | Severity | Title                                      | Status (2026-06-01) |
|--------|----------|--------------------------------------------|---------------------|
| F44-01 | High     | Resource path resolution fails outside CWD | Open — resolver not yet implemented |
| F44-02 | High     | Missing bundled font assets                | Open — only font8x8.bin present |
| F44-03 | High     | Multi-head placement compositor-dependent  | Open — known limitation, no compositor matrix tested |
| F44-04 | Medium   | Multi-head doc/arch drift                  | Open — legacy methods not yet cleaned |
| F44-05 | Medium   | ffmpeg availability                        | **Resolved** — ffmpeg 8.1.1 installed |
| F44-06 | Medium   | ALSA fallback hidden by skip policy        | Open — low priority; PipeWire works |

---

## 8. Priority Action List

### P0 — Blockers (can't do a clean demo run without these)

1. **Create `.venv` in this worktree** — `run.sh` will error immediately without it.
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/pip install opencv-python-headless  # webcam support
   ```

2. **Initialize submodules** — At minimum the ones with remote content:
   ```bash
   git submodule update --init drop-ins/alien-invasion-01 \
       drop-ins/cyber-war-01 drop-ins/disco-ball-01 \
       drop-ins/hacker-terminal-01 drop-ins/images-01 \
       drop-ins/multi-head-01 drop-ins/textures-01 \
       drop-ins/tron-grid-01 drop-ins/unicorn-tears-01 \
       drop-ins/videos-01 drop-ins/webcam-01
   ```

### P1 — Major features currently disabled

3. **Push and initialize 9 missing drop-ins** — auto-vj-01, candy-frame-01,
   control-room-01, grand-finale-01, postfx-01, projectm-01, sims-01,
   spotify-pro-01, streaming-01. Content exists in f33 repo; needs a push
   to each drop-in's private GitHub repo then submodule init.

4. **Install libprojectM 4** — Build from source (instructions in §4.1).
   The projectm-01 effect is already written and handles absence gracefully,
   but MilkDrop playback requires the native library.

5. **Install spotipy** for spotify-pro-01:
   ```bash
   .venv/bin/pip install spotipy
   ```

### P2 — Quality / correctness

6. **Add `font8x16.bin`** to `assets/fonts/` — ANSI art quality improvement.

7. **Add `ui-font.ttf`** to `assets/fonts/` — HUD rendering quality improvement.

8. **F44-01 path resolution** — Implement app-root resolver so non-CWD launches
   work (menu shortcuts, packaged installs).

9. **Verify Wayland multi-head** on this machine's compositor against the
   matrix: GNOME Wayland single / span_all / mirror_all.

### P3 — Nice to have / future

10. **ALSA opt-in probe mode** (F44-06) — add `audio.allow_alsa = false` (default)
    config toggle for diagnostics.

11. **Compositor compat matrix doc** — formalize the tested display mode ×
    compositor combinations in `docs/configuration.md`.

12. **projectm-01 preset pack** — Populate `drop-ins/projectm-01/presets/` with
    sample `.milk` presets for first-launch experience.

---

## 9. Quick Launch Verification Checklist

Once P0 and P1 items are addressed:

```bash
# 1. Smoke test — headless arg parse
cd /home/jj/Repos/unicorn-viz.worktrees/agents-full-system-review-fedora-44
.venv/bin/python -m unicornviz --help

# 2. Audio device probe
.venv/bin/python -c "import sounddevice as sd; print(sd.query_devices())"

# 3. Full launch (Wayland)
./run.sh --start-effect "Audio Spectrum" --log-level DEBUG 2>&1 | head -50

# 4. projectM launch check (after libprojectM install)
./run.sh --start-effect "ProjectM"

# 5. Recording test
./run.sh --record --record-audio --effect-duration 5 --start-effect Plasma
```

---

## 10. Notes on unicorn-viz-f33 Backup Repo

`/home/jj/Repos/unicorn-viz-f33` contains the Fedora 37 development state.
It has content for the 9 uninitialized drop-ins and slightly older versions
of the initialized ones. Treat it as a read-only reference for the migration —
do not develop in it. Once all drop-in content is pushed to their respective
private repos, this backup can be archived.
