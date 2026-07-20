# First-Run Tour (v1) — Slide Dialog Plan

Owner: owner + Claude (planning)
Status: **P1 shipped 2026-07-20** (core 1.0.0-beta.10) — `unicornviz/tour.py`
deck + policy, Overlays slide dialog, F1 + in-modal keys, startup trigger,
context-menu "Open Tour" entry, runtime-state persistence, and
`tests/test_tour.py`. Two deliberate deviations from this spec: the tour
buttons carry **no tooltips** (they are self-labeled; §2.4 simplification)
and the context-menu label is **"Open Tour"**, not "Take the Tour", to keep
the enforced `Open <context>` modal-label convention. P2 (drop-in
`TOUR_SLIDES` + help-rail tile — needs an icon asset) and P3 (CR mirroring)
remain open. **P2 update 2026-07-20** (core 1.0.0-beta.11): the
`TOUR_SLIDES` discovery scan (`discover_dropin_tour_slides` in
`dropins.py`, merged in `App._tour_deck`) and control-room-01's two
slides (0.9.0) are shipped; still open in P2 are the help-rail Tour tile
(**blocked on the icon asset** — owner is batching all image work) and
dj-mixer-01's slides (**deferred** — mixer repo has another team's work
in flight). The interactive spotlight tour remains the v2 vision in
[`guided-tour-plan.md`](guided-tour-plan.md) (backlog), which this
supersedes *for sequencing only* — v1 ships first, v2 builds on its
trigger/persistence/entry points.
Last updated: 2026-07-20

---

## 1) What v1 is

A **centered slide dialog**, offered automatically on the app's first-ever
run and re-openable on demand: a consistently-sized panel over the running
app showing a deck of short slides about the core app, the control room,
and the DJ mixer, with **PREV / NEXT / CLOSE** buttons and a **"Show on
startup" toggle**. No spotlighting, no "try it" steps, no per-surface
step targeting — that is v2 (`guided-tour-plan.md`), and nothing here
precludes it.

Reconciliation with v2's "never modal-lock" rule: the dialog is an
ordinary overlays modal (same class as the audio/MIDI selectors) — the
app keeps rendering live behind it, `Esc` closes it instantly, and it
only ever auto-opens at startup, never mid-set. That satisfies the
spirit ("a live set is never held hostage") while keeping v1 a simple
dialog, which is the owner's explicit v1 ask.

## 2) Architecture — it's an overlays modal, and that buys a lot

Build the tour as a **core overlays modal** (new
`Overlays._render_tour()` + `_show_tour` flag + snapshot type `'tour'`),
because that single choice inherits four existing mechanisms:

1. **Rendering** — the modal panel language already exists
   (`_draw_modal_underlay`, `_begin_panel`, `_draw_modal_frame_decor`,
   `_draw_text`); a fixed-size centered panel is the same geometry as the
   audio selector. Consistent size: a fixed logical size (e.g. 880×560)
   clamped to the window, identical on every slide — text wraps inside
   it (reuse `wrap_tooltip_text` for the body).
2. **Control-room mirroring** — the control room already renders overlay
   modals from `vj_api.overlay_modal_snapshot()` (`vj_api.py:1650`) with
   action dispatch back through `_dispatch_action`. Adding a `'tour'`
   snapshot type gives the CR a rendered tour with working buttons for a
   small CR-side addition (P3). Until then, the tour simply always renders
   on the main window (skip the `route_modals_elsewhere` gate for this
   one type).
3. **Input** — keyboard (←/→/Enter/Space = next, Esc = close) and mouse
   (buttons + checkbox) follow the config-editor/tab-boxes pattern
   exactly: a `_tour_button_rects` list rebuilt at render, a motion
   handler for hover, a click handler; `app.py`'s event loop gets one
   more modal branch, same shape as the existing ones.
4. **Tooltips** — the buttons get hover tooltips through the existing
   modal tooltip tracker for free (one region provider).

**Mixer window:** v1 does *not* render the dialog on the mixer's own
window — the mixer slides are *about* the mixer, shown on the main
window. Two escape hatches later: the CR mirroring path (P3), and
mixer-only hosted mode (see `drop-ins/dj-mixer-01/docs/mixer-only-mode-plan.md`),
where overlays composite **over** the hosted mixer frame on the main
window — hosted mode gets tour-over-the-mixer for free.

## 3) Slide model & content sourcing

```python
@dataclass(slots=True, frozen=True)
class TourSlide:
    section: str      # 'Unicorn Viz' | 'Control Room' | 'DJ Mixer' | drop-in name
    title: str
    body: str         # short paragraph(s); wrapped at render
    # v1 is text-only. An optional image field is reserved for v1.5
    # (screenshot thumbs), not implemented now.
```

- **Core slides** live in a module-level list in a new
  `unicornviz/tour.py` (content + the show/seen state helpers; rendering
  stays in overlays).
- **Drop-in slides**: control-room-01 and dj-mixer-01 each export a
  `TOUR_SLIDES` list, discovered the same way `HELP_ENTRIES` already is
  (extend the `unicornviz/dropins.py` discovery scan with a
  `discover_dropin_tour_slides()` sibling). Absent drop-in ⇒ its section
  simply doesn't appear — independence rules hold, core never imports
  drop-in code.
- **Order**: core section first, then drop-in sections alphabetically
  (matching help-section ordering). Slide footer shows `4 / 12 · DJ Mixer`.

### Draft deck (v1 content, ~12 slides — beats lifted from guided-tour-plan §2–4)

| # | Section | Slide |
|---|---|---|
| 0 | Unicorn Viz | **Welcome** — what the app is; "this quick tour takes ~a minute"; the Show-on-startup toggle lives on this slide too |
| 1 | Unicorn Viz | The audience window — effects render here, reacting to live audio |
| 2 | Unicorn Viz | Switching effects — next/prev/random, the effects browser, effect lock |
| 3 | Unicorn Viz | Audio in — choosing the capture source, what the viability flags mean |
| 4 | Unicorn Viz | Help lives on `H` — every hotkey, the icon rail, per-drop-in sections |
| 5 | Unicorn Viz | Multi-display — single/span/mirror; effects, mixer and control room can each own a screen |
| 6 | Control Room | What it is — the operator console vs the audience output; how to open it |
| 7 | Control Room | The panes — preview, transport, Auto VJ, tweakables, moments, modals |
| 8 | DJ Mixer | What it is — a real 4-deck mixer; how to open it; the DDJ-REV1 |
| 9 | DJ Mixer | The browser colour language — white on-deck, green mixes clean, magenta one wheel step, gold has stems |
| 10 | DJ Mixer | Decks + pod — load, play/cue, EQ/TRIM/FLT, SYNC/KEY, stems pads |
| 11 | Unicorn Viz | Where to go next — docs, config editor, the context menu; "re-run this tour any time from the help rail" |

Exact copy is a content pass during implementation; hotkey names in slide
text must be **resolved from the help registry** (the
`Overlays.lookup_help_key` mechanism the tooltip system added), never
hardcoded — same single-source-of-truth rule as tooltips.

## 4) Trigger, persistence, and the toggle

- **State** lives in the persisted **runtime state store**
  (`vj_api.get/set_runtime_state`, `vj_api.py:174-178`) — *not*
  config.toml (that file is owner-edited; this is app-managed state).
  Keys:
  - `tour.show_on_startup: bool` — missing = first run = treated as True.
  - `tour.last_slide: int` — resume position (reset to 0 on completion).
- **Startup trigger**: after the app is fully up (right after
  `self._running = True`, before the first frame is a fine place), if
  `tour.show_on_startup` resolves True and no other modal is open, open
  the tour at `tour.last_slide`. First-ever run therefore auto-offers
  (slide 0 *is* the offer); the toggle on the dialog controls every
  subsequent startup. Unchecking + closing ⇒ never auto-opens again.
  This single-key model replaces the seen/dismissed flag pair in
  guided-tour-plan §6.3 — simpler, and the control is visible right on
  the dialog.
- **Mixer-only mode**: the profile skips the visual slides' relevance —
  v1 keeps it simple: the tour behaves identically (the deck is small);
  a profile-filtered deck (mixer slides only) is a one-line follow-up
  once both features exist.
- **Re-entry points**: context-menu entry ("Take the tour") in v1 —
  code-only, cheap. The help-rail **Tour tile** (guided-tour-plan §5)
  needs a new icon asset per the help-icon standard
  (`assets/icons/help/76px|152px`, authored orientation) — asset request
  to the owner; wire it when the asset lands (P2).

## 5) Dialog spec

- Fixed logical panel (proposed 880×560, clamped to 90% of the window),
  centered; identical size on every slide (owner requirement).
- Layout: section eyebrow + title, wrapped body, footer row with
  `n / N · Section`, the **Show on startup** checkbox (left), and
  **PREV / NEXT / CLOSE** buttons (right). On the last slide NEXT becomes
  **DONE** (closes + resets `tour.last_slide`).
- Keyboard: `←/→` prev/next, `Enter`/`Space` next, `Esc` close,
  `S` toggles the checkbox. All advertised in a caption line.
- Mouse: buttons + checkbox + (nice-to-have) click-anywhere-right-half =
  next, matching slide-viewer muscle memory — optional, decide in review.
- Visual language: the existing modal frame decor (corner accents,
  underlay dim) so it reads as native.

## 6) Phasing

- **P1 — core (one repo, no drop-in changes).** `unicornviz/tour.py`
  (slides + state), overlays modal (render/input/hover), app.py event
  branch + startup trigger, context-menu entry, runtime-state keys,
  core slide deck. Drop-in sections absent until P2 — the deck simply
  shows core slides. Tests: state-key transitions (first run / toggled
  off / resume), slide navigation bounds, button hit-boxes vs rendered
  rects (config-editor test pattern), no-hardcoded-hotkeys content test.
- **P2 — drop-in slides + help-rail tile.** `TOUR_SLIDES` in
  control-room-01 and dj-mixer-01 (their repos, coordinated), discovery
  scan in `dropins.py`, the rail tile when the icon asset exists.
- **P3 — control-room mirroring.** `'tour'` type in the CR modal
  renderer + button actions (CR repo).
- **v2** — the spotlight tour per `guided-tour-plan.md`, reusing this
  trigger, persistence, and entry points; its T0 framework supersedes
  the slide renderer only if/when it lands.

## 7) Risks / notes

- **Two tour docs**: this doc owns v1; `guided-tour-plan.md` stays the
  v2 vision (its status note now points here). Don't let them drift —
  when v2 starts, fold v1's shipped reality into it.
- **First-run detection** is "key missing from runtime state", so
  existing installs (owner, other teams) will see the tour once after
  upgrading — arguably a feature (everyone reviews the deck once);
  flagged so it isn't a surprise.
- **Modal exclusivity**: opening the tour must respect the existing
  modal mutual-exclusion rules (close/decline if another modal is up;
  the startup trigger checks first).
- **Copy length**: slides must fit the fixed panel at the smallest
  supported window — the content test should render-measure the deck.
