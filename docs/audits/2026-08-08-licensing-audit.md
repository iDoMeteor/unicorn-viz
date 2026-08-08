# Unicorn Viz — Licensing & Third-Party Code Audit (2026-08-08)

Owner: core manager (agent) + owner
Status: Complete — findings 3, 4, 5 remediated; findings 1, 2, 6, 9 open (owner decision)
Last updated: 2026-08-08

Scope: every third-party thing the project depends on, links to, ships, or
downloads — Python packages (core + drop-in), native libraries, bundled fonts,
ANSi art, USD asset packs, MilkDrop presets, audio corpora, external binaries,
and the packaging manifests. Licensing only; no security or quality review.

Method: read `requirements.txt`, `pyproject.toml`, all seven drop-in
`requirements.txt` files, installed distribution metadata in `.venv`
(including the third-party notices embedded in binary wheels), `git ls-files`
for every tracked binary asset, `.gitignore` rules for untracked packs, and a
source sweep for external-binary invocation, `ctypes` library loading, and
attribution comments.

Per project policy, license findings are reported and the owner decides. The
original report proposed remediation without applying any; on 2026-08-08 the
owner approved and the agent applied findings **3** (attribution file), **4**
(stray MilkDrop preset) and **5** (ACiD art credits), plus the Windows
installer fix from recommendation 3. Those sections are marked RESOLVED
in place, with what was done. Everything else is untouched and still the
owner's call.

---

## The short version

The project is MIT-licensed and the great majority of what it depends on is
permissive (MIT / BSD / Apache) and imposes nothing beyond keeping copyright
notices around. **There is no problem at all as long as unicorn-viz stays a
source project people install themselves.**

The picture changes the moment you ship a bundle — the Flatpak, the Snap, the
Windows installer, or any paid/closed distribution. Three things are the real
issues, in order:

1. **`essentia` is AGPL-3.0.** This is the strongest copyleft license there is,
   and it is the only finding that could force you to open-source your own code.
2. **`mutagen` is GPL-2.0-or-later, and VLC (behind `python-vlc`) is GPL-2.0.**
   Both are drop-in dependencies. GPL is viral across a shipped bundle.
3. ~~**You ship no attribution file.**~~ **Fixed 2026-08-08.** Dozens of
   MIT/BSD/Apache dependencies each require their copyright notice to travel
   with any binary you distribute, and nothing did. `THIRD_PARTY_LICENSES.md`
   is now generated and installed by all three packaging targets.

A fourth, discovered while checking upstream after the first pass: **Demucs
model weights are CC BY-NC 4.0** (Finding 9). It is the only item here that
restricts *use* rather than distribution, so it does not care that operators
download the weights themselves — it lands squarely on any paid product or paid
performance driven by stem separation.

Then a set of smaller items, two of them now closed: a stray MilkDrop preset
committed by accident (fixed), an ACiD art collection whose copyright belongs to
named artists (now credited), and a CP437 font blob with no recorded provenance
(open).

**Overall grade: B−.** Clean intent, visibly careful in places (the NVIDIA asset
packs and the projectM presets are deliberately git-ignored; the Traktor mapping
has an explicit "no Mixxx code was copied" note). What's missing is the
distribution-side paperwork and a decision about the three copyleft libraries.

---

## Finding 1 — `essentia` is AGPL-3.0-only (highest severity)

**Where:** imported at runtime in `drop-ins/spotify-01/spotify_controller.py:1062`
and `drop-ins/training-kit-01/tools/training/training_lib.py:476`.

**Plain English:** AGPL is the "network copyleft" license. Ordinary GPL only bites
when you hand someone a copy of the software. AGPL also bites when users merely
*interact with it over a network* — the classic trigger being a hosted service.
If AGPL code is judged to be part of one combined program with yours, the whole
combined work has to be offered under AGPL, source included.

Python `import` is about as combined as it gets: same process, same address space,
direct function calls. The `try/except ImportError` guard makes essentia optional,
which genuinely helps — a build that never has essentia present isn't a combined
work — but the code that calls into it is written against essentia's API and
shipped in your repository, and that is the fact pattern the FSF reads as
derivative.

**What it actually means for you:**

- Running it locally on your own machine: **completely fine.** AGPL only triggers
  on distribution or network interaction.
- Shipping essentia inside the Flatpak/Snap/installer: you would need to release
  unicorn-viz (at minimum spotify-01 and training-kit-01) under AGPL-3.0.
- Any future hosted/streaming/SaaS angle where users touch it over a network:
  AGPL applies even without shipping a file.
- **This is incompatible with ever selling this as closed source.** Given the
  project positioning ("no paid competitor ships on Linux"), that matters.

**Mitigating detail:** essentia is not in *any* `requirements.txt` — not core, not
spotify-01, not training-kit-01. It is an undeclared optional import that only
activates if the operator happens to have it installed. That is a much weaker
position for a copyright claim, and it means today's shipped artifacts contain no
AGPL code. It is also, frankly, an accident rather than a decision.

**Options (owner's call):**

1. Drop the essentia paths and use the in-house BPM/key detection that
   `beat_grid.py` already provides. Cleanest.
2. Keep it, declare it honestly as an optional operator-installed extra, never
   bundle it, and document that installing it makes that operator's combination
   AGPL.
3. Move it behind a subprocess boundary (separate process, data over a pipe).
   This is the standard arm's-length argument and is much stronger than
   `import`, though not free of doubt.
4. Accept AGPL for the whole project.

## Finding 2 — GPL dependencies in shipped drop-ins

| Package | License | Where | Declared |
| --- | --- | --- | --- |
| `mutagen` | GPL-2.0-or-later | media-01, dj-mixer-01 (tags) | Yes — both `requirements.txt` |
| `python-vlc` | LGPL-2.1+ *(bindings)* | media-01 playback | Yes — `media-01/requirements.txt` |
| libVLC itself | **GPL-2.0** | loaded by `python-vlc` | Implicit |

**Plain English:** GPL-2.0 says that if you distribute a program that includes or
links GPL code, the entire program must be distributed under GPL-2.0 with source.
Same shape as AGPL minus the network trigger.

`mutagen` is the straightforward one — a pure-Python GPL library, imported
directly. It is genuinely optional in dj-mixer-01 (guarded import, used only to
show "Artist - Title" in the browser); in media-01 it is a declared requirement.

`python-vlc` is subtler and worth getting right. The *bindings* are LGPL-2.1+,
which is fine — LGPL permits linking from non-free code. But the bindings are a
thin `ctypes` shim onto **libVLC, which VideoLAN licenses as GPL-2.0**. So the
binding's permissive-ish license buys you nothing if you ship the VLC runtime; a
bundle containing VLC is a GPL bundle.

**What it actually means:**

- Users installing VLC themselves and unicorn-viz merely finding it: fine. This
  is the "mere aggregation on the user's system" case, and it is how media-01
  works today (`import vlc` inside a guard, nothing bundled).
- Bundling VLC into the Flatpak/Snap/installer: the bundle becomes GPL-2.0.
- Shipping `mutagen` in the bundle (which `pip install -r` inside the Snap build
  would do): same result via a much smaller library.

**Note on the Snap:** `packaging/snap/snapcraft.yaml` builds from `requirements.txt`
only — core deps, all permissive. Drop-in requirements are not pulled in, so
today's Snap is clean. The Windows installer was the one to watch: it did
`Source: "{#RepoRoot}\*"` with `recursesubdirs`, i.e. it swept in **everything**
in the working tree, including any drop-in and any stray file — a licensing
hazard on top of being a packaging hazard. **Fixed 2026-08-08:** the sweep now
carries an `Excludes:` list covering restricted third-party assets
(`assets\sims\`, projectM `presets\` and `preset-trash\`, drop-in `vendor\`),
operator secrets and runtime state (`.env`, `runtime\`, `logs\`, `recordings\`),
and build/VCS junk. `assets\sims\README.md` is re-added explicitly so operators
still get the instructions for fetching the restricted packs themselves.

Note that this exclusion list is the *only* thing standing between a
filesystem sweep and a restricted asset — Inno Setup does not read
`.gitignore`. Anything newly git-ignored for licensing reasons has to be added
here too.

**Options:** keep both strictly as operator-installed extras and never bundle
them (the status quo, just made explicit); or replace `mutagen` with a small
in-house tag reader — ID3v2 and Vorbis comments are not hard, and it removes the
only GPL library you'd realistically want in a bundle.

## Finding 3 — No third-party attribution file — **RESOLVED 2026-08-08**

**Plain English:** MIT, BSD, and Apache-2.0 all ask for essentially one thing in
exchange for unlimited use: when you distribute the software in binary form, the
copyright notice and license text must come with it. This is the cheapest
obligation in open source and the most commonly missed.

The repository has exactly one license file — its own `LICENSE`. There is no
`NOTICE`, no `THIRD_PARTY_LICENSES`, no credits page. The three packaging
manifests do not reference or install one either.

Every bundle you have produced or will produce carries dozens of these notices
unfulfilled: numpy, scipy, moderngl, Pillow, psutil, sounddevice, soundfile,
python-rtmidi, PySDL2, opencv, and everything they pull in.

Special cases worth calling out inside that list:

- **`pysdl2-dll` ships prebuilt SDL2 binaries** with twelve separate license
  files (SDL2 zlib, plus dav1d, libavif, gme, ogg/vorbis, and others). Each has
  its own attribution requirement.
- **`opencv-python-headless` bundles FFmpeg**, which its own
  `LICENSE-3RD-PARTY.txt` documents as LGPL. LGPL adds a requirement beyond
  attribution: users must be able to replace the LGPL library with their own
  build. Dynamic linking in a bundle satisfies this; static linking would not.
- **PyAV wheels bundle a full LGPL FFmpeg stack** (`libavcodec`, `libavformat`,
  `libmp3lame`, `libopus`, `libSvtAv1Enc`, …) — I checked, and the build carries
  no GPL components such as x264, so it is LGPL-clean. Same replaceability
  requirement.
- **`certifi` and `tqdm` are MPL-2.0.** MPL is file-level copyleft: modify one of
  their files and that file must stay MPL. Use them unmodified and there is no
  obligation beyond attribution. You use both unmodified.
- **`usd-core` is under `LicenseRef-TOST-1.0`** — Pixar's modified Apache 2.0.
  Permissive, but it is a non-standard license that automated scanners will flag,
  and it has its own attribution clause.

**What was done (2026-08-08):**

- `tools/gen_third_party_licenses.py` generates `THIRD_PARTY_LICENSES.md` from
  installed distribution metadata. It walks the transitive runtime closure of
  `requirements.txt` (16 packages), excludes dev-only tooling that never
  reaches a user, and emits a summary table plus the **full license text** of
  every license file each wheel ships — so pysdl2-dll's twelve bundled-library
  notices and numpy's twenty vendored ones are all reproduced verbatim. It
  falls back to the metadata `License` field for projects that ship no license
  file (python-osc, which is Unlicense/public domain). `--check` exits non-zero
  when the committed file is stale, so it can gate a release.
- All three packaging targets now install it:
  - **Flatpak** — `install -Dm644` into
    `/app/share/licenses/io.unicornviz.UnicornViz/`, alongside `LICENSE`.
  - **Snap** — a `licenses` dump part organizing both files into
    `usr/share/doc/unicorn-viz/`; the snap also now declares `license: MIT`,
    which it previously did not.
  - **Windows** — both files installed into `{app}`, and `LicenseFile` set so
    the installer displays the MIT terms during setup.

Regenerate with `.venv/bin/python tools/gen_third_party_licenses.py` whenever
`requirements.txt` pins move, and commit the result. Run it from the validated
virtualenv — the file is meant to describe the environment actually shipped.

Optional drop-in dependencies are listed by name in a clearly-marked advisory
section without license text, because they are operator-installed and are not
part of any bundle produced here. If that ever stops being true — if a bundle
starts shipping drop-in dependencies — that section must become full texts, and
findings 1, 2 and 9 have to be resolved first.

## Finding 4 — One MilkDrop preset committed by accident — **RESOLVED 2026-08-08**

**Where:** `drop-ins/projectm-01/preset-trash/Collaboration Milk Celebration AdamFX …ateFT flexi - divine struggle….milk`

The projectM drop-in handles presets carefully and correctly: `presets/` is
git-ignored, the ~10,300 presets on your disk are fetched locally, and none are
tracked. Exactly one file escaped, into a `preset-trash/` directory that isn't
covered by the ignore rule.

**Plain English:** MilkDrop presets are a genuinely murky area, and the pack's own
`LICENSE.md` says so out loud — presets were "in almost all cases, not released
under any specific license," each author holds full copyright, and the projectM
team's position is a good-faith assumption of public domain plus a takedown
offer. That is a norm, not a license grant.

This one file is a collaboration credited to several named authors in its own
filename. Low practical risk, trivially fixed, and it undercuts the otherwise
clean posture.

**What was done (2026-08-08):** the file was untracked with `git rm --cached`
(it stays on disk — it is a real culled preset and the runtime uses that
directory), and `preset-trash/` was added to `drop-ins/projectm-01/.gitignore`
next to `presets/`, with a comment recording *why* both are excluded so the
next person does not "helpfully" commit them back.

## Finding 5 — ACiD Productions ANSi art — **RESOLVED 2026-08-08**

**Where:** `assets/ansi/acid/*.ANS`, fetched by `tools/fetch_acid_ans.py` from
16colo.rs and committed to the repo. CLAUDE.md documents this as intentional.

Every file carries a SAUCE record naming its author and group — Ghengis, Sensei,
King Midas, Nitnatsnoc, Pharcyde, Kitiara, Reanimator, Offset, Devil Angel,
Maytag, Mr. Self Destruct — all under ACiD Productions, 1996–1997.

**Plain English:** these are copyrighted artistic works by identifiable people.
The artscene has a strong, decades-old norm of free circulation, and 16colo.rs
exists to archive and distribute them; nobody in that world objects to a
visualizer displaying ACiD art. But norm is not license, and the SAUCE records
prove you know who the authors are.

Practical risk is very low and drops further with attribution.

**What was done (2026-08-08):** `assets/ansi/README.md` now credits all
eighteen pieces in a table generated from their SAUCE records — file, title,
artist, group and release date — with links to the three source packs on
16colo.rs. It states plainly that copyright remains with the individual
artists, that the art is **not** covered by this project's MIT license, that
unicorn-viz claims no rights in it, and that inclusion rests on the artscene's
circulation convention rather than a license grant. It also carries a standing
offer to remove any piece at its author's request, and tells future
contributors to regenerate the credits from SAUCE rather than typing them by
hand.

The same file distinguishes the seven hand-made `.ans` files in the directory
root, which are original project work generated by `tools/generate_ansi_art.py`
and covered by the project's MIT license, and notes that their demoscene titles
(Future Crew, Razor 1911) are homage rather than claims of affiliation.

**Still open:** if you ever go commercial with a bundled installer, revisit
this. Artscene tolerance for free tools is not the same as tolerance for paid
products, and attribution does not by itself create a right to redistribute.

## Finding 6 — CP437 font blobs have no recorded provenance

**Where:** `assets/fonts/font8x16.bin` (4,096 bytes) and `font8x8.bin` (1,024
bytes) — raw IBM VGA-style bitmap glyph data, 256 glyphs each.

There is no README, no generator script, and no note in the commit that added
them (`be8885e`) saying where they came from.

**Plain English:** in the US, bitmap fonts are generally held not to be
copyrightable — the glyph shapes are a typeface (not protected) and the bitmap is
data rather than a program. In the EU and elsewhere, typefaces can be protected.
The realistic concern isn't IBM circa 1987; it's that many circulating copies of
these fonts are extracted from **The Ultimate Oldschool PC Font Pack**, which is
CC BY-SA 4.0 — a share-alike license that would require attribution and would
propagate to derivatives.

You almost certainly can keep using these. But you can't currently *say* where
they came from, which is the actual problem. Record the provenance now while
whoever added them might still remember; if the answer turns out to be the
Oldschool pack, add the CC BY-SA attribution and move on.

**By contrast, `ui-font.ttf` is exemplary and needs nothing:** it's Liberation
Mono Regular, SIL Open Font License 1.1, Red Hat/Google copyright, all notices
intact inside the file. OFL only requires that you not sell the font by itself
and not use the reserved name on a modified version. Both are satisfied.

## Finding 7 — Correctly-handled items (no action needed)

These deserve recording because they were done right, and the reasoning should
survive.

- **NVIDIA Reallusion USD characters** — `assets/sims/README.md` correctly
  identifies the NVIDIA Omniverse License Agreement as restricting
  redistribution, and `.gitignore` keeps every pack out of the repo while
  tracking only the README. The packs are on your disk, untracked, which is
  exactly right. Each operator downloads their own. **Watch the Windows
  installer**, whose `RepoRoot\*` sweep would happily package them.
- **MuJoCo Menagerie robots** — Apache-2.0, `CREDITS.txt` auto-generated with
  upstream URLs, output git-ignored. Correct.
- **libfunnel** (video-out-01 vendored native dep) — MIT, pinned to commit
  `779586d`, built locally into an ignored `vendor/`. Correct.
- **Traktor S4 MK3 mapping** — `drop-ins/dj-mixer-01/s4mk3_map.py:10` states
  plainly that Mixxx is GPL-2.0-or-later and no Mixxx code was copied. This is
  the right instinct and the right place to write it down. Protocol facts (MIDI
  CC numbers, LED addresses) are not copyrightable; a copied mapping file would
  have been.
- **BPM evaluation corpus** — the six `.wav` files are synthesized by
  `gen_bpm_eval_corpus.py` (sine bursts and noise). Not third-party audio, no
  claim attaches. The `hotlane` filename is a scenario label, not a track.
- **External binaries** — `ffmpeg` (recording, streaming) and `v4l2loopback` are
  invoked as separate processes or kernel modules, never linked. FFmpeg's own
  license depends on the user's build; `libx264` and `aac` are only ever named as
  config *defaults* passed to the user's own ffmpeg. Kernel modules like
  v4l2loopback are GPL-2.0 but the userspace-boundary exception applies. All
  fine, and worth keeping that way — don't ever bundle an ffmpeg binary without
  checking how it was configured.
- **projectM** — LGPL-2.1, loaded via `ctypes` at runtime, never bundled.
  Dynamic loading is precisely the arrangement LGPL exists to permit.
- **`demucs`** (dj-mixer-01, declared) — the *code* is MIT and fine. The
  *weights* are not: see Finding 9, added after checking upstream.
- **`ably`** (chat-01) and the OpenAI/Anthropic SDKs — Apache-2.0, permissive.
  Their *service terms* are a separate question from license, as is Spotify's
  developer agreement; none are license findings.

## Finding 8 — Housekeeping

- `README.md:533` says "MIT (see LICENSE if present in repo)." `LICENSE` is
  present and always has been. Drop the hedge — a vague license statement is
  worse than none, because it suggests the project isn't sure.
- The `LICENSE` copyright holder is "Unicorn Viz," which is the project, not a
  legal person. If the copyright is meant to be yours or an entity's, name it.
- **No drop-in has a `LICENSE` file.** All 40 are separate private repositories,
  and none states its license. Right now they inherit nothing explicitly — a
  private repo with no license grants no rights at all to anyone who receives it.
  That's harmless while private, and becomes a problem the day one is opened up
  or a collaborator is added. Decide once, apply to all 40.
- `pyproject.toml` has no `license` field and no license classifier, so the built
  wheel and any PyPI listing show no license.
## Finding 9 — Demucs pretrained weights are CC BY-NC 4.0 (non-commercial)

Checked against upstream on 2026-08-08, because the original report only
flagged this as "verify before commercial release."

**Where:** `demucs>=4.0` is a declared, deliberate requirement of dj-mixer-01
(`drop-ins/dj-mixer-01/requirements.txt`), where stems are described as a
requirement of the mixer rather than a nicety. `stems.py` shells out to the
Demucs CLI, which downloads model weights on first use; the default model is
`htdemucs`.

**What upstream actually says.** The repository's `LICENSE` is MIT, copyright
Meta Platforms, and the README states "Demucs is released under the MIT license."
Neither the README nor `docs/training.md` says anything at all about the
pretrained weights — the split is simply not addressed in the repo, and the
GitHub issue asking the question directly ("License of pre-trained models",
facebookresearch/demucs#327) has no maintainer answer. That silence is the
finding: **the MIT license covers the code, and it is not a grant covering the
weights.**

Independent sources that have done this diligence consistently report the
weights as **CC BY-NC 4.0**, carried over from the original Meta AI release and
constrained by the research-only terms of the training data. CC BY-NC forbids
commercial use.

**Plain English:** the important difference from every other finding in this
report is that **CC BY-NC restricts *use*, not just distribution.** GPL and
AGPL only bite when you hand the software to someone or expose it over a
network; you can use them freely in private. Non-commercial is the opposite —
it bites the moment the use itself is commercial, even if you never ship a byte
of the weights to anyone.

- Running stems locally, for free, for your own sets: **fine.**
- Shipping the weights in a bundle: not permitted. You don't do this — the
  Demucs CLI downloads them onto the operator's machine on first run, so you
  redistribute nothing. That is a genuinely good position and worth keeping.
- **Charging for unicorn-viz, or using it in paid performances, while stem
  separation runs on these weights: this is the part that is not permitted**,
  regardless of who downloaded them. A paid VJ gig driven by htdemucs stems is
  a commercial use of NC-licensed weights.

**What to do (owner's call), if a paid product or paid performance is ever on
the table:**

1. Swap to a permissively-licensed separation model. Some newer open-weight
   separators ship Apache-2.0 or MIT weights; this is the only option that
   removes the constraint outright.
2. Train or commission weights on licensed data. Expensive, fully clean.
3. Approach Meta for a commercial license to the weights.
4. Keep stems as a free-tier / personal-use feature and gate anything paid
   away from them — awkward, given stems are core to the mixer's design.

**Not a blocker today.** Nothing about the current free, source-distributed,
weights-downloaded-by-the-operator arrangement is a problem. This only matters
the day money is involved, and it is much cheaper to know that now than after
the mixer's design has hardened around these stems.

Sources: [demucs LICENSE](https://github.com/facebookresearch/demucs/blob/main/LICENSE),
[facebookresearch/demucs#327](https://github.com/facebookresearch/demucs/issues/327),
[Mixxx GSoC 2025 Demucs→ONNX writeup](https://mixxx.org/news/2025-10-27-gsoc2025-demucs-to-onnx-dhunstack/),
[models and variants overview](https://deepwiki.com/facebookresearch/demucs/5.1-models-and-variants).


---

## Prioritized recommendations

| # | Action | Why | Effort | Status |
| --- | --- | --- | --- | --- |
| 1 | Decide on `essentia` (drop / subprocess / declare-and-never-bundle) | Only finding that can force you to open-source your own code | Low–Medium | **Open — owner** |
| 2 | Generate `THIRD_PARTY_LICENSES.md`, wire into all 3 packaging manifests | Legally required for every bundle you ship | Low | **Done 2026-08-08** |
| 3 | Fix the Windows installer's `RepoRoot\*` sweep | Would package NVIDIA assets, presets, and any GPL drop-in dep into one file | Low | **Done 2026-08-08** |
| 4 | Untrack the stray `.milk`, add `preset-trash/` to projectm-01's `.gitignore` | Trivial, and restores an otherwise clean posture | Trivial | **Done 2026-08-08** |
| 5 | Record provenance of `font8x16.bin` / `font8x8.bin` | Cheap now, hard later; may carry a CC BY-SA attribution duty | Low | **Open** |
| 6 | Add `assets/ansi/README.md` crediting ACiD artists from SAUCE | Turns a norm-based position into a documented, defensible one | Low | **Done 2026-08-08** |
| 7 | Decide `mutagen` — accept as never-bundled, or replace with an in-house tag reader | GPL-2.0 in a drop-in you might one day want in a bundle | Medium | **Open — owner** |
| 8 | Add `license` + classifier to `pyproject.toml`; fix the README hedge; pick a license for the 40 drop-in repos | Correctness and future-proofing | Low | **Open** |
| 9 | Before any paid product *or paid performance*: replace the Demucs weights | Confirmed CC BY-NC 4.0 — restricts use, not just distribution | Medium | **Open — owner** |

## Distribution posture summary

Read this as the one-paragraph answer to "can I ship it."

- **Source repo, as it stands today:** clean. No obligations unmet.
- **Local use on your own machines:** clean, including essentia and VLC. Copyleft
  triggers on distribution, not on use.
- **Flatpak / Snap / Windows installer, core only:** clean as of 2026-08-08.
  Everything in `requirements.txt` is permissive, and the attribution file now
  ships in all three. Keep `THIRD_PARTY_LICENSES.md` regenerated when pins move.
- **Any bundle that includes essentia:** must be AGPL-3.0, source included.
- **Any bundle that includes mutagen or VLC:** must be GPL-2.0, source included.
- **Closed-source or paid distribution:** possible, but only after essentia is
  resolved, mutagen/VLC stay strictly operator-installed, and the Demucs weights
  are replaced. Note the last one applies to **paid performances too**, not just
  shipping — NC restricts use.

---

## Method notes and limits

- Package licenses were read from installed distribution metadata in `.venv`
  plus the license files embedded in each wheel. Metadata occasionally
  disagrees with a project's actual LICENSE file; the copyleft findings
  (essentia, mutagen, python-vlc) were cross-checked against the `COPYING` files
  the wheels ship, and match.
- `demucs`, `torch`, and `ably` are declared in drop-in requirements but not
  installed in this venv, so their licenses are stated from the packages'
  published terms rather than verified locally. The Demucs weights question
  (Finding 9) was checked against upstream on 2026-08-08: the repository's own
  MIT `LICENSE` and README were read directly, and the CC BY-NC status of the
  weights comes from third-party sources plus the *absence* of any grant
  upstream — Meta has never published weight terms in the repo, and issue #327
  asking for them is unanswered. That is a well-supported reading, not a quote
  from Meta.
- This is an engineering review of license terms as they apply to this codebase.
  It is not legal advice, and the AGPL/GPL derivative-work boundary in
  particular is genuinely contested — if a commercial release is on the table,
  the essentia question is worth a lawyer's half hour.
