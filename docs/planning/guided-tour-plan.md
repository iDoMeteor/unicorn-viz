---
Owner: Planning
Status: BACKLOG — owner-requested 2026-07-18. Not started. **Sequencing
note (2026-07-18): a simpler v1 ships first** — a centered slide dialog
with next/prev/close + a show-on-startup toggle, specified in
[`first-run-tour-plan-2026-07-18.md`](first-run-tour-plan-2026-07-18.md).
This doc remains the v2 interactive-spotlight vision and builds on v1's
trigger, persistence, and entry points.
Last updated: 2026-07-18
---

# "Give Me a Tour" — Guided Onboarding Plan

A **guided tour** that walks a new operator through a surface: what each zone
is, what the important controls do, and the one or two gestures that unlock it.
Available **on demand from the help menu**, and offered **once automatically on
the app's first-ever launch**.

unicorn-viz has grown a *lot* of surface area — three effect displays, a
four-deck mixer, a control room, overlays, hotkeys, drop-ins. A newcomer (or the
owner after a month away) shouldn't have to read `docs/` to find the good parts.

---

## 1. Behaviour (shared across surfaces)

- **Triggers**
  - **First-ever launch only:** offer the tour once ("Want the quick tour?"),
    with an obvious decline. Never nag again — completion *or* dismissal is
    recorded in the persisted runtime state.
  - **On demand, always:** an entry in the **help overlay** (the `H` rail — see
    §4) and, on each secondary surface, its own help panel.
- **Non-blocking.** The tour narrates over the live app; it never modal-locks
  the operator out of the controls. A live set is never held hostage by it.
- **Skippable + resumable.** `Esc` (or a Skip control) exits at any step;
  re-entering offers Resume vs Start over.
- **Step model.** Each step = *a target region + a short caption + optional
  "try it" affordance*. Reuse the existing highlight/tooltip primitives rather
  than inventing a new overlay language (see `docs/planning/tooltip-system-plan-2026-07-13.md`).
- **Never destructive.** Tour steps only *point at* controls; they never load,
  play, or alter audio/visual state on the operator's behalf.
- **Remembered per surface.** Finishing the mixer tour shouldn't mark the core
  tour complete — track completion per surface key.

---

## 2. Core app tour (re-contexted for core)

Audience: someone who just launched unicorn-viz for the first time.

Beats to cover:

1. **The audience output** — what the main window is, and that effects render here.
2. **Switching effects** — next/prev/random, the effects browser, and the
   effect lock.
3. **Reactivity** — that visuals follow live audio; where the audio source is
   chosen (and the viability flags).
4. **Overlays + HUD** — what the HUD shows, how to hide it.
5. **Multi-display** — display modes (single / span / mirror), and that effects,
   mixer and control room can each own a screen. (Owner runs 5 monitors: 3
   effects + mixer + control room — this is a headline capability, show it off.)
6. **Where the rest lives** — the `H` help overlay + drop-ins (Auto VJ, mixer,
   control room), one line each.
7. **Hotkey literacy** — point at the help rail rather than reciting keys.

Home: fold the trigger into the **help overlay icon rail** (see §4).

---

## 3. DJ Mixer tour (re-contexted for dj-mixer-01)

Audience: a DJ opening the mixer window (`Shift+D`) for the first time.

Beats to cover:

1. **Deck anatomy** — the 2×2 / 2-deck layouts, the full + zoom waveforms, the
   platter, and that the platter angle tracks the playhead.
2. **The browser** — crates, search/filter, and the **colour language** that
   makes this mixer worth using: white = on a deck, green = mixes cleanly,
   magenta = one wheel step away, gold = stems extracted.
3. **Loading + transport** — drag a row to a deck (or double-click), then
   play/cue/loop.
4. **The pod** — EQ/TRIM/FLT dials, PITCH/TEMPO, the two HOLDs, and the FX
   selector (single click selects, double-click locks).
5. **SYNC / KEY / 🔒 locks** — beatmatch, harmonic match, and what set-and-forget
   locks do across tracks (incl. pre-sync on load).
6. **Stems** — the STEMS pad bank, the `G:` gain faders (drag / right-click to
   mute / double-click 100%), and `S:` solos.
7. **Auto-play + transitions** — CUT/XFADE, and the scratch transition on an
   incompatible mix.
8. **Headphone cue** — the CUE buttons and where cue is routed.

Home: the mixer's own **help overlay** (the `?` icon) gains a "Take the tour"
entry. Cross-ref: `docs/planning/dj-mixer-drop-in-plan.md`.

---

## 4. Control Room tour (re-contexted for control-room-01)

Audience: an operator opening the control room for the first time.

Beats to cover:

1. **What the control room is for** — the operator-facing surface vs the
   audience output.
2. **The live preview** — what it mirrors and its refresh characteristics.
3. **Per-panel walkthrough** — each pane's job, in the room's own vocabulary.
4. **Where it defers** — which controls live here vs in the mixer vs core, so
   the operator isn't hunting across windows.
5. **Second-window behaviour** — it owns its own SDL window (cross-ref
   `docs/planning/control-room-mixer-second-window-mitigation-strategies-2026-07-09.md`).

Home: the control room's own help affordance; scope its steps in
`drop-ins/control-room-01/docs/operations.md` when the work starts.

---

## 5. Help-overlay integration (core)

The core `H` overlay already has a **centered icon rail** with staged actions
for future features (`docs/planning/help-additions-milestone-2026-06-14.md`).
The tour is a natural rail tile:

- Add a **"Tour"** icon to the rail (icon asset per the help-icon standard:
  `assets/icons/help/76px|152px`, correct orientation, no runtime flip).
- Selecting it starts the tour **for the surface the help overlay belongs to** —
  so the same affordance gives the core tour from core, the mixer tour from the
  mixer, and the control-room tour from the control room.

---

## 6. Open questions

1. **Narration style** — terse captions only, or captions + an optional
   "try it" step that waits for the operator to perform the gesture?
2. **First-run offer placement** — a small toast/banner (non-blocking, matches
   the "never modal-lock" rule) vs a centered first-run card?
3. **Persistence key** — where completion/dismissal lives (runtime state file vs
   config); must survive upgrades but be resettable ("replay the tour").
4. **Do drop-ins register their own tours?** A tour registry on `vj_api`
   (`register_tour(surface, steps)`) would let any drop-in contribute its own
   walkthrough without core knowing about it — consistent with the
   subsystem-registry pattern. Probably the right shape; confirm before building.

---

## 7. Milestones

- [ ] **T0 — step/def framework.** A surface-agnostic tour runner (step list,
  highlight + caption, next/prev/skip/resume, per-surface completion state)
  built on the existing tooltip/highlight primitives.
- [ ] **T1 — core tour + help-rail tile + first-run offer.**
- [ ] **T2 — DJ mixer tour** (its `?` overlay entry).
- [ ] **T3 — control room tour.**
- [ ] **T4 — (optional) `vj_api.register_tour()`** so drop-ins ship their own.
