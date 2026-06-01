# Unicorn Viz — Fedora 44 Migration Prep

Owner: Engineering
Status: active — projectM resolved; path resolver pending
Last updated: 2026-06-01 (projectM installation complete)

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
| libprojectM 4       | 4.1.0 at /usr/local/lib64 | ✅     |

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
| spotipy                    | 2.26.0    | ✅ (installed this session) |
| requests                   | (system)  | ✅     |

³ pysdl2-dll ships its own SDL2 binaries; at runtime the app logs
  "Using SDL2 binaries from pysdl2-dll 2.32.0" and bypasses the system
  sdl2-compat entirely. SDL2-compat is therefore a non-issue for the venv path.

⁴ Required by `spotify-pro-01`. Installed this session: `.venv/bin/pip install spotipy`.

### 2.1 Worktree venv

**✅ RESOLVED this session.** The worktree `.venv` was created and fully populated:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt opencv-python-headless spotipy
```

All packages confirmed importing cleanly under Python 3.14.5.

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

### 4.1 libprojectM 4 — ✅ RESOLVED this session

**Status:** **Installed.** libprojectM 4.1.0 built from source and installed at
`/usr/local/lib64/`. All 5 required ctypes symbols verified present.
`drop-ins/projectm-01/install.sh` created to automate future installs.
Preset pack: 4,188 `.milk` files from `presets-projectm-classic` (LGPL 2.1)
installed locally at `drop-ins/projectm-01/presets/classic/` (gitignored).

**Build summary:**

```bash
# Automated by drop-ins/projectm-01/install.sh
# Build deps: cmake 4.3.0, gcc-c++, glm-devel, mesa-libGL-devel, mesa-libEGL-devel
# Source: https://github.com/projectM-visualizer/projectm.git (tag 4.1.0)
# cmake flags: -DCMAKE_BUILD_TYPE=Release -DENABLE_SDL=OFF -DENABLE_TESTING=OFF
#              -DCMAKE_INSTALL_PREFIX=/usr/local -DBUILD_SHARED_LIBS=ON
# Install: /usr/local/lib64/libprojectM-4.so.4.1.0
# ldconfig: /etc/ld.so.conf.d/local-lib64.conf (was missing, added)
```

**Verification:**

```
$ ldconfig -p | grep projectm
libprojectM-4.so.4 (libc6,x86-64) => /usr/local/lib64/libprojectM-4.so.4
libprojectM-4.so (libc6,x86-64) => /usr/local/lib64/libprojectM-4.so
...
$ python3 -c "import ctypes.util; print(ctypes.util.find_library('projectM-4'))"
libprojectM-4.so.4
```

**Note on v3 vs v4:** The projectm-01 Phase 1 implementation targets the
projectM **4** C API (`projectm_create_with_opengl_load_proc`). The v3 API
is different and will not work. On older Fedora (≤37) only v3 may have been
available in repos. This machine should use v4 built from source (now done).

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

**✅ RESOLVED this session.** All 20 submodules initialized and checked out to
their pinned SHAs. Several submodules had stale remote SHAs (commits not
reachable via normal `upload-pack`); resolved by adding git `alternates` files
pointing to the main repo's module object stores so local objects could be used
directly. `spotify-pro-01` was fetched normally from remote.

```bash
git submodule update --init --recursive  # most submodules
# cyber-war-01 and others: resolved via object store alternates
```

---

## 6. Asset Gaps

### 6.1 Fonts (F44-02 — still open)

| Asset                    | Present | Used by |
|--------------------------|---------|---------|
| `assets/fonts/font8x8.bin`  | ✅      | ANSI renderer (fallback) |
| `assets/fonts/font8x16.bin` | ✅ (added this session) | ANSI renderer (preferred) |
| `assets/fonts/ui-font.ttf`  | ✅ (added this session) | Overlays HUD (preferred) |

**✅ RESOLVED this session.**

- `font8x16.bin` (4096 bytes): Generated by merging `default8x16.psfu.gz` and
  `drdos8x16.psfu.gz` (both from `kbd-misc`) with a Python script that maps
  the full CP437 → Unicode table. Zero missing glyphs (all 256 CP437 code
  points covered).

- `ui-font.ttf`: Copied from
  `/usr/share/fonts/liberation-mono-fonts/LiberationMono-Regular.ttf`
  (SIL Open Font License 1.1 — freely bundlable). This is now the first
  candidate in the `overlays.py` font fallback chain.

- Also fixed: `overlays.py` fallback candidate #3 was `NotoSansMono-VF.ttf`
  but the actual filename on Fedora is `NotoSansMono[wght].ttf`. Corrected.

---

## 6b. Installer Coverage Audit

### tools/install/lib.sh — `uv_install_system_deps()`

**✅ FIXED this session.** The following gaps were identified and resolved:

| Gap | Severity | Resolution |
|-----|----------|------------|
| `portaudio-devel` missing from dnf block | Medium | Added to dnf and pacman blocks; apt equivalent (`portaudio19-dev`) added |
| `libsndfile-devel` missing from dnf block | Medium | Added to dnf and pacman blocks; apt equivalent (`libsndfile1-dev`) added |
| ffmpeg dnf fallback warning was outdated | Low | Updated with RPM Fusion install one-liner |

**Remaining notes:**
- `opencv-python-headless` and `spotipy` are pip-only (no system package);
  not appropriate for the system deps block — acceptable as-is.
- `psutil` is pure Python and installs cleanly via pip — no system package needed.
- The apt block had `libpipewire-0.3-dev` but Debian/Ubuntu packages may now
  name it differently on newer distros. This is a watch item, not blocking.

### Drop-in `install.sh` scripts

Each initialized drop-in was scanned for `install.sh`. All 20 drop-ins that
stage files do so correctly. None install additional system packages — this is
intentional: the main `tools/install_linux.sh` is responsible for system deps.

No changes needed to drop-in installers.

---

Items from `2026-05-26-fedora44-compat-audit.md`, updated:

| ID     | Severity | Title                                      | Status (2026-06-01) |
|--------|----------|--------------------------------------------|---------------------|
| F44-01 | High     | Resource path resolution fails outside CWD | Open — excluded from this session (separate task) |
| F44-02 | High     | Missing bundled font assets                | **Resolved** — font8x16.bin generated, ui-font.ttf bundled |
| F44-03 | High     | Multi-head placement compositor-dependent  | Open — known limitation, no compositor matrix tested |
| F44-04 | Medium   | Multi-head doc/arch drift                  | Open — legacy methods not yet cleaned |
| F44-05 | Medium   | ffmpeg availability                        | **Resolved** — ffmpeg 8.1.1 installed |
| F44-06 | Medium   | ALSA fallback hidden by skip policy        | Open — low priority; PipeWire works |

---

## 8. Priority Action List

### P0 — Blockers (can't do a clean demo run without these)

1. ✅ **Create `.venv` in this worktree** — Done this session.

2. ✅ **Initialize submodules** — All 20 submodules initialized to pinned SHAs.

### P1 — Major features currently disabled

3. **Push and initialize 9 missing drop-ins** — auto-vj-01, candy-frame-01,
   control-room-01, grand-finale-01, postfx-01, projectm-01, sims-01,
   spotify-pro-01, streaming-01. Content exists in f33 repo; needs a push
   to each drop-in's private GitHub repo then submodule init.
   **Note:** All 9 GitHub repos already exist and accept the f33 content
   (verified by SHA match). The 9 drop-ins cloned and initialized successfully
   in this worktree from those remotes.

4. ✅ **Install libprojectM 4** — Done this session. Built from source (4.1.0),
   installed to `/usr/local/lib64/`, ldconfig updated, ctypes verified.
   `drop-ins/projectm-01/install.sh` created to automate future installs.
   4,188 classic preset `.milk` files installed locally (gitignored).

5. ✅ **Install spotipy** — Done this session (`spotipy 2.26.0`).

### P2 — Quality / correctness

6. ✅ **Add `font8x16.bin`** — Done this session. 256-glyph CP437 8×16 binary
   generated from `default8x16.psfu.gz` + `drdos8x16.psfu.gz`.

7. ✅ **Add `ui-font.ttf`** — Done this session. LiberationMono-Regular.ttf
   (SIL OFL) bundled; overlays.py Noto path mismatch also corrected.

8. **F44-01 path resolution** — Implement app-root resolver so non-CWD launches
   work (menu shortcuts, packaged installs). *Excluded from this session.*

9. **Verify Wayland multi-head** on this machine's compositor against the
   matrix: GNOME Wayland single / span_all / mirror_all.

### P3 — Nice to have / future

10. ✅ **Installer coverage gaps fixed** — `tools/install/lib.sh` dnf/apt/pacman
    blocks now include `portaudio-devel`, `libsndfile-devel`; ffmpeg warning
    updated with RPM Fusion instructions.

11. **ALSA opt-in probe mode** (F44-06) — add `audio.allow_alsa = false`
    (default) config toggle for diagnostics.

12. **Compositor compat matrix doc** — formalize the tested display mode ×
    compositor combinations in `docs/configuration.md`.

13. ✅ **projectm-01 preset pack** — 4,188 `.milk` presets from
    `presets-projectm-classic` (LGPL 2.1) installed locally at
    `drop-ins/projectm-01/presets/classic/` (gitignored). Fetched
    automatically by `drop-ins/projectm-01/install.sh`.

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
