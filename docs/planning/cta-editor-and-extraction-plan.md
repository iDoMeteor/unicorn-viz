# CTA — In-App Editor + Extraction to Its Own Drop-In

Owner: owner + Claude Opus (master coordinator)
Status: Planned (not started)
Last updated: 2026-07-13

Two related pieces of work for the call-to-action (CTA) hype overlay — the
animated "Push the buttons! 👍 / Do the thangs! 🔔 / Share the love! ❤️📤" cards:

1. an **in-app CTA editor** (edit messages + timing live, no config.toml hand-edit);
2. **extracting CTA out of `streaming-01`** into its own `cta-01` drop-in so it is
   independent of streaming.

---

## 1) Current architecture (as of 2026-07-13)

CTA is currently split across three places — entangled with the streamer:

| Piece | Location | Role |
|-------|----------|------|
| `CTAOverlay` | `unicornviz/cta_overlay.py` (core) | GL rendering of the hype cards (extracted from `overlays.py`). |
| CTA scheduling + messages | `drop-ins/streaming-01/rtmp_streamer.py` (`_cta_*`, `trigger_cta`, `trigger_song_cta`, `_parse_cta_messages`) | Owns messages, mode, duration, cooldown, seed. |
| Config | `config.toml [streaming.cta]` | `enabled`, `mode`, `duration_s`, `cooldown_s`, `seed`, `messages`. |
| Trigger path | hotkeys → `App.trigger_streaming_cta()` / `trigger_streaming_song_cta()` → `self._streamer.trigger_cta()` → `overlays._cta.trigger*()` | F9-family. |

**Problem:** CTA only works when the streaming drop-in is loaded, even though the
hype cards are useful during any show (recording, local performance). The
messages/timing live inside the RTMP streamer, which is the wrong home.

---

## 2) In-app CTA editor

**Goal:** edit CTA messages + timing from inside the app, live, no TOML editing —
consistent with the configuration editor's look and conventions.

**Recommended shape:** a **"Streaming" (or "CTA") tab in the configuration
editor** rather than a separate modal, reusing everything already built:

- The LCARS-glossy tabbed shell, sprite border, hover glow, animation.
- The config-editor **convention** (`CONFIG_EDITOR_CATEGORY`/`config_editor_settings`
  /`set_config_setting`) for the scalar knobs (`duration_s`, `cooldown_s`, mode).
- Message list editing needs a richer control than a slider row:
  - a small list widget (add / edit / delete / reorder) reusing the profile-name
    text-entry mechanism (`_name_char_for_keysym`) for typing message text;
  - each message is `text|icon` (the existing `_parse_cta_messages` format);
  - a **"Preview"** button that fires `CTAOverlay.trigger_custom(...)` so the
    operator sees the card immediately.
- Persist into configuration profiles alongside the other settings once CTA is a
  first-class contributor (see extraction below).

**Open question:** message-list editing is the first config-editor control that
isn't a numeric slider — decide whether to generalize the config-editor row model
to support list/string settings, or give CTA a bespoke sub-panel. Leaning
bespoke sub-panel for v1, generalize later.

---

## 3) Extract CTA into its own `cta-01` drop-in

**Goal:** CTA becomes a self-contained drop-in, independent of streaming, so it
fires during any show and streaming just *uses* it.

**Proposed layout:**

```
drop-ins/cta-01/
  cta_controller.py      # owns messages, mode, cooldown, scheduling, trigger API
  docs/{operations,configuration,integration,troubleshooting}.md
```

**Move:**
- The `_cta_*` config + `trigger_cta` / `trigger_song_cta` / `_parse_cta_messages`
  logic out of `rtmp_streamer.py` into `CTAController`.
- `config.toml [streaming.cta]` → `[cta]` (with back-compat: read `[streaming.cta]`
  as a fallback for one release).
- Wire via the standard optional-drop-in loader in `app.py`
  (`_load_cta_controller_class()` + `try/except` + a null fallback), same pattern
  as the other controllers.
- The `CTAOverlay` GL class: keep in core (`unicornviz/cta_overlay.py`) — it is a
  rendering primitive the app owns — or move it into `cta-01`. **Recommendation:**
  keep `CTAOverlay` in core (overlays already instantiate `self._cta`), and let
  `cta-01`'s `CTAController` drive it via `vj_api` (schedule/trigger). This keeps
  the core–drop-in boundary clean (drop-in produces intent, core renders).

**Trigger path after extraction:**
hotkeys → `App` → `vj_api` CTA capability → `CTAController.trigger()` →
`overlays._cta.trigger*()`. Streaming, when present, calls the same CTA capability
instead of owning it.

**Adopt the config-editor convention** on `CTAController` so the editor (§2) and
profiles pick it up automatically (`CONFIG_EDITOR_CATEGORY = 'Streaming'` or a new
tab).

**Independence checklist (per CLAUDE.md):** `_load_cta_controller_class()` guarded
by try/except with a functional null controller; no core hard-dependency; add CTA
hotkeys to `HELP_TEXT`.

---

## 4) Sequencing

1. Extract `cta-01` (move scheduling/config out of `streaming-01`; back-compat
   config read; loader + null fallback; streaming uses the CTA capability).
2. Adopt the config-editor convention on `CTAController`.
3. Build the in-app CTA editor tab (scalars via convention + bespoke message-list
   sub-panel + live Preview).
4. Fold CTA settings into configuration-profile persistence.

Do the extraction first so the editor targets a clean, single owner.
