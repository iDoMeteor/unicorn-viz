# The patched free-threaded wheels: recipe and provenance

Owner: UV Threads (recording work of the upstream free-threading team)
Status: active
Last updated: 2026-10-02

Release `wheelhouse-cp314t-patched-2026-10-02` publishes patched cp314t wheels of
**python-rtmidi 1.5.8 (-3), glcontext 3.0.0 (-2), moderngl 5.12.0 (-2), sphn 0.2.1 (-1) and
opencv-python-headless 4.13.0.92 (-1)**, for Linux (manylinux_2_28) and Windows (win_amd64).
They differ from the unpatched wheels (`../build_ft_wheels.sh` and friends) in that their
modules **declare free-threading support**, so importing them leaves the GIL off, and they carry
fixes for races and leaks found while doing that audit. The fixes are offered upstream as pull
requests; the release notes list them.

**Credit.** The patches, the iDoMeteor forks and the original build scripts are the work of the
upstream free-threading team (their working directory is `~/Repos/python-free-threading`). They
were not reproducible from this repository: the Linux scripts read local clones with absolute
paths, and the Windows builds came from a private repository (`iDoMeteor/ft-wheels-ci`). This
directory brings the recipe into the repository. Nothing here was written by modifying the
upstream team's clones; files were copied from them and are marked below.

## What is here

| Path | What it is |
|---|---|
| `recipe.json` | **The pins**: per package, the fork URL, branch and full commit (and the RtMidi sub-module commit), the sdist hash, the OpenCV tag and commits, both patch files' sha256, build tags, and the manylinux image digests the wheels were built on. Tests tie it to everything below. |
| `patches/` | `opencv-4.13.0-free-threading.patch` (sha256 `1d19d901d66346bdadf5bd7df0ec0b1b60bdc14dfa582c6ae7878c5f613653f4`, the hash the release notes cite) and `sphn-0.2.1-gil-used-false.patch`. Copied verbatim. |
| `fetch_patched_sources.py` | Fetches the git packages' sources **by pinned commit** from the forks and verifies them (new; replaces the local clones). |
| `build_windows_patched_wheels.py` | The Windows build script (copied verbatim from the private repo). Pins its own sources; a test checks that it agrees with `recipe.json`. |
| `smoke/` | The smoke tests the patched wheels were verified with. They **enforce** that the GIL stays off after import (the unpatched `../ft_*_smoke.py` only report it). Copied verbatim, with the fixture clips. |
| `reference/` | As-built records, verbatim: the three build manifests (sources, hashes, image digests, tool versions), the build-tools listing, a **snapshot of the published release notes**, and the Actions workflow that ran the Windows script (reference only: it lives in a private repository and is **not** a workflow of this one). |
| `as-built/` | The original Linux scripts (`linux-scripts/`) and the two Windows Actions run records (`windows-runs/`), verbatim, for the record. The Linux scripts are **not runnable elsewhere** (local paths); use the `--patched` modes below. |

## Reproducing the Linux wheels

From a checkout of this repository, with rootless `podman`, `git` and `python3`:

    tools/packaging/build_ft_wheels.sh --patched         # python-rtmidi, glcontext, moderngl
    tools/packaging/build_ft_sphn_wheel.sh --patched     # sphn
    tools/packaging/build_ft_opencv_wheel.sh --patched   # opencv-python-headless (about an hour)

Each fetches or checks its sources against the pins, builds in the manylinux container, gives
the wheel its PEP 427 build tag (which is what makes pip prefer it over the unpatched wheel of
the same version), and with `--verify-python PATH` installs it into the bundled free-threaded
runtime and runs the enforcing smoke test. `build_ft_wheels.sh --patched` also writes
`patched-build-manifest.json` (fetched commits, image, wheel hashes).

## Reproducing the Windows wheels

They were built on GitHub Actions (`windows-2022`) by `build_windows_patched_wheels.py`,
dispatched from the private repository's workflow (`reference/windows-patched-wheels.yml`).
To rebuild from this repository you need a Windows runner with Visual Studio 2022's C++ tools,
Git and rustup, and then:

    python tools/packaging/ft-patched/build_windows_patched_wheels.py --out wheels-out --work work [--only NAMES] [--dry-run]

(`--dry-run` prints the whole plan and works anywhere.) Running it from Actions in *this*
repository needs a workflow here, which is the installer team's to add with the owner's approval.
Two real Windows runs of the script are recorded in `as-built/windows-runs/`.

## What is and is not reproducible

**Measured on 2026-10-02**, by rebuilding with the `--patched` modes on the pinned images and
comparing with the published wheels in the wheelhouse:

| Wheel (Linux) | Result |
|---|---|
| python-rtmidi 1.5.8-3, glcontext 3.0.0-2, moderngl 5.12.0-2 | **Every file inside the wheel is byte-identical**, including the compiled extensions and the vendored `libasound`. Only the zip entries' timestamps differ, so the wheel files' own sha256 differ. |
| sphn 0.2.1-1 | Same member list and the same size to the byte. Not identical: the ELF build-id (20 bytes), LLVM's generated `.llvm.<number>` suffixes on internal symbol names (about 400 bytes of 85.7 MB), and the SBOM's timestamp and UUID. Same code and the same compilers (rustc 1.98.1). |
| opencv-python-headless 4.13.0.92-1 | The patch applies cleanly to the pinned OpenCV tree, and the same `--patched` path builds it. **A full rebuild (about an hour) has not been compared yet.** |
| Windows (all five) | Not rebuilt from here. The script's pins were checked against GitHub and PyPI (`FT_WHEELS_ONLINE=1`), and the two real Actions runs are in `as-built/windows-runs/`. |

So the recipe reproduces the patched Linux wheels' **contents**; a rebuilt wheel will not have
the same file hash as the published one, so the **published hashes remain the trust anchor**
(`../wheelhouse-cp314t.sha256`), not a rebuild.

* **Pinned and verified:** every git source (by commit hash, verified after fetching), the
  sdist (by hash), the patches (by hash), Cython, the Rust and maturin versions, and the
  manylinux image (by digest; both digests were still pullable on 2026-10-02).
* **Not pinned:** distro packages installed in the build containers at build time (`yum`:
  ALSA and Mesa headers), PyPI build requirements other than the ones the scripts pin, the sphn
  toolchain image's base (`manylinux_2_28:latest` when it is first built), and the Windows runner
  image.
* **sphn** is built from the PyPI sdist plus a one-line patch, not from the fork commit the
  release notes also cite (that commit is the same change plus CI and tests).
* **OpenCV** is a modified-source build: the patch changes the Python bindings only.

## Tests

`tests/test_ft_patched_recipe.py` (the recipe agrees with the patch files, the release-notes
snapshot, the manifests, the Windows script's pin table and the installers' trust file),
`tests/test_ft_patched_fetch.py` (the fetch helper), `tests/test_ft_patched_windows_script.py`
(the upstream team's tests of the Windows script, adapted only in their root path; with
`FT_WHEELS_ONLINE=1` they also check every pinned branch and the sdist against GitHub and PyPI).
