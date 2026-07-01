# Unicorn Viz — Full System Audit (2026-07-01)

Owner: owner + Claude Opus (master coordinator)
Status: Complete
Last updated: 2026-07-01

Scope: Whole-system pass — core architecture, the 35-drop-in surface, effects
consolidation, new runtime-network features, security posture (bandit +
pip-audit), test coverage, hotkey/help governance, and mono-file growth. Includes
per-area grades and a prioritized remediation plan. Also scopes the incoming
**right-click context menu** mission (§11).

Prior audit: [2026-06-19-full-system-audit.md](2026-06-19-full-system-audit.md)

Method: static review + live tooling (full pytest suite, bandit, pip-audit,
git/submodule state, help-parity tests). No GPU runtime profiling this pass.

---

## 0) Executive Summary

Since the 2026-06-19 audit the project has moved **enormously**: **121 commits**,
drop-ins grew **22 → 35**, effects consolidated into **10 category packs (~44
effects)**, and a first-class **effects browser**, **show-presets** system, and
**ProjectM-only mode** shipped. Notably, five drop-ins I suggested last audit were
built: `audio-out-01`, `beat-flash-01`, `color-grade-01`, `lyrics-01`,
`osc-bridge-01`.

| Area | Grade | One-line |
|------|-------|----------|
| Architecture & module boundaries | A- | Loader pattern scaled cleanly to 22 guarded load sites; mono-files regrew (§7). |
| Drop-in independence & fallbacks | A | 22 `_load_*` sites, all try/except guarded; no bare drop-in imports. |
| Effects consolidation | A | 44 effects in 10 packs; catalog + browser well-tested. |
| New features (browser/presets/PM-lock) | A- | Shipped with tests; help entries present. |
| **Test coverage** | **A** | **298 core + 141 spotify = ~439 green.** Big jump from 199. |
| Security — static (bandit) | A- | Clean at `-ll`; one `# nosec` (documented) in training daemon. |
| Security — deps (pip-audit) | A- | No known vulns; but the pip-audit **hook flag is broken** (§5.3). |
| **Security — runtime network surface** | **B** | **4 network drop-ins now; chat-01 ships `enabled = true`. Posture doc needs updating (§5.1).** |
| Hotkey / help governance | A- | Rich single-source help registry; parity tests green. |
| Docs / governance | B+ | Registry refreshed; a few controller drop-ins lack `docs/` (§8). |
| Submodule pointer hygiene | B | Many pointers ahead/uncommitted; new packs not yet in main index (§9). |

**Overall: A-.** The system grew fast and stayed healthy — tests, guards, and
security gates all held. The two things to watch are the **runtime network
surface** (new since the posture was last documented) and **submodule pointer
hygiene** during this high-velocity phase.

---

## 1) Scale Delta Since 2026-06-19

| Metric | 2026-06-19 | 2026-07-01 |
|--------|-----------|-----------|
| Commits (cumulative in window) | — | +121 |
| Drop-ins | 22 | **35** |
| Registered effects | ~43 | **~44** (10 category packs + core) |
| Core `app.py` | 4,666 | **5,472** |
| Core `overlays.py` | 4,184 | **4,711** |
| Drop-in `_load_*` sites in app.py | ~16 | **22** |
| Core tests (collected) | 199 | **298** |
| Spotify drop-in tests | 141 | 141 |

New drop-ins this window: `audio-out-01`, `beat-flash-01`, `color-grade-01`,
`lyrics-01`, `osc-bridge-01`, `chat-01`, `media-01`, `midi-controllers-01`,
`training-kit-01`, plus effect packs `cosmic-01`, `feature-01`, `games-01`,
`holiday-01`, `immersive-01`, `particles-01`, `psychedelic-01`, `retro-01`,
`tech-01`, `vector-01`.

Major features: effects browser (shared `CatalogBrowser` model), show-presets
(`Ctrl+Shift+P`, save/load named runtime setups), ProjectM-only lock (`Ctrl+L`),
modal text-entry key gating, USD character support in `sims-01`, native
relocatable runtime packaging.

---

## 2) Architecture & Drop-In Independence — A / A-

**Independence: strong.** 22 `_load_<name>_class()` functions in `app.py`, each
inside a `try/except` that degrades to `None`/null-controller on failure. No bare
`drop-ins/*` imports in core (`test_dropin_boundary.py` green). The loader pattern
scaled to 13 → 22 sites without structural strain — the design is holding.

**Null-controller safety:** re-export + null-contract tests
(`test_null_controller_contracts.py`) still pin the surfaces; the A/B extraction
from the last cycle (`_null_controllers.py`, `cta_overlay.py`) is intact and
covered by `test_module_extraction_boundary.py`.

**Watch:** the number of optional subsystems composited each frame keeps growing
(post-fx, color-grade, beat-flash, candy, nova, finale, chat, webcam, media HUD…).
The sequential compositing chain is still correct but is the place a future
FBO/ordering bug is most likely to appear. The compositor-dedup plan
(`docs/planning/compositor-dedup-implementation-plan-2026-06-18.md`) is now more
valuable, not less.

---

## 3) Effects Consolidation — A

The move from one-file-per-effect to 10 **category packs** is clean and well-
tested:

- Shared **effect catalog** helper + generic `CatalogBrowser` model back both the
  effects browser and the migrated ProjectM preset manager — good reuse.
- Coverage: `test_catalog_browser.py`, `test_registry_browser_entries.py`,
  `test_hotkeys_effects_browser.py` all green.
- Tag normalization + README catalog rebuild kept the registry and docs in sync.

No dead effects found; packs load via the same guarded drop-in path.

---

## 4) New Features — A-

| Feature | Key | Tested | Notes |
|---------|-----|--------|-------|
| Effects browser | `B` | ✅ `test_hotkeys_effects_browser` | Search/filter/preview/pin; debounced live thumbnail preview. |
| Show presets | `Ctrl+Shift+P` | ✅ `test_show_presets` | Save/load/delete named runtime setups. |
| ProjectM-only mode | `Ctrl+L` | ✅ (registry/lock) | Generic effect-lock. |
| Modal text-entry gating | — | ✅ (hotkey gating commit) | Drop-in key handlers suppressed during text entry — good correctness fix. |

All four register help entries and pass the parity audit. The effects browser on
naked `B` plus the banner remap (`Shift+B` config, `Ctrl+B` editor) is a sensible
key reallocation.

---

## 5) Security

### 5.1 Runtime network surface — B (was effectively N/A) — PRIORITY

The core app still makes **no** runtime network requests, but the **drop-in**
network surface has grown materially. Four drop-ins now do runtime network I/O:

| Drop-in | Backend | Default | Notes |
|---------|---------|---------|-------|
| `spotify-01` | Spotify Web API | opt-in | PKCE, Client-ID only, local token (documented threat model). |
| `lyrics-01` | lyrics provider | opt-in | New; verify provider + rate-limit handling. |
| `auto-vj-01` | LLM scoring (training) | opt-in | Provider keys; training-side. |
| **`chat-01`** | **Ably Realtime** | **`enabled = true`** | Live chat overlay; ships enabled with an empty `ably_api_key`. |

**Finding (P1):** `chat-01` ships `enabled = true` in `config.toml`. It is inert
until an `ably_api_key` is set (so no connection by default), but "enabled by
default" for a component that opens a **persistent third-party realtime socket**
and renders **inbound user text** deserves an explicit decision:

- Confirm the intended default (recommend `enabled = false`, opt-in like the other
  network drop-ins), OR document why on-by-default is correct.
- Inbound chat text is untrusted input rendered on stream — confirm it is treated
  as text-only (no shell/eval/markup execution; the parser path is display-only).
- The Ably key is a secret; confirm it is documented as operator-supplied and
  never committed.

**Finding (P2):** `SECURITY.md` (added 2026-06-20) still says "the core
application does not make network requests at runtime" — accurate for *core*, but
the **drop-in network surface should be enumerated** there now (chat/lyrics/
spotify/auto-vj). Update the Security Model → Network section and the Spotify-only
secrets section to cover Ably + lyrics provider.

### 5.2 Static analysis (bandit) — A-

`bandit -r unicornviz/ drop-ins/ -ll` exits **0** (clean at medium+). One
`# nosec B108` at `drop-ins/training-kit-01/tools/training_daemon.py:197`
(hardcoded temp path) — pre-existing, documented, training-side. No new
shell-injection, `eval`/`exec`, or unsafe-subprocess findings.

### 5.3 Dependency audit (pip-audit) — A- with a broken hook

`pip-audit -r requirements.txt` → **"No known vulnerabilities found."** Good.

**Finding (P2):** the pre-commit hook entry runs `pip-audit -r requirements.txt
-q`, but this `pip-audit` version **rejects `-q`** (`error: unrecognized
arguments: -q`, exit 2). The hook is `stages: [manual]` so it does not block
commits, but the manual invocation is currently broken. Remove `-q` (or replace
with `--progress-spinner off`).

Per CLAUDE.md, no findings were remediated — reported for owner decision only.

---

## 6) Test Coverage — A

- **Core:** 298 collected, **all green** (up from 199). New suites cover catalog
  browser, effects browser hotkeys, show-presets, registry browser entries.
- **Spotify drop-in:** 141 collected.
- **Total: ~439 tests.**
- Help/hotkey parity suites (`test_hotkey_help_audit`, `test_help_overlay_parity`)
  green (9 tests).

Gaps worth closing (P2):
- `chat-01`, `media-01`, `midi-controllers-01` have no dedicated test dir in the
  main tree (may live in their submodules — confirm).
- No test asserts `chat-01` inbound text is rendered as inert text (ties to §5.1).

---

## 7) Mono-File Growth — B (regression from the June refactor)

The June A/B extraction trimmed `app.py` to 4,666 and `overlays.py` to 4,184.
Both have since **regrown past their pre-refactor size** as features landed:

| File | Pre-refactor | Post A/B | Now |
|------|-------------|----------|-----|
| `app.py` | 4,891 | 4,666 | **5,472** |
| `overlays.py` | 4,500 | 4,184 | **4,711** |

The extractions weren't undone — new feature code simply accreted. This is the
expected outcome of pausing items C & D. Recommendation: resume the **`run()`
decomposition (items C & D)** from
`docs/planning/mono-file-refactor-plan-2026-06-19.md`, and consider extracting the
**event-dispatch / mouse-handling** block (which the §11 context-menu mission will
grow anyway) into its own module as a natural item E.

---

## 8) Docs / Governance — B+

- `docs/drop-ins.md` registry refreshed (32 references to the new packs). Good.
- Controller drop-ins `audio-out-01`, `beat-flash-01`, `color-grade-01`,
  `lyrics-01`, `osc-bridge-01`, `training-kit-01` each have a `docs/` set (4–5
  files) — compliant with the "complex drop-ins keep structured docs" rule.
- **Gap (P2):** `chat-01` and `media-01` are controller-type drop-ins with
  runtime + network behavior but only a `README.md` (no `docs/`). Per the
  Documentation SOP they should have at least `operations.md`, `configuration.md`,
  `integration.md`, `troubleshooting.md`. `midi-controllers-01` (presets
  extraction) is borderline — README likely sufficient.
- Effect packs (`cosmic-01`, `tech-01`, …) with README-only are fine (simple
  drop-ins).

---

## 9) Submodule Pointer Hygiene — B (in-flight state)

Snapshot at audit time (expected for active parallel work, flagged for awareness):

- Several submodule pointers are **ahead of the committed gitlink**
  (`git submodule status` shows `+` for `banner-01`, `chat-01`, `webcam-01`; also
  `M drop-ins/...` in status).
- Multiple **new drop-in packs are cloned on disk and present in `.gitmodules`,
  but their gitlink is not yet committed to the main index** (they show as
  untracked: `cosmic-01`, `feature-01`, `games-01`, `holiday-01`, `media-01`,
  `midi-controllers-01`, `particles-01`, `psychedelic-01`, `retro-01`, `tech-01`,
  `vector-01`).

**Implication:** a fresh `git clone --recurse-submodules` of the main repo *right
now* would **not** fetch those packs (no committed pointer), so those effects would
be absent on a clean machine. The independence guards mean the app still starts —
but the catalog would be smaller than intended. **Recommend** committing the new
submodule pointers so the main repo reflects the intended 35-drop-in surface.
(No action taken by this audit — this is live team state.)

---

## 10) Prioritized Remediation Plan

### P1 — decide + document
1. **`chat-01` default + input safety (§5.1):** confirm `enabled = false` (recommended)
   or document on-by-default; confirm inbound chat text is inert display-only.
2. **Update `SECURITY.md` network section (§5.1/5.2):** enumerate the 4 network
   drop-ins and the Ably/lyrics secret handling.

### P2 — hygiene
3. **Fix the pip-audit hook flag (§5.3):** drop the unsupported `-q`.
4. **Commit the new submodule pointers (§9)** so a clean clone gets all 35 drop-ins.
5. **Add `docs/` to `chat-01` and `media-01` (§8).**
6. **Add a chat-text-is-inert regression test (§6/5.1).**

### P3 — structural
7. **Resume mono-file split (items C & D) + extract event/mouse dispatch (item E)**
   ahead of the context-menu mission (§7, §11).
8. **Revisit compositor-dedup** as the overlay chain keeps growing (§2).

---

## 11) Incoming Mission — Right-Click Context Menu (design scope)

The owner's next mission: a **right-click context menu** exposing all toggles and
modals. This audit confirms it is well-supported by the current architecture and
records the design so the mission starts from a plan.

### 11.1 Feasibility — clean

- **Right-click is unused today.** `app.py` handles `SDL_BUTTON_LEFT` and
  `SDL_BUTTON_MIDDLE` in the event loop (~`app.py:2861–2914`); `SDL_BUTTON_RIGHT`
  is free. No key/mouse collision.
- **A dispatch pattern already exists.** `HELP_ICON_ENTRIES` uses an
  `action_kind` field (`placeholder` / `url` / `projectm_manager`) routed through
  `handle_help_icon_action()`. The context menu can reuse this exact
  label→action_kind→dispatch shape.
- **A single source of truth already exists.** `CORE_HELP_SECTIONS` +
  dynamically-registered drop-in `HELP_ENTRIES` already enumerate every
  toggle/modal with a human label. The menu should be **generated from the same
  registry** so it never drifts from the help overlay (and satisfies the
  single-source rule in CLAUDE.md).

### 11.2 Label conventions (owner-specified, endorsed)

- **Toggles:** `<action> <context>` describing what the click *does now* —
  e.g. `Enable Auto-Advance`, `Disable Candy Frame`, `Mute Audio Reactivity`.
  The label must reflect the **current state** (show `Enable X` when off,
  `Disable X` when on) — this requires the menu to read live state at open time.
- **Modals:** `Open <context>` — e.g. `Open Effects Browser`, `Open System
  Monitor`, `Open Show Presets`, `Open MIDI Devices`.

### 11.3 Proposed menu structure (generated, grouped by help section)

**Modals (`Open …`):**
`Open Effects Browser` · `Open Show Presets` · `Open System Monitor` ·
`Open Control Room` · `Open MIDI Devices` · `Open Audio Sources` ·
`Open Webcam Editor` · `Open ProjectM Manager` · `Open Controller Help` ·
`Open Help`

**Toggles (`Enable/Disable …`, state-aware):**
`… Auto-Advance` · `… Random Mode` · `… Recording` · `… HUD` · `… Name Overlay` ·
`… Notifications` · `… Fullscreen` · `… Invert Colors` · `… Candy Frame` ·
`… Chat Overlay` · `… ProjectM-Only Lock` · `… EQ/Spectrum` ·
`… Speed Random` · `… Reactivity Random` · `… Zoom Random`

### 11.4 Additional entries I'd suggest (beyond toggles/modals)

Since you're open to ideas — a right-click menu is a great home for **discoverable
actions** that today are only on obscure keys:

1. **Navigation actions:** `Next Effect`, `Previous Effect`, `Random Effect Now`,
   `Replay Splash`. (Not toggles — one-shot verbs.)
2. **One-shot triggers:** `Trigger Grand Finale`, `Reset Scroll FX`,
   `Take Screenshot`. High-value, currently hidden on modifier combos.
3. **A submenu for "Jump to Effect…"** that opens the effects browser filtered —
   ties the menu into the new catalog.
4. **Contextual entries:** show `Start Streaming` / `Stop Streaming`,
   `Login to Spotify` / `Logout` based on live state (mirrors the stateful
   login/logout help-icon pattern already in the codebase).
5. **A "Reset" group:** `Reset Reactivity`, `Reset Speed`, `Reset Zoom`,
   `Reset Resolution Scale` — the `g`/`Ctrl+G`/`Ctrl+Z` family, made visible.
6. **Footer:** `Open Help (H)` and `Quit` — always-present anchors. Consider
   showing the bound hotkey in a dim right-column so the menu doubles as
   discoverability for the keys.
7. **"Copy diagnostics"** (fps, effect, audio source, xruns) — pairs with the
   existing Contact/"send logs" help-icon intent.

### 11.5 Implementation notes for the mission

- Add `SDL_BUTTON_RIGHT` handling in the event loop; open an `Overlays`-owned
  `ContextMenu` at the cursor, dismiss on click-away / `ESC` / selection.
- Build entries from a registry that maps a help entry → `{label_fn(state),
  action_kind, action}`; render with the existing `_draw_rect` / `_draw_text`
  primitives (no new GL stack needed — same approach as the modals).
- Route actions through `vj_api` where possible (public runtime surface rule),
  not `app._private`.
- Add it to `HELP_TEXT`/help registry (`Right Click`, "Open context menu").
- This is also the natural moment to extract **event/mouse dispatch (item E, §7)**.

---

## Session Log

- Date: 2026-07-01
- Reviewer: Claude Opus (master coordinator)
- Tooling run: full `pytest tests/` (298 green), `bandit -r` (exit 0),
  `pip-audit` (no known vulns), submodule/status reconciliation, help-parity tests.
- Headline deltas: +121 commits, 22→35 drop-ins (5 were my prior suggestions),
  effects consolidated to 10 packs, effects-browser/show-presets/PM-lock shipped.
- New risk to watch: runtime network surface (chat-01 Ably, enabled-by-default) —
  P1 decision + SECURITY.md update.
- Hygiene: pip-audit hook `-q` broken; several submodule pointers uncommitted.
- Structural: mono-files regrew past the June refactor; resume items C/D + add
  event-dispatch extraction (item E) ahead of the right-click-menu mission.
- No code changed in this pass — audit + mission scoping only.
