# Configuration Editor — Design & Build Plan

Owner: owner + Claude Opus (master coordinator)
Status: In progress — Increment 1 (foundation) landing; UI increments queued
Last updated: 2026-07-01

A tabbed, LCARS-glossy in-app **configuration editor** for tuning effect (and
later, subsystem) settings live, and saving them as named **configuration
profiles**.  Opens on **`c`** (chat-01 will vacate `c`).

---

## 1) Concept & scope

- **Configuration profiles** are a *new*, separate concept from **show presets**.
  - **Show presets** = which effects are enabled for rotation (effect on/off
    toggles only).  Unchanged; the config editor does **not** touch enable/disable.
  - **Configuration profiles** = the *exact settings* (per-effect tweakable
    parameters now; audio/visual globals + drop-in settings later), saved under a
    name and recallable.
- Primary v1 job: **edit individual effect configs** — core *and* drop-in effects
  — where each effect exposes `self.parameters: dict[str, float]`.
- Edits **live-apply** to the running show immediately, and can be **saved as a
  named configuration profile**; loading a profile re-applies it.

---

## 2) How it fits the existing settings model (the key insight)

Effects already have a clean settings pipeline:

- `BaseEffect` declares `self.parameters: dict[str, float]` in `_init()` and keeps
  `self._initial_parameters` as the pristine snapshot.
- `App._instantiate(cls)` reads `config.toml [effects.<ClassName>]` and passes it
  as `effect_cfg` to `cls(ctx, w, h, effect_cfg)`; the effect uses those values
  **instead of randomizing** the corresponding parameters.

So a configuration profile is just **a per-effect parameter override dict** that we
inject at instantiation, layered on top of the `config.toml` values.  Because a
configured parameter suppresses that parameter's startup randomization, profiles
naturally "pin" the settings the operator dialed in, while un-pinned parameters
keep their per-run variety (respecting the Effect Randomization Requirements).

### Override layer (Increment 1)

- `App._effect_config_overrides: dict[str, dict[str, float]]` — `{ClassName: {param: value}}`.
- `_instantiate` merge order (lowest → highest precedence):
  `config.toml [effects.ClassName]`  →  active profile overrides.
- **Live apply:** when the operator edits a parameter for the *current* effect,
  also write `self._current_effect.parameters[name] = value` for instant feedback;
  the override map makes it persist across re-activation and into the saved profile.
- All of this is exposed through `VJApi` (public runtime surface rule); the editor
  never touches `app._private`.

---

## 3) Persistence

- New store `unicornviz/config_profiles.py` → `ConfigProfileStore`, mirroring
  `ShowPresetStore` (atomic JSON write, thread-safe, schema-versioned).
- File: `runtime/config_profiles.json` (separate from `runtime/presets.json`).
- Never writes `config.toml` (owner-owned).
- Profile payload schema (extensible):
  ```json
  {
    "effects": { "Plasma": { "speed": 1.4, "hue_shift": 0.2 } },
    "audio":   { "reactivity": 1.1 },
    "visuals": { "render_scale": 0.85 },
    "meta":    { "created": "...", "notes": "..." }
  }
  ```
  v1 populates `effects`; `audio`/`visuals` land with their tabs.

---

## 4) UI design (LCARS-glossy, layered)

A tab-based modal reusing the house style:

- **Frame:** themed panel + neon border + audio-reactive sprite bulbs + open/close
  animation + glossy hover glow (same vocabulary as the context menu & modals).
- **Tab bar** across the top (styled like help section headers); click or
  Left/Right to switch; active tab underlined/glowing.
- **Two-pane body** (reusing the `CatalogBrowser` two-pane feel): left = list
  (effects / setting groups), right = detail (that item's parameters as labelled
  rows with value + adjust controls: drag / wheel / `[ ]` nudge / click-to-type).
- **Footer bar:** profile name + `Save` / `Load` / `Delete` / `Revert`, and a dirty
  indicator.

### v1 tabs (core-first)
- **Effects** — browse all effects (core + drop-in via the catalog); edit the
  selected effect's `parameters`; live-apply.
- **Audio** — global reactivity, speed/zoom ranges, BPM profile, audio source.
- **Visuals** — resolution scale, transition style, invert default.

### Later tabs
- **Drop-ins** — per-drop-in enable + settings, generated dynamically from
  drop-in metadata/help (never hard-coded, same principle as the context menu).
- **Bindings** — read-only hotkey/MIDI map (from the help registry).

### Controls
- Open/close: **`c`** (naked).  Also add "Open Configuration" to the right-click
  context menu and register `c` in the help overlay.
- Tabs: click or `Left`/`Right`; items: `Up`/`Down`; adjust: `[ ]` / wheel / drag;
  `Esc` closes; text-entry mode for the profile name (gated like other modals).

---

## 5) Build increments (each independently green + committable)

1. **Foundation (this increment):** `ConfigProfileStore` + `App` effect-override
   layer (`_instantiate` merge, set/get/apply/save/load/clear) + `VJApi` surface +
   tests.  No UI yet.
2. **Modal shell:** `ConfigEditor` overlay — themed frame, tab bar, open on `c`,
   animation/sprite-border/hover-glow, event routing, help entry.  Tabs stubbed.
3. **Effects tab:** effect list (catalog) + parameter rows with live editing wired
   to Increment 1.
4. **Profile footer:** name entry + Save/Load/Delete/Revert + dirty state.
5. **Audio + Visuals tabs.**
6. **Later:** Drop-ins + Bindings tabs.

---

## 6) Open questions / notes

- **Parameter metadata:** `parameters` are bare floats with no min/max/label.  For
  good sliders we need ranges.  Options: (a) infer from `_initial_parameters` (e.g.
  0.25×–4× initial), (b) add optional `parameter_meta` to effects over time.  v1
  will infer sensible ranges and show the raw value; richer metadata is additive.
- **Auto-apply-on-start:** should a "default" profile auto-load at launch?  Deferred
  — v1 is manual load; a `[config] default_profile` can come later.
- **Reset semantics:** "Revert" clears overrides for the selected effect back to
  `config.toml` + randomized defaults (re-instantiate or restore
  `_initial_parameters`).
