Owner: UI/Overlays
Status: proposed
Last updated: 2026-06-16

# Help Screen Additions: About, Contact/Bug Report, and Links

## Scope

Extend the existing `H` help overlay with three new informational sections so operators can access project identity, bug-reporting channels, and key resource links without leaving the runtime.

---

## Phase 1 — Help Content (Display Only)

**Goal:** Add the three sections as read-only text inside the existing Help overlay; no external actions yet.

**Changes to make**

1. Add three section groups to `HELP_TEXT` or via `register_help_entries()`:
   - `About` — version, project identity, short one-liner tagline
   - `Contact / Bug Report` — bug report URL (text label only)
   - `Links` — GitHub, docs, community (text labels only)
2. Display in `_render_help()` using existing section typography and theme colors.
3. No interactive elements; no external-open behavior.
4. All positioning stays relative to overlay canvas (safe for span/mirror routing).

**Files touched**

- `unicornviz/overlays.py` only

---

## Phase 2 — Interaction Wiring (Optional Open Actions)

**Goal:** Let the operator trigger open-URL actions from inside the help panel without leaving keyboard focus.

**Changes to make**

1. Add focusable rows to About/Links/Contact sections.
2. Trigger `xdg-open` or equivalent on the selected row when Enter is pressed.
3. Route through:
   - `unicornviz/hotkeys.py` for key handling
   - `unicornviz/app.py` public surface if runtime shim is needed
4. Fail gracefully: flash overlay message if open fails, log the failure.
5. Keep external calls non-blocking (subprocess or `os.startfile` with no wait).

**Files touched**

- `unicornviz/overlays.py`
- `unicornviz/hotkeys.py`
- `unicornviz/app.py` (only if new public shim is required)

---

## Phase 3 — Multi-Head Validation Pass

**Goal:** Confirm help additions behave correctly across all relevant display modes and topologies.

**Checklist**

1. `single` — Help panel centers correctly on sole display.
2. `span_included` — Help panel routes to configured primary (display index 2 in current 3-screen setup).
3. `mirror_included` — Same primary routing as span.
4. 3-screen non-grid (display 2 at `(940, 1080)`) — no clipping/overdraw at panel edges.
5. 5-screen mixed topology — confirm no regression on smaller auxiliary screens.
6. Screenshot hotkey (`S`) still stable after help panel interaction.

---

## Phase 4 — Milestone Delivery

**Sequencing**

1. Commit Phase 1 as its own scoped commit (`unicornviz/overlays.py` only).
2. Owner review pass on wording and section structure.
3. If approved, implement Phase 2 in a separate commit.
4. Phase 3 validation done interactively before final push.

---

## Content Draft (for owner review before Phase 1 implementation)

| Section | Label | Value |
|---|---|---|
| About | Project | Unicorn Viz |
| About | Version | `{runtime version}` |
| About | Author | iDoMeteor |
| Contact | Bug Reports | `github.com/iDoMeteor/unicorn-viz/issues` |
| Links | GitHub | `github.com/iDoMeteor/unicorn-viz` |
| Links | Documentation | `github.com/iDoMeteor/unicorn-viz/wiki` (or docs URL) |

**Owner: please edit this table before Phase 1 begins to confirm exact labels, URLs, and any additional rows.**
