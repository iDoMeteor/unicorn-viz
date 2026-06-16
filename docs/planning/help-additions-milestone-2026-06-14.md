Owner: UI/Overlays
Status: in progress (phase 1 and phase 2 landed)
Last updated: 2026-06-16

# Help Overlay Icon Rail + Section Content Milestone

## Scope

Evolve the existing `H` help overlay into a two-zone interaction model:

1. Existing section cards remain the default active surface (section 1 focused on open).
2. A new centered icon rail sits in a dedicated horizontal band under the title/time header and above help section content.

The icon rail supports keyboard focus and mouse clicks, with labels and staged action behavior for both currently-available and future features.

---

## Functional Requirements (owner confirmed)

1. Add another horizontal separator below the current title/time separator.
2. Reserve that band for icon tiles (target visual size: ~50 px square at 1920x1080 with ~10 px internal padding).
3. Keep icon rail centered.
4. Add labels for each icon (superseded by owner decision on 2026-06-16: labels removed; icon-only rail retained).
5. Help opens with section 1 highlighted/active (current behavior retained).
6. `Tab` toggles focus between section area and icon rail.
7. Icons and labels respond to mouse clicks.
8. Initial icon set:
   - DJ UT (about/links page)
   - Contact (DJ UT / devs; future payload sending for logs, VJ data, screenshots, recordings)
   - Share (open sharing website flow)
   - Login/Logout (future-ready placeholder)
   - Settings (future-ready placeholder)
   - Account (future-ready placeholder)
   - Shop (open web store, future in-app path)
   - Drop-ins (ProjectM browser + future in-app purchases)
9. Decide and implement modal cursor visibility behavior (see cursor policy below).

---

## UX/Architecture Proposal

### Focus Model

Use a two-region focus state for help overlay:

- `sections`: current section card navigation (`Up/Down/Left/Right`, `Enter`)
- `icons`: icon rail navigation (`Left/Right`, `Enter`)

Rules:

1. On help open, focus region = `sections`, focus index = 0.
2. `Tab` flips region between `sections` and `icons`.
3. When region is `icons`, section navigation keys do not mutate section focus.
4. `Esc` still closes help (existing behavior).

### Icon Action Model

Represent each icon as a typed action entry with staged capability:

- `action_kind='url'`: open external URL now.
- `action_kind='placeholder'`: show flash message (`Coming soon`) now.
- `action_kind='intent'`: queue runtime intent for future drop-ins/in-app flows.

This prevents one-off hotkey logic and keeps future auth/account/shop integration additive.

### Mouse Model

Track hit boxes for icon tiles each frame and expose an overlay handler:

- `handle_help_mouse_click(x, y) -> bool`

Behavior:

1. Hit test icon tile and label bounds.
2. On hit: set icon focus index, switch focus region to `icons`, trigger action.
3. Return `True` when consumed so app-level mouse handlers can short-circuit.

### Sizing/Placement Model

Use relative layout derived from panel dimensions with clamps:

1. Tile size scales from panel height/width, clamped to a reasonable min/max.
2. Padding and gaps scale proportionally.
3. Center the full rail width within the icon band.
4. Keep all coordinates overlay-canvas relative for span/mirror safety.

---

## Cursor Policy (modal visibility)

Recommendation:

1. Show cursor while any overlay modal/help/selector is open.
2. Restore default cursor policy (config + Ctrl-hold behavior) when modal stack closes.

Rationale:

1. Required for reliable icon clicking and discoverability.
2. Minimizes behavior surprise: modal UI implies pointer interactivity.
3. Low risk if tied to existing modal visibility checks in app loop.

Implementation note: this should be driven by a single app-level helper that derives "modal active" from overlay visibility flags, not ad-hoc per modal.

---

## Delivery Status Snapshot (2026-06-16)

Completed:

1. Phase 1 structural UI landed in core help overlay.
2. Phase 2 action wiring landed for keyboard and mouse dispatch.
3. Icon rail visual tune pass landed:
   - icon size reduced (~15% from original target)
   - labels removed per owner direction
   - rail spacing increased and vertical centering corrected

Still open:

1. Phase 3 cursor visibility integration has not been implemented in this milestone sequence.
2. Phase 4 multi-head validation sweep remains to be recorded as a dedicated validation pass.

Next:

1. Run dedicated multi-head/help-overlay visual validation for single/span/mirror topologies.
2. Decide whether modal-aware cursor policy should be implemented now (phase 3) or deferred.
3. If phase 3 is approved, add cursor visibility guard and re-run regression checks.

## Delivery Phases

## Phase 1 — Structural UI (No external actions) [DONE]

Goal: render icon rail and focus states without launch behavior.

Changes:

1. Add icon rail band and separator under header.
2. Add icon metadata list and rendering (tile + label + hover/focus visuals).
3. Add help focus-region state and `Tab` switching behavior.
4. Add keyboard navigation for icon index.
5. Keep icon activation as local flash-only placeholders.

Files:

- `unicornviz/overlays.py`
- `unicornviz/hotkeys.py`

## Phase 2 — Click + Action Wiring [DONE]

Goal: make icons clickable and wire live actions where safe today.

Changes:

1. Add app-level mouse click dispatch for help modal region.
2. Add `Overlays.handle_help_mouse_click(...)` hit-test path.
3. Wire immediate actions:
   - DJ UT / Share / Shop -> external URL launch path.
   - Drop-ins -> open current in-app browser/modal route if available, otherwise placeholder.
4. Keep Contact/Login/Settings/Account on placeholder or intent-dispatch mode until feature owners land backends.
5. Non-blocking launches with graceful flash + log on failure.

Files:

- `unicornviz/app.py`
- `unicornviz/overlays.py`
- `unicornviz/hotkeys.py`

## Phase 3 — Cursor Visibility Integration [OPEN]

Goal: ensure pointer visibility is modal-aware and consistent.

Changes:

1. Add a modal-active visibility check in app runtime.
2. Force cursor visible when any modal/help/selectors are open.
3. Revert to default/ctrl policy when closed.
4. Validate no regression with control-room/mirror windows.

Files:

- `unicornviz/app.py`

## Phase 4 — Multi-Head Validation + Milestone Commit [OPEN]

Goal: verify no regressions across current topologies/modes and ship in scoped commits.

Checklist:

1. `single` mode: rail centered and clickable.
2. `span_included` and `mirror_included`: rail on configured primary, aligned correctly.
3. 3-screen non-grid topology: no clipping/split artifacts.
4. 5-screen mixed topology: no right-edge bleed or scale overflow.
5. Keyboard-only navigation works for both focus regions.
6. Mouse click paths work with cursor visibility policy.
7. Screenshot hotkey remains stable with help/modal open.

Commit sequencing:

1. Phase 1 commit (UI/focus only).
2. Phase 2 commit (actions/click wiring).
3. Phase 3 commit (cursor policy).
4. Phase 4 validation notes in commit body or follow-up comment.

---

## Icon Asset Plan

1. Start with internal placeholders rendered via existing overlay text/shape pipeline so implementation can proceed immediately.
2. Replace placeholders with custom themed art once owner provides final assets or confirms generated pack.
3. Suggested intake format for final assets:
   - transparent PNG
   - square source (128x128 or 256x256)
   - filename slug per icon id

Owner decision needed before final polish pass: provide custom icon pack externally vs. have agent generate first-pass icon set in-repo.
