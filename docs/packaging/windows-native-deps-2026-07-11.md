# Windows Native Dependency Build — Field Notes & Remediation Ideas

Owner: Studio
Status: Active reference
Last updated: 2026-07-11

This document records the exact sequence of problems and solutions encountered
when installing the full unicorn-viz dependency stack on a vanilla Windows
Python 3.14 environment (no Visual Studio, no MSVC toolchain) on 2026-07-11,
plus actionable ideas for removing these pain-points for future end users.

---

## Environment at the time

| Item | Value |
|---|---|
| OS | Windows 10/11 (x86-64) |
| Python | 3.14.6 (MSC v.1944 64-bit) from `pythoncore-3.14-64` |
| Virtual env | `.venv` at workspace root |
| Package managers | `winget` 1.29.280 (only); no `choco`, `scoop`, `conda` |
| Pre-installed C toolchain | None (no MSVC, no MinGW) |
| VLC | Not installed |

---

## Problem log

### 1. `python-rtmidi >= 1.5` — meson/no-compiler

**Symptom**

```
error: metadata-generation-failed
..\meson.build:1:0: ERROR: Unknown compiler(s): [['icl'],['cl'],['c++'],['g++'],['clang++'],['clang-cl']]
```

python-rtmidi 1.5.x switched its build system from setuptools to meson-python.
Meson always probes for a C++ compiler at configuration time. None was present.

**Fix applied**

1. Installed **LLVM 22.1.8** via winget (`LLVM.LLVM`) — provides `clang-cl` and
   `clang++` targeting the MSVC ABI (`x86_64-pc-windows-msvc`).
2. Clang was found but `meson compile` still failed:

   ```
   clang-22: error: no such file or directory: '/EHsc'
   ```

   Root cause: `rtmidi/meson.build` line 29 unconditionally adds `/EHsc` (an
   MSVC-only C++ exception flag) for any compiler that is not GCC:

   ```meson
   if meson.get_compiler('cpp').get_id() != 'gcc'
       defines += ['/EHsc']
   endif
   ```

   Clang in GNU/MinGW mode treats arguments starting with `/` as file paths,
   not compiler flags.

3. Installed **LLVM MinGW UCRT 22.1.8-20260616** via winget
   (`MartinStorsjo.LLVM-MinGW.UCRT`) — same LLVM version but re-targeting
   `x86_64-w64-windows-gnu`, bundling MinGW-w64 headers and the UCRT runtime.
   This clang knows `/EHsc` is a path, not a flag, but the build still fails
   for the same reason.

4. **Real fix:** downloaded the python-rtmidi 1.5.8 source tarball and patched
   `rtmidi/meson.build` to only emit `/EHsc` for actual MSVC:

   ```diff
   - if meson.get_compiler('cpp').get_id() != 'gcc'
   + if meson.get_compiler('cpp').get_id() == 'msvc'
       defines += ['/EHsc']
   endif
   ```

   Built with `pip install --no-build-isolation` after installing `meson`,
   `meson-python`, `ninja`, `cython` into the venv, with the LLVM MinGW `bin`
   and the venv `Scripts` prepended to `PATH`.

5. After a successful build the compiled `.pyd` could not be imported:

   ```
   ImportError: DLL load failed while importing _rtmidi: The specified module could not be found.
   ```

   The extension linked against `libc++.dll` and `libunwind.dll` from the LLVM
   MinGW runtime. Fix: copied both DLLs from the LLVM MinGW `bin` directory
   into `.venv\Lib\site-packages\rtmidi\` so they are co-located with the
   extension.

   **Note:** The same fix applies to any other MinGW-built extension in the
   venv. A scan of all `.pyd` files with `llvm-objdump --private-headers` will
   reveal which ones link against `libc++.dll` / `libunwind.dll`. At the time
   of writing, both `rtmidi\_rtmidi.cp314-win_amd64.pyd` and
   `moderngl\mgl.cp314-win_amd64.pyd` required the co-located DLLs.

---

### 2. `moderngl >= 5.10` — setuptools MSVC probe

**Symptom**

```
error: Microsoft Visual C++ 14.0 or greater is required.
Get it with "Microsoft C++ Build Tools"
```

`moderngl` depends on `glcontext` which has a small C extension (`glcontext.wgl`
and `glcontext.egl`) built via setuptools. Setuptools on Windows always probes
for MSVC through `_msvccompiler.py` first; if not found it falls back to MinGW
only when explicitly configured.

Setting `CC`/`CXX` environment variables has no effect — setuptools' Windows
code path ignores them.

**Fix applied**

Created `%USERPROFILE%\pydistutils.cfg` (the user-level distutils config file,
honoured by setuptools ≥ 60 on Python 3.12+):

```ini
[build]
compiler=mingw32
```

With the LLVM MinGW `bin` directory on `PATH` (providing `gcc.exe` and `g++.exe`
as wrappers for clang targeting MinGW), setuptools used the `Mingw32CCompiler`
class successfully and compiled both `glcontext` and `moderngl` cleanly.

---

### 3. `python-vlc` — VLC system library absent

**Symptom**

```
FileNotFoundError: Could not find module '…\libvlc.dll'
```

`python-vlc` is a thin ctypes wrapper; `libvlc.dll` ships with VLC Player, not
the Python package. VLC Player was not installed.

**Fix applied**

```
winget install VideoLAN.VLC --silent --accept-package-agreements --accept-source-agreements
```

---

## Final installed package state

All 19 declared packages installed and importable after the session:

| Package | Version | Notes |
|---|---|---|
| `moderngl` | 5.12.0 | Built from source with MinGW (`pydistutils.cfg`) |
| `PySDL2` | 0.9.17 | Wheel |
| `pysdl2-dll` | 2.32.10 | Wheel |
| `numpy` | 2.5.1 | Wheel (cp314) |
| `scipy` | 1.18.0 | Wheel (cp314) |
| `sounddevice` | 0.5.5 | Wheel |
| `python-rtmidi` | 1.5.8 | Built from patched source; DLLs co-located |
| `Pillow` | 12.3.0 | Wheel (cp314) |
| `psutil` | 7.2.2 | Wheel |
| `opencv-python-headless` | 5.0.0.93 | Wheel (cp311 abi3) |
| `soundfile` | 0.14.0 | Wheel |
| `python-osc` | 1.10.2 | Pure Python |
| `openai` | 2.45.0 | Pure Python |
| `anthropic` | 0.116.0 | Pure Python |
| `ably` | 3.1.2 | Pure Python |
| `av` | 18.0.0 | Wheel (cp311 abi3) |
| `python-vlc` | 3.0.21203 | ctypes wrapper; VLC Player 3.0.23 required |
| `mutagen` | 1.48.1 | Pure Python |
| `usd-core` | 26.5 | Wheel (cp311 abi3) |

Toolchain artefacts installed alongside (not Python packages):

- **LLVM 22.1.8** — `C:\Program Files\LLVM`
- **LLVM MinGW UCRT 22.1.8-20260616** —
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\MartinStorsjo.LLVM-MinGW.UCRT_…`
- **VLC Player 3.0.23** — system install

---

## Root causes summary

| Package | Why no pre-built wheel | Blocker |
|---|---|---|
| `python-rtmidi` | No cp314-win_amd64 wheel on PyPI; meson-python build | `/EHsc` flag hardcoded for non-GCC compilers; missing C++ runtime DLLs after build |
| `moderngl` / `glcontext` | No cp314-win_amd64 wheel on PyPI; setuptools C ext | setuptools ignores `CC`/`CXX` on Windows; MSVC not present |

All other packages either had pre-built cp314 or cp311-abi3 wheels, or are pure
Python.

---

## Ideas for streamlining — future roadmap

### Short-term: `tools/install/windows_deps.ps1`

A single PowerShell script that automates everything discovered in this session.
It would:

1. Check Python version and venv existence; bail with a clear message if missing.
2. Install LLVM MinGW via winget if no usable C++ compiler is detected.
3. Write `%USERPROFILE%\pydistutils.cfg` with `compiler=mingw32` if not already
   present.
4. Install VLC via winget if `libvlc.dll` is not found in `PATH` or standard
   install locations.
5. Download the python-rtmidi tarball, apply the `/EHsc` patch, build and
   install it with `--no-build-isolation`.
6. Copy `libc++.dll` and `libunwind.dll` from the LLVM MinGW bin into the
   rtmidi package directory.
7. Run `pip install -r requirements.txt` (skipping `python-rtmidi` since it was
   just installed).
8. Run `pip install -e .` (editable install of the main project).
9. Run `pip check` and import-smoke each package; report failures clearly.

This script can be invoked from `install.sh` or `README.md` with:
```powershell
Set-ExecutionPolicy -Scope Process Bypass; .\tools\install\windows_deps.ps1
```

### Medium-term: upstream fixes

Both native-build failures are upstream bugs or gaps:

1. **python-rtmidi** — the unconditional `/EHsc` flag on Windows should be
   guarded on `cpp.get_id() == 'msvc'`. File or PR against
   <https://github.com/SpotlightKid/python-rtmidi>. Once merged and released
   with a cp314 wheel, the whole patching dance is unnecessary.

2. **glcontext** / **moderngl** — maintainers can add cp314-win_amd64 wheels to
   their CI (GitHub Actions `windows-latest` + Python 3.14 matrix). Once those
   wheels exist, `pip install moderngl` will just work with no compiler at all.
   The moderngl project already has a solid wheel-building setup; they just need
   to extend the Python version matrix.

Contributing or sponsoring these wheels upstream is the highest-leverage fix.

### Medium-term: bundled LLVM MinGW in Windows installer

The Windows NSIS installer (`packaging/windows/UnicornViz.iss`) is currently
★1 (see [docs/planning/installers.md](../planning/installers.md)).  When it
reaches ★★★ (self-contained + curated payload), it should:

- Bundle a **portable copy** of LLVM MinGW UCRT (the `llvm-mingw-…-ucrt-x86_64`
  directory) inside the installer or as a CI-downloaded staging asset.
- Pre-build `python-rtmidi`, `moderngl`, and `glcontext` wheels in CI against
  the bundled Python version and ship those pre-built wheels inside the
  installer, so end users never trigger a source build at all.
- Ship `libc++.dll` / `libunwind.dll` alongside `_rtmidi.pyd` inside the
  bundled site-packages.

This means zero compiler required on the end-user machine for any supported
package.

### Medium-term: `unicorn-viz dropins install` command

The [installers plan](../planning/installers.md) §0 already calls for a
per-drop-in dependency manager. That command should:

- Accept a `--platform windows` flag.
- Know which packages need source builds on Windows and whether a patched
  pre-built wheel is available in a trusted release asset.
- Auto-detect whether a working C toolchain is present and either use it or
  install LLVM MinGW automatically.

### Long-term: `python-build-standalone` embedded runtime

The installers plan already mandates bundling `python-build-standalone` in every
packaged release. When that runtime is embedded:

- It will be a fixed Python version (e.g. 3.11) chosen by us, so we can
  pre-build **every** native wheel in CI for exactly that version and include
  them in the bundle — eliminating all source-build paths for end users
  completely.
- The `pydistutils.cfg` hack, the LLVM MinGW dependency, and the VLC winget
  install all become installer-level concerns rather than developer/user-facing
  ones.

This is the correct long-term answer. Until the installer reaches ★★★, the
`tools/install/windows_deps.ps1` script is the practical bridge.

### Notes on Python 3.14 specifically

Python 3.14 is very new (released 2025–2026). Several packages that build
native extensions have not yet published cp314-win_amd64 wheels to PyPI,
defaulting to source builds that expose the MSVC dependency. This situation will
improve over 6–12 months as package maintainers extend their CI matrices. By the
time the Windows installer reaches ★★★, most or all of these packages should
have official cp314 wheels available.

If the project moves to `python-build-standalone` for the embedded runtime and
pins to Python 3.11 or 3.12, this issue disappears entirely — those versions have
mature wheel ecosystems on Windows.
