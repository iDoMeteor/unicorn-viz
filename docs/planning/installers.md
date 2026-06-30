# Unicorn Viz — Cross-Platform Installer Plan

**Owner:** Solo maintainer (one-person studio)
**Status:** Active — driving toward five gold-star installers
**Last updated:** 2026-06-30
**Canonical release repo:** https://github.com/djunicorntears/unicorn-viz
**Dev repo (not user-facing):** https://github.com/iDoMeteor/unicorn-viz

**Documentation pipeline planning:** `docs/planning/documentation-cicd-pipeline-plan.md`

> **Read this first:** §0.5 defines what "gold star" means and scores every
> channel against today's code. §16 is the authoritative, solo-friendly,
> free-tooling phased roadmap that supersedes the original §14 milestone
> sketch. §17 is the money ledger (what is free vs. what costs).

---

## 0. Decisions Locked In (2026-05-22)

- **Domain:** `unicornviz.io` will be hooked up; `get.unicornviz.io` →
  raw `install.sh` on the canonical repo. A second domain is planned (TBD).
- **GitHub CLI automation** for the canonical org is **blocked** on being
  logged in as the wrong user locally; defer any `gh` operations against
  `djunicorntears/*` until the right account is active.
- **Code-signing publisher name:** `Unicorn Viz`.
- **Snap Store + Flathub handles:** both names need to be **claimed**; not
  yet reserved. Treat as an owner action item before M5/M6.
- **Embedded Python:** bundle `python-build-standalone` on **every** Linux
  package and the Windows + macOS installers — uniform runtime, no system
  Python dependency anywhere.
- **Release tarball:** **core only.** Official drop-in submodules are
  packaged separately per channel (see §6) and are installed alongside core.
- **Per-drop-in dependency manager:** required — see §6. Drop-ins that add
  Python or system deps beyond the core set must ship a manifest and be
  resolvable by a single `unicorn-viz dropins install` command.
- **macOS signing/notarization:** deferred to post-launch ("after we ship
  and make some money"). v1 ships an **unsigned** `.dmg` with Gatekeeper
  workaround instructions in the README.
- **macOS minimum version:** open — recommendation stands at macOS 12
  (Monterey).
- **Homebrew tap repo name:** `djunicorntears/homebrew-unicornviz`
  (Homebrew convention: the GitHub repo must be named `homebrew-<tap>`, and
  users type `brew tap djunicorntears/unicornviz`). See §11.
- **Mobile (Android/iOS):** **not** in v1 scope.

## 0.5 Gold-Star Bar & Honest Scorecard (2026-06-21)

"Five gold-star installers for all platforms" needs a definition we can grade
against, otherwise it is a vibe. Here is the rubric. Each channel earns stars
**cumulatively** — you cannot claim ★4 until ★1–★3 hold.

### 0.5.1 The rubric (applies to every channel)

| Stars | Bar | What it proves |
|-------|-----|----------------|
| ★ | **Exists & builds.** A repeatable command/CI job produces the artifact. | We can ship *something*. |
| ★★ | **Works clean-room.** Installs on a fresh machine with **no dev tools**, app launches, and a menu / Start-menu / Dock entry with our unicorn icon appears. | A real first-time user succeeds. |
| ★★★ | **Self-contained & tidy.** Bundles its own Python runtime (`python-build-standalone`), pollutes no system interpreter, ships a **curated payload** (no `.git`/`.venv`/`logs`/`recordings`/dev scratch), preserves the user's `config.toml` on upgrade, and uninstalls cleanly. | It behaves like a real product, not a clone. |
| ★★★★ | **Automated & verified.** Built on tag in CI, checksums published, and a **nightly clean-container/VM install smoke** asserts `unicorn-viz --help` works. No human in the build loop. | Releases are boring and trustworthy. |
| ★★★★★ | **Trusted & discoverable.** Signed/notarized **or** shipped with a documented, low-friction trust path where signing costs money; published to the platform's native channel (vanity URL / Flathub / Snap Store / Homebrew); README badge + install docs live. | Strangers install it without fear or instructions. |

**Solo-dev escape hatch for ★5:** code-signing certs and notarization cost real
money (see §17). A channel may bank ★5 with an **unsigned artifact** *provided*
the trust path is one documented, copy-pasteable step (e.g. macOS right-click-open
+ `xattr` one-liner) and the signing step is already wired in CI behind a secret
gate (per §10) so flipping it on is a one-day job the day a cert lands. This keeps
"no paying for anything" from blocking the gold star.

### 0.5.2 Where each channel stands today

Graded against the actual code in this repo on 2026-06-21, not against intent.

| Channel | Today | Gap to next star |
|---|---|---|
| **Linux one-liner** (`install.sh` + `tools/install/lib.sh`) | ★★★★ (clone path) | **Done:** bundles `python-build-standalone` via `tools/packaging/fetch_runtime.sh` (no system `python3` needed); full canonical `.desktop` (§7); `set -Eeuo pipefail` + `ERR` trap; `uv_sudo` for root containers; shellcheck gate; **nightly real clean-container install smoke** (ubuntu/fedora/arch) asserting `unicorn-viz --help`. **Remaining:** validate the **release path** (tag → tarball → checksum) against a real release; icon size ladder. **★5:** GPG-sign `SHA256SUMS` + `install.sh.asc`, wire `get.unicornviz.io`. |
| **Native `.deb` / `.rpm`** (`tools/packaging/build_native.sh`) | ★★★ (climbing) | **Done 2026-06-30:** reworked to stage via `stage_payload.sh` (**drop-ins now stripped**), bundle a relocatable `fetch_runtime.sh` interpreter with shebangs rewritten to `/opt` (verified: 0 staging-path leaks), install only core deps into it, ship `unicornviz/`+`assets/` as siblings so `APP_ROOT` resolves and **assets are found** (fixed a real bug — see progress log), `postinst`/`postrm` cache refresh, MIT + C-lib-only deps. A real `.rpm` builds + inspects clean. **Remaining for ★4:** distro matrix + nightly `apt/dnf install ./pkg` smoke; **the `config.toml` conffile is intentionally deferred** pending distribution cleanup of config. **★5:** `dpkg-sig` / `rpm --addsign` with the release GPG key. |
| **Windows `.exe`** (`packaging/windows/UnicornViz.iss`) | ★ | Replace the blanket `RepoRoot\*` copy + postinstall network pip (the exact anti-pattern §8 kills) with a curated payload + embedded Python 3.11 + bundled ffmpeg; real Start-menu/desktop/PATH; version from CI not hardcoded; portable `.zip`; **★4:** `windows-2022` CI build + silent-install smoke; **★5:** `signtool` gated on cert secret (ship unsigned + SmartScreen workaround until a cert is bought). |
| **macOS `.dmg`** (nothing yet) | ☆ | Stand up `briefcase` universal2 bundle with `python-build-standalone`, `.icns`, Info.plist usage strings; **★2–3:** Dock/Spotlight + curated payload; **★4:** `macos-14` CI build + smoke; **★5:** Homebrew cask + README Gatekeeper workaround (notarization deferred behind Apple cert — §17). |
| **Flatpak** (`packaging/flatpak/…yml`) | ★ | Won't pass Flathub today (network `pip install`, `--filesystem=home`, pulseaudio). Pin pip deps offline via `flatpak-pip-generator`, build native wheels in-sandbox, tighten `finish-args` (pipewire + xdg dirs, drop `home`/`network`), add `metainfo.xml` + desktop + icons; **★4:** `flatpak-builder` CI + `flatpak run … --help` smoke; **★5:** Flathub submission (free; needs app-id claim). |
| **Snap** (`packaging/snap/snapcraft.yaml`) | ★ | `core24`, **strict** confinement + precise plugs (§5.2), `desktop-launch` wrapper + `meta/gui`; **★4:** `snapcore/action-build` CI + `snap install`/`--help` smoke; **★5:** Snap Store publish (free; needs name registration). |

**Cross-cutting blockers that gate stars on multiple channels at once:**

1. **`python-build-standalone` bundling** is a locked decision (§0). The shared
   helper now exists (`tools/packaging/fetch_runtime.sh`, landed 2026-06-21) and
   is wired into both Linux bash installers. It is the single biggest lever: it
   unlocks ★3 for the one-liner (done), native packages (done 2026-06-30),
   Windows, and macOS. Windows and macOS still need to adopt it (Phases 3–4).
2. **Curated payload staging** — ✅ done. `tools/packaging/stage_payload.sh`
   (landed 2026-06-29) produces an allowlisted core payload (no `.git`/`.venv`/
   `logs`/`docs`/`drop-ins`/licensed sims packs) with a leak guard. Windows,
   macOS, and native packaging stage from it so none can ship the whole repo.
3. **Drop-in dependency system (§6)** — `dropin.toml` + `unicorn-viz dropins`
   CLI are unbuilt. Not required for core-installer gold stars, but required
   before the "official drop-in pack" UX and before drop-ins can be promised to
   install cleanly on any channel. Sequenced last (§16 Phase 7).

## 1. Current Implementation Snapshot

This section is the working inventory for the installer effort. Keep it
current as the repo evolves so we always know which surfaces own install-time
behavior and which dependencies belong to the core versus an individual drop-in.

### 1.1 Installer and packaging entrypoints

- `install.sh` - public one-line Linux bootstrapper for release artifacts.
- `tools/install/lib.sh` - shared distro detection, dependency install, and
  desktop integration helpers.
- `tools/install_linux.sh` - clone-local Linux installer wrapper.
- `tools/install/uninstall_linux.sh` - uninstall helper for the Linux flow.
- `tools/packaging/build_native.sh` - native `.deb` / `.rpm` packager.
- `packaging/windows/UnicornViz.iss` - Windows installer definition.
- `packaging/flatpak/io.unicornviz.UnicornViz.yml` - Flatpak manifest.
- `packaging/snap/snapcraft.yaml` - Snap manifest.
- `.github/workflows/release-installers.yml` - release-time packaging fan-out.

### 1.2 Core dependency inventory

The authoritative Python runtime dependency list lives in
`requirements.txt`. The current core set is:

- `moderngl>=5.10`
- `pysdl2>=0.9.16`
- `pysdl2-dll>=2.28`
- `numpy>=1.26`
- `scipy>=1.12`
- `sounddevice>=0.4.6`
- `python-rtmidi>=1.5`
- `Pillow>=10.0`
- `psutil>=5.9`
- `opencv-python-headless>=4.9`

Current Linux installer and native package system dependencies are:

| Family | Packages | Notes |
|---|---|---|
| APT / Debian | `python3`, `python3-venv`, `python3-dev`, `libsdl2-dev`, `libgl1-mesa-dev`, `libffi-dev`, `libpipewire-0.3-dev`, `libasound2-dev`, `ffmpeg`, `git`, `curl` | Used by the release installer and native package build path. |
| DNF / Fedora | `python3`, `python3-devel`, `gcc-c++`, `make`, `SDL2-devel`, `mesa-libGL-devel`, `libffi-devel`, `pipewire-devel`, `alsa-lib-devel`, `git`, `curl`, `ffmpeg` | Fedora install helper prefers the distro package manager and falls back gracefully if `ffmpeg` is not available. |
| Pacman / Arch | `python`, `python-pip`, `sdl2`, `mesa`, `libffi`, `pipewire`, `alsa-lib`, `ffmpeg`, `git`, `curl` | Current clone-local installer path. |

### 1.3 Known drop-in dependency inventory

Only a small subset of drop-ins currently declares extra install-time
requirements beyond the core set:

| Drop-in | Extra dependencies | Source of truth |
|---|---|---|
| `webcam-01` | `opencv-python-headless >= 4.9` | `drop-ins/webcam-01/README.md` |
| `spotify-01` | `playerctl` available on `PATH` | `drop-ins/spotify-01/README.md` |

All other drop-ins currently discovered in this repo appear to rely on the
core dependency set only. Re-check this table whenever a drop-in README,
manifest, or import surface changes.

### 1.4 Current packaging risk to watch

The current Fedora installer failure is caused by the project build backend
declaration, not by a missing system package. `pip install .` is invoking a
backend path that cannot be imported from the build environment, so the native
package flow never reaches the actual project build.

The fix is to use a valid setuptools backend and keep the build requirements in
sync with the packaging toolchain so isolated builds can resolve the project
metadata cleanly.

---

## 1. Goals

A first-time user must be able to install Unicorn Viz on any supported OS in
**one obvious step**, end up with:

1. A working `unicorn-viz` command on PATH (or platform-equivalent).
2. A menu / Start-menu entry that uses our unicorn avatar as the icon and
   launches the app on click.
3. A self-contained Python environment that does not pollute the system
   interpreter.
4. A clearly tagged version that matches a GitHub release on
   `djunicorntears/unicorn-viz`.

### Target deliverables per release tag

| Platform              | Deliverable                                   | Channel                  |
|-----------------------|-----------------------------------------------|--------------------------|
| Linux (any distro)    | `curl … \| bash` one-liner                    | `install.unicornviz.io` redirect → raw GitHub script |
| Ubuntu/Debian (amd64) | `unicorn-viz_X.Y.Z_amd64.deb`                 | GitHub Releases asset    |
| Fedora/RHEL (x86_64)  | `unicorn-viz-X.Y.Z-1.fc40.x86_64.rpm`         | GitHub Releases asset    |
| Linux (sandboxed)     | Flathub: `io.unicornviz.UnicornViz`           | Flathub                  |
| Linux (sandboxed)     | Snap Store: `unicorn-viz`                     | Snap Store               |
| Windows 10/11 (x64)   | `UnicornViz-Setup-X.Y.Z.exe` (Inno Setup)     | GitHub Releases asset    |
| Windows (portable)    | `UnicornViz-Portable-X.Y.Z.zip`               | GitHub Releases asset    |
| macOS 12+ (universal2)| `UnicornViz-X.Y.Z.dmg` (notarized)            | GitHub Releases asset    |
| macOS (Homebrew)      | `brew install --cask unicorn-viz`             | Homebrew tap (`djunicorntears/tap`) |
| Android / iOS         | Not planned for v1 — see §12 feasibility note | —                        |

All artifacts are produced by GitHub Actions on tag push (`v*.*.*`) and
uploaded to the matching GitHub Release on the **canonical repo**.

---

## 2. Versioning & Release Source of Truth

- Single version string lives in `pyproject.toml` (`[project].version`).
- Tagging: annotated tags on `djunicorntears/unicorn-viz` named `vX.Y.Z`.
- CI extracts the version from the tag (`${GITHUB_REF_NAME#v}`) and stamps it
  into every artifact (`.deb`, `.rpm`, `.iss`, `snapcraft.yaml`, flatpak
  manifest, installer script defaults).
- Pre-release tags (`vX.Y.Z-rc.N`) build artifacts but mark the GitHub Release
  as **pre-release** and skip Flathub/Snap stable channel pushes.

### Release-time automation contract

A single workflow (`.github/workflows/release.yml`) is triggered on tag push and
fans out to matrix jobs:

```
on:
  push:
    tags: ['v*.*.*']
```

Jobs (parallel where possible):

1. `build-linux-bash-installer` — lints `install.sh`, uploads it as a release
   asset and updates the `latest` symlink-style asset.
2. `build-deb` — builds `.deb` for `amd64` (and `arm64` later) on Ubuntu 22.04
   and 24.04 runners.
3. `build-rpm` — builds `.rpm` on Fedora container (`fedora:40`).
4. `build-flatpak` — builds & validates the flatpak bundle; on stable tags,
   opens a PR against the Flathub manifest repo.
5. `build-snap` — runs `snapcraft remote-build`; on stable tags, pushes to
   the `stable` channel via stored credentials.
6. `build-windows-installer` — builds Inno Setup `.exe` and portable `.zip`.
7. `publish-release` — gathers artifacts from all jobs, creates / updates the
   GitHub Release, attaches checksums (`SHA256SUMS`) and a `manifest.json`
   listing every artifact + version for the bash installer to consume.

---

## 3. One-Line Linux Bash Installer

### 3.1 User experience

```bash
curl -fsSL https://raw.githubusercontent.com/djunicorntears/unicorn-viz/main/install.sh | bash
```

(Optional vanity URL `https://get.unicornviz.io` redirecting to the above —
not required for v1.)

Flags supported via `bash -s --`:

| Flag                  | Effect                                                  |
|-----------------------|---------------------------------------------------------|
| `--prefix <dir>`      | Override install root (default: `~/.local/share/unicorn-viz`) |
| `--version <vX.Y.Z>`  | Pin a specific release (default: latest stable tag)     |
| `--channel stable\|prerelease` | Pick latest stable or latest prerelease        |
| `--no-deps`           | Skip system package install (assume user did it)        |
| `--no-desktop`        | Skip `.desktop` entry / icon install                    |
| `--system`            | System-wide install to `/opt/unicorn-viz` (needs sudo)  |
| `--uninstall`         | Remove install, venv, desktop entry, icon               |
| `--dry-run`           | Print actions without executing                         |

### 3.2 Script responsibilities

1. **Refuse to run as root** unless `--system` is given (avoid surprise
   `pip install` into system Python).
2. **Detect distro** via `/etc/os-release` (`ID`, `ID_LIKE`). Supported:
   `ubuntu`, `debian`, `linuxmint`, `pop`, `fedora`, `rhel`, `centos`,
   `rocky`, `almalinux`, `arch`, `manjaro`, `endeavouros`. Fall back to a
   clear error listing the packages the user must install manually.
3. **Install system deps** with `apt-get` / `dnf` / `pacman` using the same
   package sets currently in `tools/install_linux.sh` (extracted into a
   shared shell function library `install/lib.sh` so the bash installer and
   the in-tree dev installer stay in sync).
4. **Resolve release tag** via the GitHub REST API:
   `GET /repos/djunicorntears/unicorn-viz/releases/latest`. Honor
   `--version` and `--channel`. Fall back gracefully if the API is rate-limited
   by reading a static `manifest.json` from the latest release.
5. **Download & verify** the release source tarball
   (`unicorn-viz-X.Y.Z.tar.gz`) and matching `SHA256SUMS` file.
   Verify checksum with `sha256sum -c`. If `gpg` and our signing key are
   present, also verify the detached `.asc` signature (optional in v1, planned
   for v1.1 — see §10).
6. **Create venv** at `<prefix>/venv` using Python 3.11+. If the system
   Python is older, surface a clear, distro-specific remediation message
   (e.g. `sudo dnf install python3.11`).
7. **Install Python deps** with `pip install --upgrade -r requirements.txt`,
   then `pip install .` so the `unicorn-viz` console script is generated in
   `<prefix>/venv/bin/`.
8. **Install desktop integration** (see §7):
   - `~/.local/share/applications/unicorn-viz.desktop`
   - `~/.local/share/icons/hicolor/256x256/apps/unicorn-viz.png`
   - `~/.local/share/icons/hicolor/scalable/apps/unicorn-viz.svg` (if SVG is
     added later)
   - Symlink `~/.local/bin/unicorn-viz` → `<prefix>/venv/bin/unicorn-viz`
     (warn if `~/.local/bin` is not on `PATH`).
9. **Run `update-desktop-database`** and `gtk-update-icon-cache` if available
   (best-effort, never fatal).
10. **Print a final summary**: install path, version, how to launch, how to
    uninstall, location of `config.toml` template.

### 3.3 Hardening rules

- `set -Eeuo pipefail`, an `ERR` trap that prints the failing command and
  line, and a `cleanup` trap that removes the temp download dir.
- All `curl` calls use `-fsSL --retry 3 --retry-delay 2`.
- All `wget` references replaced with `curl` to avoid the wget/curl bifurcation.
- Idempotent re-runs: detect existing install, prompt to upgrade in place
  (preserve user's `config.toml`).
- No `eval`, no `curl … | sudo bash`. The script asks once for sudo and caches
  the timestamp via `sudo -v`.
- Lint with `shellcheck` in CI; fail the workflow on warnings.

### 3.4 Files added

```
install.sh                              # the public one-liner (top of repo)
tools/install/lib.sh                    # shared distro detection + deps
tools/install/uninstall_linux.sh        # invoked by install.sh --uninstall
```

`tools/install_linux.sh` becomes a thin wrapper around `tools/install/lib.sh`
for dev contributors working from a clone.

---

## 4. Native Packages (.deb / .rpm)

### 4.1 Package layout (FHS)

```
/opt/unicorn-viz/                       app files (venv lives here)
/opt/unicorn-viz/venv/                  bundled Python venv (relocatable)
/usr/bin/unicorn-viz                    -> /opt/unicorn-viz/venv/bin/unicorn-viz
/usr/share/applications/unicorn-viz.desktop
/usr/share/icons/hicolor/256x256/apps/unicorn-viz.png
/usr/share/icons/hicolor/scalable/apps/unicorn-viz.svg
/usr/share/doc/unicorn-viz/             README, LICENSE, config.full.example.toml
/etc/unicorn-viz/config.toml            shipped as conffile (dpkg/rpm aware)
```

Bundling the venv into `/opt/unicorn-viz/venv` lets us avoid Python ABI
fragility and gives us one `.deb` / `.rpm` per (distro × arch) pair.

### 4.2 Build approach

Use **[fpm](https://github.com/jordansissel/fpm)** as the package generator.
It runs cleanly in CI, supports both `.deb` and `.rpm`, and lets us reuse a
single `tools/packaging/build_native.sh` script.

Build pipeline per target distro:

1. Spin up a container matching the target distro:
   - `ubuntu:22.04`, `ubuntu:24.04`, `debian:12` → `.deb`
   - `fedora:40`, `fedora:41` → `.rpm`
2. Install system build deps (same set as §3.2 step 3) **plus** `patchelf` and
   any libraries needed by `python-rtmidi` / `sounddevice` to build wheels.
3. Create a fresh venv at `/opt/unicorn-viz/venv` with the target distro's
   Python 3.11+.
4. `pip install --no-cache-dir -r requirements.txt && pip install .`
5. Make the venv relocatable: rewrite the shebangs of every script in
   `venv/bin/*` to `#!/opt/unicorn-viz/venv/bin/python` (works because the
   final install path matches the build path).
6. Stage files into `staging/` matching §4.1.
7. Invoke `fpm` with:
   - shared metadata (name, version, license=MIT, vendor, URL, description),
   - per-format dependencies (`Depends:` for deb, `Requires:` for rpm),
   - postinst running `update-desktop-database` and `gtk-update-icon-cache`,
   - prerm cleanly removing the symlink if it points at our binary.
8. Upload artifact `unicorn-viz_${VERSION}_${ARCH}.${EXT}` to the release.

### 4.3 Runtime dependencies declared in package metadata

| Distro family | Packages                                                          |
|---------------|-------------------------------------------------------------------|
| Debian/Ubuntu | `libsdl2-2.0-0`, `libgl1`, `libffi8`, `libpipewire-0.3-0`, `libasound2`, `ffmpeg`, `python3.11` (Ubuntu 22.04 needs deadsnakes-equivalent — see note) |
| Fedora        | `SDL2`, `mesa-libGL`, `libffi`, `pipewire`, `alsa-lib`, `ffmpeg-free`, `python3.11` |

**Ubuntu 22.04 Python note:** if the target distro ships Python < 3.11, the
`.deb` for that distro ships its own Python 3.11 inside `/opt/unicorn-viz/`
via `python-build-standalone` (Indygreg). This removes the deadsnakes
requirement and yields identical runtimes across all Ubuntu LTS versions.

### 4.4 Repository hosting (post-v1)

- Optional v1.1: publish an APT repo and a DNF/YUM repo on GitHub Pages so
  users can `apt-add-repository` / drop a `.repo` file and receive updates.
- Until then, the bash installer's `--channel` logic handles update polling.

---

## 5. Flatpak & Snap

### 5.1 Flatpak (Flathub target)

Current state: minimal manifest in `packaging/flatpak/io.unicornviz.UnicornViz.yml`.
Gaps to close before Flathub submission:

1. **Pin runtime deps as flatpak sources** — Flathub forbids `pip install`
   reaching the network. Generate a `python3-requirements.json` from
   `requirements.txt` using
   [`flatpak-pip-generator`](https://github.com/flatpak/flatpak-builder-tools/tree/master/pip)
   and commit it next to the manifest. CI regenerates and diffs on every
   release.
2. **Wheels with native code** (`python-rtmidi`, `sounddevice`, `moderngl`)
   must build inside the sandbox — add their build deps to a `modules:`
   entry (`libffi`, `alsa-lib`, `portaudio`, `jack-dev` headers via the SDK).
3. **Permissions audit (`finish-args`):**
   - Replace `--filesystem=home` with `--filesystem=xdg-music:ro`,
     `--filesystem=xdg-videos:ro`, `--filesystem=xdg-pictures:ro`, plus
     `--filesystem=xdg-config/unicorn-viz:create`.
   - Add `--device=all` only if MIDI / webcam access requires it; otherwise
     keep `--device=dri` and add `--device=input` for MIDI.
   - Replace `--socket=pulseaudio` with `--socket=pipewire` once Flathub
     runtime supports it (24.08 does); keep pulseaudio as fallback.
   - Drop `--share=network` unless the in-app `tools/fetch_acid_ans.py`
     workflow is exposed to end users (it currently is not).
4. **Desktop file + AppStream metadata** required by Flathub:
   - `io.unicornviz.UnicornViz.desktop`
   - `io.unicornviz.UnicornViz.metainfo.xml` (with screenshots, release notes,
     OARS rating, content rating, license SPDX = `MIT`).
   - 256×256 and 512×512 PNG icons + scalable SVG.
   All three live under `packaging/flatpak/data/`.
5. **CI build job** uses `flatpak-builder --user --install-deps-from=flathub`
   inside `bilelmoussaoui/flatpak-github-actions/flatpak-builder@v6`, and on
   stable tags opens a PR against `flathub/io.unicornviz.UnicornViz` (which
   we will request after the first successful local end-to-end build).

### 5.2 Snap (Snap Store target)

Current state: minimal `snapcraft.yaml` with `devmode` confinement.
Roadmap:

1. Switch `base: core24` (matches Ubuntu 24.04, current LTS at the time of
   this plan).
2. Move from `devmode` to `strict` confinement and declare the precise plugs:
   `opengl`, `wayland`, `x11`, `audio-record`, `audio-playback`, `alsa`,
   `pulseaudio`, `removable-media`, `home`, `raw-usb` (for MIDI).
3. Promote `grade: devel` → `grade: stable` once strict confinement passes
   the snap review.
4. Add a `desktop-launch` wrapper so the snap integrates with the application
   menu and picks up the icon from `meta/gui/unicorn-viz.png` and
   `meta/gui/unicorn-viz.desktop`.
5. CI uses `snapcore/action-build@v1` to produce the `.snap`, attaches it to
   the GitHub Release, and on stable tags runs `snapcraft upload --release=stable`
   using a token stored in `SNAP_STORE_LOGIN`.
6. Manual one-time setup: register the `unicorn-viz` name on the Snap Store
   under the `djunicorntears` publisher.

### 5.3 Known sandbox risks to validate before promoting either

- PipeWire device latency and xrun behavior under `pipewire` socket vs.
  `pulseaudio` socket.
- `python-rtmidi` enumerating ALSA sequencer ports inside the sandbox.
- `moderngl` requiring `LIBGL_DRI3_DISABLE=1` in some Mesa/Wayland combos.
- File pickers for user-supplied media (drop-ins like `videos-01`,
  `images-01`) — confirm they work under both XDG portals.

Each of these gets a dedicated checklist item in the release QA matrix.

---

## 6. Drop-In Dependency Management

Drop-ins live in their own private repos (per project policy) and may pull
in Python packages or system libraries that the core does **not** require.
The core release tarball, `.deb`, `.rpm`, Windows installer, and `.dmg`
ship the **core dependency set only**. Drop-ins must declare and resolve
their extra deps through a shared mechanism.

### 6.1 Drop-in dependency manifest

Every drop-in repo (and every directory under `drop-ins/`) gains a
`dropin.toml` at its root:

```toml
[dropin]
id = "webcam-01"
name = "Webcam"
version = "0.3.2"
min_core = "0.9.0"

[dependencies.python]
# PEP 508 requirement strings, resolved with pip inside the core venv.
requires = [
  "opencv-python>=4.9",
  "av>=12.0",
]

[dependencies.system]
# Per-platform native package names. Missing keys = nothing needed there.
apt    = ["libv4l-dev", "v4l-utils"]
dnf    = ["libv4l-devel", "v4l-utils"]
pacman = ["v4l-utils"]
brew   = ["ffmpeg"]
winget = []   # bundled in the Windows installer payload

[dependencies.binaries]
# Optional: extra runtime binaries to fetch (e.g., ffmpeg static builds).
ffmpeg = { source = "system", min_version = "6.0" }

[capabilities]
# Used by the dependency checker to warn about sandbox limits.
needs_camera = true
needs_midi   = false
needs_network = false
```

The manifest is the **single source of truth** for that drop-in's extra
requirements. The core installer never hard-codes drop-in deps.

Every drop-in also ships a platform-aware installer bundle. For complex
drop-ins, the installer may add Python or system dependencies before staging
files. For simple drop-ins, the installer is still required but may only copy
the bundle into the correct drop-in location for the current OS.

### 6.2 `unicorn-viz dropins` CLI

A new subcommand group on the core CLI handles enumeration, checking, and
installing drop-in deps. Implemented in `unicornviz/dropins/cli.py`.

| Command                                  | Behavior                                                       |
|------------------------------------------|----------------------------------------------------------------|
| `unicorn-viz dropins list`               | List installed drop-ins + version + dep status (OK / missing). |
| `unicorn-viz dropins check`              | Read each `dropin.toml`, verify Python + system deps, report.  |
| `unicorn-viz dropins check <id>`         | Same, scoped to one drop-in.                                   |
| `unicorn-viz dropins install`            | Install missing deps for every enabled drop-in.                |
| `unicorn-viz dropins install <id>`       | Install for one drop-in.                                       |
| `unicorn-viz dropins doctor`             | Verbose diagnostics: platform detection, package manager, sandbox status, write-permission to the core venv. |

Behavior:

1. **Python deps** are installed into the **core venv** via
   `pip install --upgrade <pkg>`. This is the same venv the core uses so
   imports just work. For sandboxed installs (flatpak/snap) where the venv
   is read-only, the command prints a clear message that the drop-in is
   incompatible with the sandboxed build and recommends the `.deb`/`.rpm`
   /bash-installer/native installer instead.
2. **System deps** are installed via the platform package manager (`apt`,
   `dnf`, `pacman`, `brew`, `winget`). The command prompts for sudo when
   needed; in `--non-interactive` mode it prints the exact command instead
   of running it.
3. **No drop-in is auto-enabled** by `dropins install` — enabling/disabling
   is a separate concern handled by `config.toml`. `install` only ensures
   the deps are present for whatever the user later enables.
4. **Idempotent:** running twice does nothing the second time.
5. **Offline-aware:** if no network, prints the list of missing deps and
   exits non-zero so CI / packaging scripts can detect the gap.

6. **Installer required for every drop-in:** even when a drop-in has no extra
  runtime dependencies, it still ships an installer that stages its files to
  the proper drop-in directory for the host platform.

### 6.3 Boot-time gating

The core loader already wraps drop-in imports in `try/except` per the
Drop-In Independence Rules. We extend it:

- On startup, for every enabled drop-in, run a lightweight version of
  `dropins check` (no network, no installs) and:
  - Log a single-line WARN per drop-in with missing deps.
  - Surface the warning in the on-screen `H` help overlay's drop-in section
    so the user sees "webcam-01: missing opencv-python" without digging in
    logs.
  - Skip loading that drop-in's GL resources so it stays a true no-op
   rather than crashing mid-render.
- An optional `--strict-dropins` CLI flag causes startup to exit non-zero
  when any enabled drop-in has missing deps (useful for installer smoke
  tests in CI).

### 6.4 Core installer responsibilities

Each platform's installer is responsible for the **core dep set only**:

- Linux bash installer / `.deb` / `.rpm`: install `python3.11`, SDL2, GL,
  pipewire, alsa, ffmpeg, libffi, plus the bundled `python-build-standalone`
  runtime and the core's `requirements.txt`.
- Windows installer: bundle Python 3.11 embed, ffmpeg, SDL2 DLLs, and
  install `requirements.txt` into the embedded site-packages.
- macOS `.dmg`: bundle Python 3.11 universal2, ffmpeg, SDL2 frameworks,
  and install `requirements.txt` into the bundle's `runtime/`.
- Flatpak / snap: same as above but inside the sandbox.

After the core is installed, the user (or a post-install helper) runs
`unicorn-viz dropins install` to fetch the extras for the drop-ins they
want to use. The installer's final-summary screen prints this command
verbatim so the discovery path is obvious.

### 6.5 Optional: "meta" drop-in installers per platform

For the curated official drop-in set, we publish per-platform helper
packages that wrap `unicorn-viz dropins install` for users who prefer
GUI/menu installation:

- Linux: a `unicorn-viz-dropins-official` `.deb`/`.rpm` whose postinst calls
  `unicorn-viz dropins install --bundle official`.
- Windows: an optional checkbox on the main installer's last page —
  "Install official drop-in pack now" — which runs the same command.
- macOS: same checkbox on the `.dmg`'s first-run helper.

The "official drop-in bundle" is defined by a list in
`packaging/dropins/official-bundle.toml` in the canonical repo and is
versioned alongside the core release.

### 6.6 Per-drop-in repo policy update

The project policy already requires drop-ins to live in their own private
repos as submodules. We add:

- Every drop-in repo **must** ship `dropin.toml` at its root before it can
  be added as a submodule.
- CI in each drop-in repo runs `unicorn-viz dropins check` against a fresh
  core install to verify the manifest matches reality.
- A new `tools/lint_dropin.py` in the core repo validates manifests across
  all `drop-ins/*/dropin.toml` so PRs that break the contract fail fast.

### 6.7 Current drop-in installer matrix

Current policy: every shipped drop-in has an installer bundle. When no extra
deps are needed, the installer is copy-only and places the drop-in into the
appropriate `drop-ins/` target path for the OS/package format.

| Drop-in | Installer mode | Extra dependencies | Notes |
|---|---|---|---|
| alien-invasion-01 | Copy-only bundle installer | None listed | Stages effect files into the drop-in location. |
| auto-vj-01 | Copy-only bundle installer | None listed | Automation bundle remains self-contained. |
| candy-frame-01 | Copy-only bundle installer | None listed | Simple effect bundle. |
| control-room-01 | Copy-only bundle installer | None listed | Control surface bundle. |
| cyber-war-01 | Copy-only bundle installer | None listed | Simple effect bundle. |
| disco-ball-01 | Copy-only bundle installer | None listed | Simple effect bundle. |
| grand-finale-01 | Copy-only bundle installer | None listed | Sequenced effect bundle. |
| hacker-terminal-01 | Copy-only bundle installer | None listed | Simple effect bundle. |
| images-01 | Copy-only bundle installer | None listed | Media bundle with bundled assets. |
| multi-head-01 | Copy-only bundle installer | None listed | Display subsystem bundle. |
| postfx-01 | Copy-only bundle installer | None listed | Post-processing bundle. |
| projectm-01 | Copy-only bundle installer | None listed | Engine integration bundle. |
| sims-01 | Copy-only bundle installer | None listed | Media/effect bundle. |
| spotify-01 | Copy-only + dependency check installer | `playerctl` on PATH for local mode | Installer verifies host MPRIS support before enabling local metadata mode; Web API auth prep is documented separately. |
| streaming-01 | Copy-only bundle installer | None listed | Streaming subsystem bundle. |
| textures-01 | Copy-only bundle installer | None listed | Media bundle. |
| tron-grid-01 | Copy-only bundle installer | None listed | Simple effect bundle. |
| unicorn-tears-01 | Copy-only bundle installer | None listed | Simple effect bundle. |
| videos-01 | Copy-only bundle installer | None listed | Media bundle. |
| webcam-01 | Bundle installer + dependency check | `opencv-python-headless >= 4.9` | Installer verifies camera stack before enabling. |

If a new drop-in appears in the workspace, it must be added to this matrix
before release packaging is considered complete.

Copy-only installer bundles now exist for the easy drop-ins, including the
simple effects and subsystem bundles that only need file staging. `webcam-01`
and `spotify-01` remain the dependency-aware follow-up installers that will be
upgraded next.

---

## 7. Desktop / Menu Integration (Linux)

Single canonical `.desktop` file shipped by **every** Linux delivery channel
(`.deb`, `.rpm`, flatpak, snap, bash installer):

```ini
[Desktop Entry]
Type=Application
Name=Unicorn Viz
GenericName=Audio-Reactive Visualizer
Comment=Fullscreen OpenGL demoscene visualizer with audio + MIDI control
Exec=unicorn-viz %U
Icon=unicorn-viz
Terminal=false
Categories=AudioVideo;Audio;Graphics;Player;
Keywords=visualizer;demoscene;vj;audio;midi;ansi;
StartupNotify=true
StartupWMClass=unicorn-viz
```

- Icon: `assets/icons/unicorn-viz.png` (already in repo). Generate additional
  sizes (48, 64, 128, 256, 512) at release time via `magick convert` and
  install into the matching `hicolor/<size>x<size>/apps/` directories.
- An SVG version (`unicorn-viz.svg`) is a v1.1 follow-up; the PNG ladder
  covers all current desktops in the interim.
- Bash installer writes to `~/.local/share/{applications,icons}`.
- `.deb` / `.rpm` write to `/usr/share/{applications,icons}` and run
  `update-desktop-database` / `gtk-update-icon-cache` in postinst.
- Flatpak / snap publish via their respective manifests (which the host
  exposes to the menu automatically).

---

## 8. Windows Installer

### 7.1 Goal

Drop the current "clone + run batch file" flow in favor of a real
**`.exe` installer** that:

- Installs into `%ProgramFiles%\UnicornViz\` (per-machine) or
  `%LocalAppData%\Programs\UnicornViz\` (per-user, selectable on the first
  page).
- Bundles its own Python 3.11 runtime — no reliance on a system Python or
  the `py` launcher.
- Bundles ffmpeg.
- Creates a Start menu entry **and** an optional desktop / taskbar entry,
  both with our unicorn avatar icon.
- Registers a proper uninstaller in Apps & Features.
- Is signed with an EV (or, initially, OV) code-signing certificate so
  SmartScreen doesn't bury it (see §10).

### 7.2 Toolchain

Continue with **Inno Setup 6** (existing `packaging/windows/UnicornViz.iss`)
but rework it substantially:

1. CI job runs on `windows-2022` GitHub-hosted runner.
2. Build steps before invoking `ISCC.exe`:
   - Download embeddable Python 3.11 (`python-3.11.x-embed-amd64.zip`) from
     python.org, extract to `build/python/`. Enable `site` by uncommenting
     the `python311._pth` line and shipping `get-pip.py`.
   - Create venv-equivalent layout: `build/python/Scripts/`, `build/python/Lib/site-packages/`.
   - `python -m pip install --no-cache-dir -r requirements.txt`.
   - `python -m pip install .` (puts `unicorn-viz.exe` into `Scripts/`).
   - Download static ffmpeg build (gyan.dev) and stage into `build/ffmpeg/`.
   - Copy `assets/`, `unicornviz/`, `config.full.example.toml`, `README.md`,
     `LICENSE` into `build/payload/`.
3. `ISCC.exe packaging/windows/UnicornViz.iss /DAppVersion=${VERSION}` produces
   `UnicornViz-Setup-${VERSION}.exe`.
4. A separate job zips `build/payload/` as `UnicornViz-Portable-${VERSION}.zip`
   for users who can't run installers.

### 7.3 Inno Setup script changes

```iss
[Setup]
AppId={{7F4A7D48-38DE-4B80-95F7-773ECA5B2D13}
AppName=Unicorn Viz
AppVersion={#AppVersion}
AppPublisher=Unicorn Viz
AppPublisherURL=https://github.com/djunicorntears/unicorn-viz
AppSupportURL=https://github.com/djunicorntears/unicorn-viz/issues
DefaultDirName={autopf}\UnicornViz
DefaultGroupName=Unicorn Viz
OutputBaseFilename=UnicornViz-Setup-{#AppVersion}
SetupIconFile=..\..\assets\icons\unicorn-viz.ico
UninstallDisplayIcon={app}\unicorn-viz.exe
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
Compression=lzma2/ultra64
SolidCompression=yes
SignTool=signtool

[Files]
Source: "build\payload\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "build\python\*";  DestDir: "{app}\runtime"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "build\ffmpeg\*";  DestDir: "{app}\ffmpeg"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\..\assets\icons\unicorn-viz.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Unicorn Viz";        Filename: "{app}\runtime\Scripts\unicorn-viz.exe"; WorkingDir: "{app}"; IconFilename: "{app}\unicorn-viz.ico"
Name: "{group}\Unicorn Viz Config"; Filename: "{app}\config.full.example.toml";        WorkingDir: "{app}"; IconFilename: "{app}\unicorn-viz.ico"
Name: "{group}\Uninstall Unicorn Viz"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Unicorn Viz";  Filename: "{app}\runtime\Scripts\unicorn-viz.exe"; WorkingDir: "{app}"; IconFilename: "{app}\unicorn-viz.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "pintotaskbar"; Description: "Pin Unicorn Viz to the taskbar"; Flags: unchecked

[Registry]
; PATH entry (per-user or per-machine depending on install scope)
Root: HKA; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}\runtime\Scripts"; Check: NeedsAddPath('{app}\runtime\Scripts')

[Run]
Filename: "{app}\runtime\Scripts\unicorn-viz.exe"; Description: "Launch Unicorn Viz"; Flags: nowait postinstall skipifsilent
```

(`Check: NeedsAddPath` is a Pascal Script helper to avoid duplicating PATH
entries on reinstall.)

### 7.4 Things removed from the current Windows flow

- `tools/install_windows.bat`, `tools/install_windows.ps1`,
  `tools/install_windows_gui.ps1` move under `tools/dev/windows/` and are
  marked **developer-only** (running from a git clone). End users never see
  them.
- The current `[Files] Source: "{#RepoRoot}\*"` blanket copy is replaced by
  the curated `build/payload` staging in §8.2 so we never ship `.git/`,
  `.venv/`, screenshots, logs, audit docs, or drop-in dev scratch files into
  Program Files.

### 7.5 Start-menu / taskbar requirements

- `Icons` section above creates Start-menu entries automatically.
- Taskbar pinning is offered as an optional task; the actual pin happens via
  a small PowerShell helper (`tools/packaging/windows/pin_taskbar.ps1`)
  invoked from `[Run]` when the user opts in. Windows 11 made programmatic
  pinning harder; if the helper fails we silently no-op and rely on the user
  right-clicking the Start tile.
- The app's `StartupWMClass` Linux equivalent on Windows is the
  `AppUserModelID`. We set it inside `unicornviz/app.py` via
  `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("io.unicornviz.UnicornViz")`
  so taskbar grouping uses the right icon.

### 7.6 Future: MSIX

Once the EV cert is in place, evaluate MSIX packaging to enable Microsoft
Store distribution. Deferred to v1.2.

---

## 9. CI Architecture

```
.github/workflows/
  release.yml             # tag-triggered fan-out
  ci.yml                  # PR + main: lint + tests + shellcheck
  installer-smoke.yml     # nightly: install each artifact in a clean VM/container
  compat-matrix.yml       # (existing) runtime smoke tests
```

### 8.1 `release.yml` matrix sketch

```yaml
jobs:
  bash-installer:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: shellcheck install.sh tools/install/*.sh
      - run: cp install.sh dist/install.sh

  deb:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        target: [ubuntu-22.04, ubuntu-24.04, debian-12]
    container: ${{ matrix.target == 'debian-12' && 'debian:12' || format('ubuntu:{0}', matrix.target == 'ubuntu-22.04' && '22.04' || '24.04') }}
    steps: …

  rpm:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        target: [fedora-40, fedora-41]
    container: fedora:${{ matrix.target == 'fedora-40' && '40' || '41' }}
    steps: …

  flatpak:
    runs-on: ubuntu-latest
    steps:
      - uses: bilelmoussaoui/flatpak-github-actions/flatpak-builder@v6
        with:
          bundle: unicorn-viz.flatpak
          manifest-path: packaging/flatpak/io.unicornviz.UnicornViz.yml

  snap:
    runs-on: ubuntu-latest
    steps:
      - uses: snapcore/action-build@v1
      - if: startsWith(github.ref, 'refs/tags/v') && !contains(github.ref, '-rc')
        uses: snapcore/action-publish@v1
        with:
          store_login: ${{ secrets.SNAP_STORE_LOGIN }}
          snap: ${{ steps.build.outputs.snap }}
          release: stable

  windows:
    runs-on: windows-2022
    steps: …  # see §8.2

  publish:
    needs: [bash-installer, deb, rpm, flatpak, snap, windows]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
      - run: sha256sum dist/* > dist/SHA256SUMS
      - uses: softprops/action-gh-release@v2
        with:
          repository: djunicorntears/unicorn-viz
          token: ${{ secrets.DJUNICORNTEARS_RELEASE_TOKEN }}
          files: dist/*
          prerelease: ${{ contains(github.ref, '-rc') }}
          generate_release_notes: true
```

### 8.2 Cross-repo publishing

The dev repo (`iDoMeteor/unicorn-viz`) runs the build matrix. A PAT stored as
`DJUNICORNTEARS_RELEASE_TOKEN` (scoped to `contents:write` on the canonical
repo) is used to create the release there. Alternatively, mirror the tag into
`djunicorntears/unicorn-viz` and run the same workflow on that repo. The
mirror approach is preferred long-term so the public repo is the single
source of truth for releases.

### 8.3 Nightly smoke matrix

`installer-smoke.yml` runs every night against the latest release artifacts:

| Job                  | Environment                | Checks                                |
|----------------------|----------------------------|---------------------------------------|
| bash-installer-ubuntu| `ubuntu:24.04` container   | Runs `install.sh`, asserts `unicorn-viz --help` works |
| bash-installer-fedora| `fedora:41` container      | Same                                  |
| bash-installer-arch  | `archlinux:latest`         | Same                                  |
| deb-install          | `ubuntu:24.04`             | `apt install ./*.deb`, then `--help`  |
| rpm-install          | `fedora:41`                | `dnf install ./*.rpm`, then `--help`  |
| flatpak-run          | `ubuntu:24.04` + flatpak   | `flatpak install`, `flatpak run … --help` |
| snap-run             | `ubuntu:24.04` + snapd     | `snap install`, then `--help`         |
| windows-install      | `windows-2022`             | Silent install (`/SILENT`), check Start menu shortcut + run `--help` via shortcut target |

Any failure opens an issue on the canonical repo via `peter-evans/create-issue-from-file`.

---

## 10. Signing & Trust

| Artifact                  | Signing plan                                                  |
|---------------------------|---------------------------------------------------------------|
| GitHub Release files      | `SHA256SUMS` + `SHA256SUMS.asc` (GPG) signed by release key   |
| `.deb`                    | `dpkg-sig` with the same GPG key                              |
| `.rpm`                    | `rpm --addsign` with the same GPG key                         |
| Flatpak                   | Flathub signs at their end                                    |
| Snap                      | Snap Store signs at their end                                 |
| Windows `.exe`            | `signtool` with OV code-signing cert (EV upgrade in v1.1)     |
| macOS `.dmg` / `.app`     | **v1: unsigned.** Post-launch: Developer ID + notarization (see §11.4) |
| `install.sh`              | Optional GPG detached sig at `install.sh.asc`                 |

GPG key: create a long-lived `release@unicornviz.io` (or equivalent) key,
publish the public key in the repo (`docs/release-key.asc`) and on
`keys.openpgp.org`. Document fingerprint in `SECURITY.md`.

Code-signing cert acquisition (Windows OV cert, future Apple Developer ID)
is an owner-action item (not an agent task). The Windows `SignTool` and
macOS `codesign`/`notarytool` steps are both gated on their respective
secrets being present in CI \u2014 if a secret is unset, the job builds an
unsigned artifact and prints a loud WARN rather than failing the release.
This keeps the pipeline live during v1 and lets us flip each signature on
the day its cert lands.

---

## 11. macOS

First-class delivery target alongside Linux and Windows. v1 ships
**unsigned**; full Developer ID signing + notarization is deferred until
revenue is in (see §0 decisions).

### 11.1 Deliverables

- `UnicornViz-X.Y.Z.dmg` — drag-to-`/Applications` disk image containing
  `Unicorn Viz.app`, a `universal2` bundle (arm64 + x86_64) so a single
  artifact covers Apple Silicon and Intel Macs.
- A Homebrew **cask** in the `djunicorntears/homebrew-unicornviz` tap repo
  (Homebrew SOP: the repo must be named `homebrew-<tap-name>` so users can
  type `brew tap djunicorntears/unicornviz`). Install with:
  `brew tap djunicorntears/unicornviz && brew install --cask unicorn-viz`.
  The cask formula is auto-bumped by CI on each stable tag via
  `dawidd6/action-homebrew-bump-formula`.

### 11.2 Toolchain

- **[`briefcase`](https://briefcase.readthedocs.io/)** (BeeWare) is the
  primary bundler. It already understands macOS app bundles, code signing,
  notarization, and universal2 wheels, and supports our exact stack
  (Python + native deps + asset folders). `py2app` is a fallback if briefcase
  hits a wall with `python-rtmidi` or `moderngl`.
- Build on the `macos-14` GitHub runner (Apple Silicon, with `arch -x86_64`
  cross builds for the Intel slice via `delocate` and `lipo`).
- Embedded Python: `python-build-standalone` universal2 build, same family
  as the one we ship inside `.deb`/`.rpm`/Windows installer — keeps the
  runtime story uniform across all five desktop platforms.

### 11.3 Bundle structure

```
Unicorn Viz.app/
  Contents/
    Info.plist            CFBundleIdentifier = io.unicornviz.UnicornViz
                          LSMinimumSystemVersion = 12.0
                          NSMicrophoneUsageDescription = "Unicorn Viz captures audio for visualization."
                          NSCameraUsageDescription   = "Unicorn Viz uses the webcam for the webcam-01 drop-in."
    MacOS/UnicornViz      tiny launcher stub → runtime/bin/unicorn-viz
    Resources/
      unicorn-viz.icns    multi-resolution icon generated from assets/icons/unicorn-viz.png
      app/                unicornviz/ package + assets/ (core only — no drop-ins; see §6)
    Frameworks/
      Python.framework/   embedded universal2 Python 3.11
    runtime/              venv-equivalent with site-packages installed
```

### 11.4 Signing & notarization (v1: deferred)

v1 ships unsigned. The README's macOS section gets an unmissable "Right-click
open the first time" Gatekeeper workaround block, plus the `xattr -dr
com.apple.quarantine /Applications/Unicorn\ Viz.app` one-liner for users
who already double-clicked and got the quarantine bit.

When we revisit this post-launch:

- Developer ID Application certificate stored as a base64 secret
  (`MACOS_CERT_P12` + `MACOS_CERT_PASSWORD`).
- Sign with `codesign --options=runtime --entitlements packaging/macos/entitlements.plist`.
- Notarize with `xcrun notarytool submit --wait` using
  `APPLE_ID` / `APPLE_TEAM_ID` / `APPLE_APP_PASSWORD` secrets.
- Staple the ticket with `xcrun stapler staple` before producing the `.dmg`.
- The Windows-style "gated on cert presence in CI" pattern from §10 applies:
  if the macOS certificate secret is unset, the job builds an unsigned
  `.dmg` and prints a loud WARN. This keeps the pipeline live during v1
  and lets us flip the switch the day the cert lands.
- Required entitlements once we sign:
  - `com.apple.security.device.audio-input` (microphone for audio capture)
  - `com.apple.security.device.camera` (webcam drop-in)
  - `com.apple.security.device.usb` (USB-MIDI controllers)
  - `com.apple.security.cs.allow-jit` (moderngl shader compilation backends)
  - `com.apple.security.cs.disable-library-validation` (loading the bundled
    `python-rtmidi` / `sounddevice` dylibs that aren't signed by Apple)

### 11.5 Menu / dock integration

Native `.app` bundles get menu-bar, Dock, and Spotlight integration for free.
The unicorn avatar (`assets/icons/unicorn-viz.png`) is converted at build time
to a multi-resolution `.icns` (16, 32, 64, 128, 256, 512, 1024) via
`iconutil`. No extra desktop-entry plumbing needed.

### 11.6 Platform-specific runtime notes

- Audio: `sounddevice` uses CoreAudio on macOS. PipeWire-specific defaults in
  `config.toml` are already optional; the macOS-shipped `config.toml` template
  picks the default CoreAudio device.
- MIDI: `python-rtmidi` uses CoreMIDI. Works under sandbox with the
  `device.usb` entitlement above.
- OpenGL: macOS 10.14+ deprecated OpenGL. 3.3 core still works through the
  legacy compatibility layer on macOS 12–15, but Apple may remove it.
  **Risk to track:** moving the renderer to Metal via `moderngl-window`'s
  `pyglet`/`glfw`/MoltenGL path or a future Metal backend is a v1.2 concern,
  not blocking for v1.
- Wayland-only code paths must remain optional. Audit `unicornviz/app.py`
  and the drop-ins for Linux-only `os.environ` assumptions before the first
  macOS build.

### 11.7 Open Mac-specific risks

1. `python-rtmidi` wheels for `universal2` may not be on PyPI; if not, we
   compile from source in CI (adds ~2 minutes per build).
2. The webcam drop-in (`webcam-01`) uses OpenCV or a custom V4L2 path —
   confirm AVFoundation path exists, or guard the drop-in as Linux-only on
   macOS until ported.
3. Drop-ins that shell out to ffmpeg need the bundled ffmpeg binary copied
   into `Contents/Frameworks/ffmpeg` and added to `PATH` in the launcher stub.

---

## 12. Mobile (Android & iOS) — Feasibility Evaluation

**Recommendation: not planned for v1. Treat as a separate product line, not
a port.**

This section exists so we have a written assessment before someone asks
"why not just briefcase it?" The honest answer is that mobile is a
fundamentally different product, and the lift is well above what "installer
team" implies.

### 11.1 What technically works today

- **BeeWare briefcase** has Android (via Chaquopy) and iOS targets and can
  bundle a Python interpreter into both. Hello-world apps are real and ship.
- **Kivy / KivyMD** + **python-for-android** / **kivy-ios** also bundle
  Python apps into APK/IPA.
- **PyOpenGL ES** bindings exist on both platforms.

So a *Python visualizer* on mobile is not science-fiction. The hard parts
are what's specific to **our** stack and **our** product.

### 11.2 What does not port cleanly

| Subsystem            | Status on Android                       | Status on iOS                         |
|----------------------|-----------------------------------------|---------------------------------------|
| `moderngl` (GL 3.3 core, desktop GL) | ❌ Mobile is GLES 3.x — every shader needs rewriting (`#version 330` → `#version 300 es`, `texture2D` semantics, precision qualifiers, no `double`) | ❌ Same; plus Apple has deprecated GL in favor of Metal |
| `pysdl2` + `pysdl2-dll` | ⚠️ SDL2 builds for Android exist but the Python bindings + DLL wheel do not — would need a custom Gradle integration | ⚠️ Same, plus App Store review concerns around interpreted code |
| `sounddevice` (PortAudio) | ❌ No PortAudio backend; would need to swap to AAudio/OpenSL ES via a different library | ❌ No PortAudio; needs AVAudioEngine bridge |
| `python-rtmidi` (ALSA/CoreMIDI/WinMM) | ⚠️ Android MIDI is a totally different API (`android.media.midi`) — needs a new backend | ⚠️ iOS uses CoreMIDI but `python-rtmidi` is not packaged for iOS wheels |
| `numpy` / `scipy` FFT | ✅ Available via briefcase/kivy recipes | ✅ Available via kivy-ios recipes      |
| Fullscreen + always-on display | ⚠️ Trivial flag, but battery/thermals on a phone GPU running 60fps shaders for an hour is brutal | ⚠️ Same, plus iOS aggressively throttles background audio |
| ANSI / CP437 font asset | ✅ Pure-data, ships fine                | ✅ Same                                 |
| Drop-in submodule architecture | ⚠️ Runtime `importlib` from arbitrary paths conflicts with Android's APK assets model and iOS code-signing | ❌ Apple forbids downloading and executing new code post-install (drop-in hot-loading would not pass App Store review) |

### 11.3 Effort estimate (rough order of magnitude)

- **Android MVP** (one effect, audio-reactive from device mic, no MIDI,
  no drop-ins, GLES 3 port of the simplest shader, briefcase packaging):
  weeks of focused work, not days.
- **iOS MVP** with the same scope: same order of magnitude, plus Apple
  developer account, App Store review, and a Metal-or-MoltenGL decision.
- **Feature parity with desktop** (full drop-in catalog, MIDI, recording,
  postfx chains, control room): multi-month rewrite of the renderer and
  the audio/MIDI layer. Probably more code than the current desktop app.

### 11.4 If we ever do it

The right architecture is **not** "port the installer" — it's:

1. Extract a `unicornviz-core` package with shaders, palette logic, beat
   detection, scene sequencing, and ANSI rendering — anything that's not
   platform glue.
2. Build a thin mobile shell (likely Kotlin/Swift, or a Flutter/React Native
   wrapper if a JS/TS shader runtime is acceptable) that consumes
   `unicornviz-core` either via Chaquopy (Android) or by re-implementing
   the shader feed on the native side.
3. Ship a curated, sandbox-safe subset of effects. Drop-in hot-loading is
   off the table on iOS and impractical on Android.

Tracked as a future product spike under `docs/planning/mobile.md` when (and
if) we decide to invest.

### 11.5 What we will do now

- Keep `unicornviz/` core code reasonably platform-agnostic (no Linux-only
  imports at module load time outside guarded blocks).
- Avoid baking PipeWire / ALSA assumptions into shared modules.
- That's it. No mobile-specific installer work in this plan.

---

## 13. Documentation Updates

Once installer artifacts are live, rewrite the "Install" sections of:

- `README.md` — replace the manual `git clone` recipes with the one-liner,
  the `.deb`/`.rpm` download links, the Flathub badge, the Snap Store badge,
  and the Windows installer download link.
- `docs/user-guide.md` — same, with per-platform screenshots of the menu
  entry and the running app.
- `docs/configuration.md` — note where `config.toml` lives per install
  method (`~/.config/unicorn-viz/config.toml` for system installs;
  `<prefix>/config.toml` for portable / bash-installed; XDG portal location
  for sandboxed installs).

These doc updates are part of the same PR that lands each delivery channel,
not a separate cleanup pass.

---

## 14. Milestones

> **Superseded by §16 (2026-06-21).** This table is kept for history. It assumed
> an "installers team" and channel-at-a-time delivery. The active plan is the
> solo-dev, foundation-first roadmap in §16, which front-loads the shared
> `python-build-standalone` runtime and payload work so multiple channels reach
> ★3 together. Read §16 for current sequencing; treat the table below as the
> original sketch.

| Milestone | Scope                                                              | Exit criteria                                    |
|-----------|--------------------------------------------------------------------|--------------------------------------------------|
| **M1** — Bash installer    | §3 only                                          | `curl … \| bash` works on Ubuntu 22.04/24.04, Debian 12, Fedora 40/41, Arch; nightly smoke green |
| **M2** — Native packages   | §4                                               | `.deb` + `.rpm` for all matrix targets attached to a real tagged release; nightly install smoke green |
| **M3** — Windows installer | §8                                               | Signed (or clearly unsigned with warning) `.exe` produces a working Start-menu entry on Win10/Win11 |
| **M4** — macOS `.dmg`      | §11                                              | Unsigned universal2 `.dmg` installs into `/Applications`; Spotlight/Dock entry works on Apple Silicon and Intel; Homebrew cask published in `djunicorntears/homebrew-unicornviz`; README documents the Gatekeeper workaround. (Notarization deferred — see §0.) |
| **M5** — Flatpak           | §5.1                                             | Local `flatpak install` works end-to-end; Flathub submission PR open |
| **M6** — Snap              | §5.2                                             | `snap install --edge unicorn-viz` works under strict confinement |
| **M7** — Polish            | Signing, repo hosting, docs sweep, MSIX eval     | All channels signed; README rewritten; v1.0 tag |

Each milestone is one PR (or a small stack) so the canonical repo gets a
clean, reviewable history.

---

## 15. Open Questions for the Owner

*(Updated 2026-05-22 with answers. Items marked **OPEN** still need input.)*

1. ~~Public domain~~ — **Resolved:** `unicornviz.io` will be wired up;
   `get.unicornviz.io` redirects to the raw `install.sh` on the canonical
   repo. A second domain is planned (TBD). GitHub CLI plumbing for the
   `djunicorntears` org is parked until the correct GitHub account is the
   active login.
2. ~~Code-signing publisher name~~ — **Resolved:** `Unicorn Viz`.
3. ~~Snap / Flathub handle ownership~~ — **Action item, not yet resolved:**
   both `unicorn-viz` on Snap Store and `io.unicornviz.UnicornViz` on
   Flathub still need to be claimed. Blocks M5 and M6 ship.
4. ~~Bundle `python-build-standalone` everywhere?~~ — **Resolved: yes**, on
   every Linux package and every desktop installer.
5. ~~Drop-ins in release tarball?~~ — **Resolved: core only.** Drop-ins ship
   separately (see §6).
6. ~~Apple Developer ID for macOS notarization?~~ — **Resolved: deferred**
   post-launch. v1 ships an unsigned `.dmg` with Gatekeeper workaround docs.
7. **OPEN — macOS minimum version:** recommendation is macOS 12 (Monterey).
   Confirm or bump.
8. ~~Homebrew tap repo name~~ — **Resolved:**
   `djunicorntears/homebrew-unicornviz` (Homebrew SOP: the GitHub repo must
   be named `homebrew-<tap>`; the user-facing tap command is
   `brew tap djunicorntears/unicornviz`).
9. ~~Mobile in v1?~~ — **Resolved: no.** Android/iOS explicitly out of scope.

### Remaining owner action items (not blocking the plan, but blocking ship)

- Log in to GitHub CLI as the `djunicorntears` owner so release automation,
  Pages setup for the bash installer, and Homebrew tap creation can proceed.
- Register / claim:
  - DNS for `unicornviz.io` and the planned second domain.
  - `unicorn-viz` snap name on the Snap Store.
  - `io.unicornviz.UnicornViz` app ID on Flathub.
  - `djunicorntears/homebrew-unicornviz` GitHub repository.
- Decide macOS minimum version (Q7 above).

---

## 16. Solo-Dev Phased Roadmap to Five Gold Stars (2026-06-21)

This is the authoritative plan. It replaces the §14 milestone sketch. Design
constraints, stated plainly:

- **One person.** No parallel "teams." Phases are sequential and each ends in a
  shippable, reviewable PR (or small stack), per the repo's commit conventions.
- **No budget except, maybe, store/signing fees.** Every tool below is free on
  public-repo GitHub Actions (`ubuntu-latest`, `windows-2022`, `macos-14` are all
  free for public repos), plus free OSS packagers (`fpm`, Inno Setup, `briefcase`,
  `flatpak-builder`, `snapcraft`). The only spend is itemized in §17 and every
  paid item is deferrable behind the unsigned-but-documented escape hatch (§0.5.1).
- **Foundation first.** The two cross-cutting levers (bundled runtime + curated
  payload) are built once in Phase 0 so four channels climb to ★3 together.
- **Ship the cheapest reach first.** The Linux one-liner is already ★3 and reaches
  the widest audience for the least work, so it leads. Windows is the most users
  but the biggest rework, so it follows the runtime/payload foundation.

### Progress log

- **2026-06-30 — Phase 2 native packaging reworked + a real asset bug fixed.**
  - **Asset-resolution bug (found & fixed).** `unicornviz.paths.APP_ROOT` is
    `Path(__file__).resolve().parents[1]` — the parent of the package dir. A normal
    (non-editable) `pip install` puts the package in site-packages, so `APP_ROOT`
    became site-packages and `assets/` (shipped as a sibling of the package) was
    **not found at runtime**. The dev `.venv` is an *editable* install, which hid
    this, and `--help` can't trip it. Verified the failure with a clean install.
    Fix: `paths.py` now honors a `UNICORNVIZ_APP_ROOT` env override (default
    behavior unchanged when unset); both the native wrapper and the one-liner's
    launcher export it so assets resolve to the install prefix. Added
    `tests/test_paths_app_root.py`; full suite green (206 passed).
  - **`build_native.sh` reworked.** Stages via `stage_payload.sh` (drop-ins +
    licensed sims packs gone); bundles a relocatable `fetch_runtime.sh` interpreter
    and installs **only core deps** into it (not the project); ships the
    `unicornviz/` package and `assets/` as siblings under `INSTALL_ROOT` (default
    `/opt/unicorn-viz`);
    rewrites runtime shebangs from the staging path to the install path; `/usr/bin`
    wrapper sets `UNICORNVIZ_APP_ROOT` + `PYTHONPATH` and runs the bundled
    interpreter via `-m unicornviz`; `postinst`/`postrm` refresh desktop + icon
    caches. New `--install-root` and `--no-package` (stage-only) flags enable a
    local relocation test. **Verified on Fedora:** built a real
    `unicorn-viz-0.1.0-1.x86_64.rpm` (MIT, C-lib-only deps, no Python dep, no
    drop-ins, no `/etc` conffile); a relocated staging tree resolves `APP_ROOT`
    and finds assets; runtime shebangs point at `/opt` with 0 staging-path leaks.
  - **The `config.toml` conffile is the stopping point.** It is *not* shipped as a
    dpkg/rpm conffile yet — config is being cleaned up for distribution by a
    separate effort. `config.full.example.toml` ships as documentation in the
    interim; the conffile + `--config-files` wiring lands once distribution-ready
    config exists.
  - `installer-smoke.yml`: `build_native.sh` added to the shellcheck gate.
    `release-installers.yml`: rpm job now installs `curl`/`tar` (for the runtime
    download) instead of system Python.
- **2026-06-21 — Bundling system + Linux low-hanging fruit landed.**
  - `tools/packaging/fetch_runtime.sh`: the shared "bundling system." Downloads a
    pinned `python-build-standalone` interpreter (CPython 3.11.10, PBS `20241016`),
    verifies it against the upstream `.sha256` sidecar, extracts it, and prints the
    interpreter path. Autodetects or accepts `--os`/`--arch` (Linux/macOS/Windows
    × x86_64/aarch64/universal2) so Phases 2–4 can reuse it unchanged. Pin is
    env-overridable (`UV_PBS_RELEASE`, `UV_PBS_PYVER`) and **must be re-confirmed
    against upstream before each release** (a wrong pin 404s loudly).
  - `tools/install/lib.sh`: added `uv_provision_runtime` + `uv_install_runtime_and_app`
    (locates `fetch_runtime.sh` in a clone, or curl-bootstraps it for the
    `curl | bash` path); `set -Eeuo pipefail` + `uv_err_trap`; upgraded the
    `.desktop` to the canonical entry (§7) with `GenericName`/`Keywords`/
    `StartupWMClass`/full `Categories`.
  - `install.sh` and `tools/install_linux.sh`: **bundled runtime is now the
    default** for both (the dev-clone installer too, per owner decision). Added
    `--system-python` to opt out. Dev clone puts the runtime in `.venv-runtime/`
    (gitignored) and still builds `.venv/` so `run.sh` is unchanged.
  - `installer-smoke.yml`: added a `shellcheck` gate and bundled/`--system-python`
    dry-run coverage.
  - Verified end-to-end: `fetch_runtime.sh` downloads + checksum-verifies + extracts
    a working CPython 3.11.10 that builds a venv; all installer dry-runs pass.
- **2026-06-29 — Phase 0 foundations completed.**
  - `tools/packaging/stage_payload.sh`: the curated payload stager. Allowlist copy
    of `unicornviz/`, `assets/`, `config.full.example.toml`, `requirements.txt`,
    `pyproject.toml`, `README.md` (+ `LICENSE` when present); excludes bytecode,
    `.DS_Store`, and **all licensed `assets/sims/` packs** (keeps the placement
    README); fails loudly if a required member is missing or if a forbidden tree
    (`.git`, `.venv`, `logs`, `docs`, `drop-ins`, `tests`, `build`, …) or a sims
    pack subdir leaks in. Verified: a dev-tree run drops 115M → 44M and the leak
    guards hold.
  - `lib.sh`: added `uv_sudo` (runs directly as root, else via sudo, else dies) so
    the real-install smoke works in root CI containers; `uv_install_system_deps`
    now routes every privileged call through it.
  - `installer-smoke.yml`: now runs **nightly** (`schedule:`). The fast job adds a
    `stage_payload.sh` smoke (asserts no `.git`/`drop-ins`/`docs` leak); a new
    `real-install` matrix does a **full clean-container install** of
    `tools/install_linux.sh` (bundled runtime + system deps) on `ubuntu:24.04`,
    `fedora:41`, and `archlinux:latest`, then asserts `unicorn-viz --help`. This
    is the ★4 install gate for the Linux channels.
- **Still open (validation):** the **release path** (`install.sh` resolving a real
  GitHub release → tarball → checksum) is still only dry-run-tested because no
  release exists yet; validate it against a one-off test release. Also: add a
  `LICENSE` file (MIT is declared in `pyproject.toml` but no license text ships).

### Sequencing at a glance

| Phase | Outcome | Channels moved | Rough effort |
|-------|---------|----------------|--------------|
| **P0 — Foundations** | Shared `python-build-standalone` fetcher + curated payload stager + CI hardening (shellcheck, real smoke harness) | unblocks ★3 for one-liner, deb/rpm, Windows, macOS | Medium |
| **P1 — Linux one-liner → ★5** | Bundled runtime, full `.desktop`, GPG sig, nightly smoke, vanity URL | one-liner | Small |
| **P2 — Native deb/rpm → ★5** | Relocatable bundled runtime, core-only, conffile, matrix, signed | deb, rpm | Medium |
| **P3 — Windows → ★5** | Curated payload + embedded Python + ffmpeg, real installer, CI smoke, signing gated | Windows | Large |
| **P4 — macOS → ★5** | briefcase universal2 dmg, Homebrew cask, Gatekeeper docs | macOS | Large |
| **P5 — Flatpak → ★5** | Offline pip, tight sandbox, metainfo, Flathub | Flatpak | Medium |
| **P6 — Snap → ★5** | core24, strict confinement, desktop, Snap Store | Snap | Medium |
| **P7 — Drop-in system + polish** | `dropin.toml` + `unicorn-viz dropins` CLI, official pack, docs sweep, v1.0 tag | all | Large |

### Phase 0 — Foundations (do these once, everything else depends on them)

1. **`tools/packaging/fetch_runtime.sh`** — ✅ **Done (2026-06-21).** Downloads and
   checksum-verifies the correct `python-build-standalone` build for a given
   OS/arch (Linux x86_64/arm64, Windows x64, macOS universal2/arm64/x86_64). One
   helper, consumed by P1–P4. Release tag + version are pinned (env-overridable),
   not floating; download is verified against the upstream `.sha256` sidecar.
2. **`tools/packaging/stage_payload.sh`** — ✅ **Done (2026-06-29).** Produces a
   curated payload dir (`unicornviz/`, `assets/`, `config.full.example.toml`,
   `requirements.txt`, `pyproject.toml`, `README.md`, + `LICENSE` when present)
   with an explicit allowlist so `.git`, `.venv`, `logs/`, `recordings/`,
   `screenshots/`, `docs/`, `drop-ins/`, and licensed sims packs can **never**
   leak into a shipped artifact (enforced by post-stage leak guards).
   Windows/macOS/native will all call it.
3. **CI hardening (free):**
   - ✅ **Done (2026-06-21):** `shellcheck` gate added to `installer-smoke.yml`
     over `install.sh`, `tools/install/*.sh`, and the packaging scripts.
   - ✅ **Done (2026-06-29):** `installer-smoke.yml` now runs **nightly**
     (`schedule:`) with a `real-install` matrix that installs into clean
     containers (`ubuntu:24.04`, `fedora:41`, `archlinux:latest`) and asserts
     `unicorn-viz --help`. The ★4 install gate for the Linux channels. The
     **release-path** install (`install.sh` against a tagged release) still needs
     a one-off validation once a test release exists.
4. **Runtime story for the one-liner:** ✅ **Resolved (2026-06-21).** Both the
   public `install.sh` **and** the clone-local `tools/install_linux.sh` default to
   the bundled `python-build-standalone` runtime (owner decision). `--system-python`
   opts out for contributors who want their own interpreter.

**Exit criteria:** `fetch_runtime.sh` and `stage_payload.sh` exist with unit-ish
smoke tests; shellcheck + nightly real-install smoke are green on `master`.

### Phase 1 — Linux one-liner → ★5 (smallest lift, widest reach)

- ✅ **Done (2026-06-21):** adopted `fetch_runtime.sh` — installs into
  `<prefix>/runtime` and builds the venv from the bundled interpreter; the hard
  `python3` requirement is dropped (system Python only via `--system-python`).
- ✅ **Done (2026-06-21):** replaced the trimmed `.desktop` in `lib.sh` with the
  canonical §7 entry (`GenericName`, `Keywords`, `StartupWMClass`, full
  `Categories`).
- ✅ **Done (2026-06-21):** `set -Eeuo pipefail` + an `ERR` trap (`uv_err_trap`)
  that prints the failing command/line, across `install.sh`, `lib.sh`, and
  `tools/install_linux.sh`.
- **Still open:** generate + install the icon size ladder (48–512) at install
  time (needs ImageMagick best-effort, fall back to the single 256px icon).
- **★4:** the Phase 0 nightly container smoke covers this (still to be built).
- **★5:** owner generates the `release@unicornviz.io` GPG key; CI signs
  `SHA256SUMS` → `SHA256SUMS.asc` and publishes `install.sh.asc`; wire
  `get.unicornviz.io` → raw `install.sh` (owner DNS action, free-ish — see §17).

### Phase 2 — Native `.deb` / `.rpm` → ★5

- ✅ **Done (2026-06-30):** use the bundled `python-build-standalone` runtime
  instead of a host-linked venv; runtime shebangs rewritten from the staging path
  to the final `/opt/unicorn-viz/...` path (verified 0 leaks). Deps install into
  the bundled interpreter; the app ships as source + assets siblings and runs via
  `-m unicornviz` with `UNICORNVIZ_APP_ROOT` set (fixes asset resolution).
- ✅ **Done (2026-06-30):** **drop-ins stripped** (now staged via
  `stage_payload.sh`, which excludes them and the licensed sims packs).
- ✅ **Done (2026-06-30):** `postinst`/`postrm` refresh desktop + icon caches.
  (No symlink to clean up anymore — `/usr/bin/unicorn-viz` is a package-owned
  wrapper that fpm removes on uninstall.)
- ⛔ **Stopping point — `config.toml` conffile DEFERRED.** Shipping `config.toml`
  as a dpkg/rpm conffile at `/etc/unicorn-viz/` (with fpm `--config-files` so
  upgrades preserve edits) is **blocked on the config being cleaned up for
  distribution** by a separate effort. Until then, `config.full.example.toml`
  ships as documentation under `/usr/share/doc/unicorn-viz/`.
- **Still open for ★4:** build **inside per-distro containers** (matrix:
  `ubuntu:22.04`/`24.04`, `debian:12` → deb; `fedora:40`/`41` → rpm) and add a
  nightly `apt install ./*.deb` / `dnf install ./*.rpm` smoke in clean containers.
  (The runtime is downloaded per-arch, so the host distro matters less than before,
  but matrix coverage still validates the C-lib dependency names.)
- **★5:** `dpkg-sig` (deb) and `rpm --addsign` (rpm) with the same GPG key from P1.
  (APT/DNF GitHub-Pages repos remain a post-v1 nicety, §4.4.)

### Phase 3 — Windows → ★5 (biggest rework; most users)

- **Kill the anti-pattern.** Delete the blanket `Source: "{#RepoRoot}\*"` copy and
  the postinstall network pip install. Replace with: `stage_payload.sh` output +
  `fetch_runtime.sh` embedded Python 3.11 + a bundled static ffmpeg, all staged at
  build time on `windows-2022` CI, then `ISCC.exe /DAppVersion=${VERSION}`.
- Real integration: Start-menu + optional desktop/taskbar shortcuts, PATH registry
  entry with the `NeedsAddPath` guard, proper uninstaller, `AppUserModelID` set in
  `app.py` for correct taskbar icon grouping (§8.5).
- Produce `UnicornViz-Portable-${VERSION}.zip` from the same payload.
- Move `tools/install_windows*.{bat,ps1}` + the GUI scripts under
  `tools/dev/windows/` and mark them developer-only; end users never see them.
- **★4:** CI builds the `.exe` and runs a silent-install (`/SILENT`) smoke that
  launches the Start-menu target with `--help`.
- **★5 (no cert yet):** wire the `signtool` step behind a `WINDOWS_CERT` secret
  gate (§10) — until a cert is bought, CI builds **unsigned** + prints a loud WARN,
  and the README documents the one-click SmartScreen "More info → Run anyway"
  path. Buy an OV cert post-revenue to flip it on (§17).

### Phase 4 — macOS → ★5 (currently nonexistent; unsigned v1)

- Stand up `briefcase` (BeeWare) as the bundler; `py2app` fallback if
  `python-rtmidi`/`moderngl` resist. Universal2 (arm64 + x86_64) so one `.dmg`
  covers Apple Silicon + Intel.
- Embed `python-build-standalone` universal2 via `fetch_runtime.sh`; generate
  `.icns` from `assets/icons/unicorn-viz.png`; set Info.plist usage strings
  (`NSMicrophoneUsageDescription`, `NSCameraUsageDescription`).
- Audit `unicornviz/app.py` + drop-ins for Linux-only `os.environ`/PipeWire
  assumptions before the first build (§11.6).
- **★4:** `macos-14` CI build produces the `.dmg` + a launch-`--help` smoke.
- **★5 (unsigned escape hatch):** Homebrew **cask** in
  `djunicorntears/homebrew-unicornviz` (free; auto-bumped by CI) + README
  Gatekeeper block (right-click-open + `xattr -dr com.apple.quarantine`). Wire
  `codesign`/`notarytool` behind the Apple-cert secret gate now; turn it on when
  the $99/yr Apple Developer Program is purchased post-revenue (§17).

### Phase 5 — Flatpak → ★5

- Generate `python3-requirements.json` from `requirements.txt` via
  `flatpak-pip-generator` and commit it (Flathub forbids network during build);
  add native-wheel build deps (`libffi`, `alsa-lib`, `portaudio`) as `modules:`.
- Tighten `finish-args`: drop `--filesystem=home` and `--share=network`, switch
  `--socket=pulseaudio` → `--socket=pipewire`, add `xdg-music:ro`/`xdg-videos:ro`/
  `xdg-pictures:ro` + `xdg-config/unicorn-viz:create`, `--device=dri`
  (+`--device=input` for MIDI). Base runtime `24.08`.
- Add `io.unicornviz.UnicornViz.metainfo.xml` + `.desktop` + icon ladder under
  `packaging/flatpak/data/`.
- **★4:** `bilelmoussaoui/flatpak-github-actions/flatpak-builder@v6` CI build +
  `flatpak run … --help` smoke.
- **★5:** Flathub submission PR (free; **owner must claim the
  `io.unicornviz.UnicornViz` app-id** first — §0 action item).

### Phase 6 — Snap → ★5

- `base: core24`, move `devmode` → **strict** with explicit plugs (`opengl`,
  `wayland`, `x11`, `audio-record`, `audio-playback`, `alsa`, `removable-media`,
  `raw-usb` for MIDI), `grade: stable`.
- Add a `desktop-launch` wrapper + `meta/gui/unicorn-viz.{png,desktop}` for menu
  integration.
- **★4:** `snapcore/action-build@v1` CI + `snap install`/`--help` smoke.
- **★5:** `snapcraft upload --release=stable` (free; **owner must register the
  `unicorn-viz` snap name** first — §0 action item).

### Phase 7 — Drop-in dependency system + polish (close out v1.0)

- Build §6 for real: `dropin.toml` in every `drop-ins/*`, the
  `unicorn-viz dropins {list,check,install,doctor}` CLI, `tools/lint_dropin.py`,
  and boot-time gating that surfaces missing-dep warnings in the `H` overlay.
- Define `packaging/dropins/official-bundle.toml` + the optional per-platform
  "install official drop-in pack" affordance (§6.5).
- Docs sweep (§13): rewrite README install section with the one-liner, download
  links, and Flathub/Snap badges; update `user-guide.md` and `configuration.md`
  for per-install `config.toml` locations. Tag **v1.0**.

### Definition of done for "five gold stars, all platforms"

All six channels (one-liner, deb/rpm counted together as "native", Windows,
macOS, Flatpak, Snap) sit at ★4 minimum with a documented, owner-gated path to
★5, and at least the four desktop channels with zero signing cost
(one-liner, deb/rpm, Flatpak, Snap) are at a full ★5. Windows + macOS bank ★5
via the unsigned-but-documented escape hatch until certs are funded.

---

## 17. Money Ledger — Free vs. Paid (2026-06-21)

The brief is "we're doing everything ourselves and not paying for anything except
maybe store submissions." Here is exactly what that buys and what it doesn't.

### Free (use these; the whole roadmap runs on them)

| Item | Notes |
|------|-------|
| GitHub Actions CI | `ubuntu-latest`, `windows-2022`, `macos-14` all free for **public** repos. The canonical release repo must be public to keep this free. |
| `fpm`, Inno Setup, `briefcase`, `flatpak-builder`, `snapcraft` | All OSS / free for our use. |
| `python-build-standalone` | Free, redistributable (PSF/BSD-family). |
| Flathub submission & hosting | Free. Needs the app-id claimed (owner action, no fee). |
| Snap Store publishing | Free. Needs the snap name registered (owner action, no fee). |
| Homebrew tap (`homebrew-unicornviz`) | Free; just a public GitHub repo. |
| GPG signing (deb/rpm/checksums) | Free; owner generates one key. |
| GitHub Pages (future APT/DNF repos) | Free. |

### Paid (all deferrable; ship unsigned + documented until funded)

| Item | Cost | Blocks | Workaround until paid |
|------|------|--------|-----------------------|
| Apple Developer Program | **$99/yr** | macOS notarization (silent Gatekeeper pass) | Unsigned `.dmg` + README right-click-open + `xattr` one-liner (§11.4). macOS still reaches ★5 via the escape hatch. |
| Windows code-signing cert (OV) | **~$200–400/yr** | SmartScreen-clean `.exe` | Unsigned `.exe` + documented "More info → Run anyway" (§10). Windows still reaches ★5 via the escape hatch. EV cert is a later upgrade. |
| `unicornviz.io` domain | **~$12/yr** | `get.unicornviz.io` vanity URL only | Use the raw `raw.githubusercontent.com/.../install.sh` URL; vanity is cosmetic. |
| Microsoft Store dev account | **$19 one-time** | MSIX Store listing | Out of v1 scope (§8.6, v1.2). Not needed for the `.exe`. |

**Bottom line:** the entire five-star roadmap can ship for **$0** using the
unsigned escape hatch on Windows/macOS. The first dollar worth spending, once
there is revenue, is the **Apple $99/yr** (best trust-per-dollar — it removes the
scariest first-run wall), then a **Windows OV cert**. A domain is optional polish.
No payment is on the critical path to "five gold stars."
