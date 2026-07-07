# MIDI Drop-In Extraction Plan

**Owner:** (to be assigned)  
**Status:** Planning  
**Last Updated:** June 18, 2026

---

## Executive Summary

This plan describes a clean extraction of MIDI support from the core unicorn-viz package into an optional drop-in subsystem. The goal is to simplify packaging for app distributors by making MIDI support optional and decoupled from the main application lifecycle.

**Key Constraints:**
- Zero legacy remnants — no compatibility shims or dual-path code
- Single source of truth after extraction: MIDI code lives in drop-in only
- Maintain full feature parity during migration
- All regression tests must pass before completion

---

## Current State Snapshot

### Core MIDI Coupling

**App Lifecycle** (`unicornviz/app.py`):
- Line 2308: Read MIDI device hint and preset from config.toml
- Line 2310–2311: Parse cc_map and note_map config overrides
- Line 2315–2322: Construct MidiManager, start(), store as `_midi_manager`
- Line 2674–2676: Call midi_manager.maintenance_update() and hotkeys.process_pending_midi() per frame
- Line 3366: Call midi_manager.stop() on shutdown
- Line 4193–4201: Expose `midi_action_for_note()` and `midi_param_for_cc()` as public API methods
- Line 4203–4223: Expose `select_midi_device()` and `get_midi_ports()` as public API methods

**Hotkey Dispatch** (`unicornviz/hotkeys.py`):
- Line 18: Import MidiManager and MidiEvent from unicornviz.midi
- Line 24–34: Define MIDI note key bindings and MIDI selector hotkey (Alt+M)
- Line 59–83: Define MIDI context slot bindings (audio_selector, midi_selector)
- Line 168: Queue for pending MIDI events (deque)
- Line 171–177: attach_midi() method registers listener
- Line 179–232: process_pending_midi() and _dispatch_midi_event() dispatch events on main thread
- Line 261–287: _active_midi_context() resolves context for contextual dispatch
- Line 755–767: MIDI selector navigation (Up/Down/Enter/Esc)
- Line 1093–1099: Alt+M hotkey triggers selector modal

**VJ API Surface** (`unicornviz/vj_api.py`):
- Line 447–480: sync_midi_selector() refreshes overlay port rows
- Line 482–495: close_midi_selector() and open_midi_selector()
- Line 497–510: set_midi_selector_index() and get_midi_selector_index()
- Line 512–517: select_midi_device() dispatches to app._midi_manager.reopen()

**Overlay UI** (`unicornviz/overlays.py`):
- Line 870: `_show_midi` state variable
- Line 879–881: MIDI ports and current port state tracking
- Line 2289–2330: _render_midi_selector() modal rendering
- Line 2289–2326: set_midi_ports(), move_midi_selection(), get_midi_selected_port(), etc.
- Line 3786–3787: midi_selector_visible property
- Line 3870–3876: MIDI selector row generation in snapshot
- Line 4230–4231: toggle_midi_selector()

**Config Defaults** (`unicornviz/config.py`):
- Line 65–69: [midi] section with device, preset, cc_map, note_map

**Packaging**:
- `pyproject.toml` line 17: `python-rtmidi>=1.5` in core dependencies
- `requirements.txt` line 7: `python-rtmidi>=1.5`

**Core Module** (`unicornviz/midi.py`):
- ~600 lines: MidiManager class, BUILTIN_PRESETS, event routing, port resolution

**Tests Affected**:
- `tests/test_midi_port_resolution.py` — MidiManager._resolve_target_indices unit tests
- `tests/test_midi_apc_preset.py` — BUILTIN_PRESETS coverage
- `tests/test_hotkeys_behavior.py` — MIDI event dispatch in hotkeys (7 tests)
- `tests/test_hotkeys_m_family.py` — Alt+M and MIDI selector tests

---

## Proposed Extraction Plan

### Phase 1: Create MIDI Drop-In Repository & Submodule

**Goal:** Establish independent MIDI drop-in with full feature parity.

**Steps:**

1. Create new private GitHub repository: `unicorn-viz-midi-01` (or similar naming)
2. Add as git submodule in main repo at `drop-ins/midi-01/`
3. Implement drop-in structure:
   ```
   drop-ins/midi-01/
   ├── __init__.py
   ├── midi_controller.py          # Main subsystem (replaces app wiring)
   ├── midi_engine.py              # Moved from unicornviz/midi.py
   ├── midi_hotkey_handler.py      # MIDI event dispatch (replaces hotkeys.py logic)
   ├── midi_overlay.py             # MIDI selector modal rendering
   ├── config_validator.py         # Optional config validation
   ├── pyproject.toml              # Drop-in dependencies (python-rtmidi)
   ├── requirements.txt
   ├── docs/
   │   ├── operations.md
   │   ├── configuration.md
   │   ├── integration.md
   │   └── troubleshooting.md
   └── tests/
       ├── test_midi_port_resolution.py  (moved from core tests)
       ├── test_midi_apc_preset.py       (moved from core tests)
       └── test_midi_integration.py      (new)
   ```

4. Define DROPIN_CAPABILITIES in midi_controller.py:
   ```python
   DROPIN_CAPABILITIES = {
       'name': 'midi',
       'class_symbol': 'MidiController',
       'subsystem_name': 'midi',
       'key_handler_attr': 'handle_key',
   }
   ```

5. Implement MidiController class with:
   - Constructor takes (app, config)
   - Owns MidiManager lifecycle (construct, start, stop, maintenance)
   - Registers key handler for MIDI event dispatch
   - Implements handle_key(sym, mod) → bool | str | None for subsystem key bindings
   - Provides public read-only properties for querying device/port state
   - Exposes methods for device selection, port enumeration (called via VJ API)

### Phase 2: Switch Core App to Drop-In Capability Registration

**Goal:** Make app agnostic to MIDI implementation; register drop-in via capability system.

**Changes to `unicornviz/app.py`:**

1. Remove lines 2308–2322 (MIDI manager construction and startup)
2. Remove lines 2674–2676 (MIDI maintenance call)
3. Remove lines 3366 (MIDI stop call)
4. Remove lines 4193–4223 (midi_action_for_note, midi_param_for_cc, select_midi_device, get_midi_ports methods)
5. Remove line 34: `from unicornviz.midi import MidiManager`
6. At startup (after effects/overlays are ready), add generic drop-in registration pattern similar to banner/control-room:
   ```python
   # MIDI controller (optional drop-in)
   try:
       midi_capabilities = _load_midi_capabilities()
       if midi_capabilities:
           midi_cls = load_runtime_capability_class(midi_capabilities)
           midi_cfg = self.cfg.get('midi', default={}) or {}
           midi_instance = midi_cls(self, midi_cfg)
           register_runtime_capability(self.vj_api, midi_instance, midi_capabilities)
           log.info('MIDI controller loaded from drop-in')
   except Exception as exc:
       log.info('MIDI drop-in unavailable: %s', exc)
   ```

7. Remove `self._midi_manager` instance variable entirely
8. Add new VJ API wrapper methods (thin shims) that delegate to drop-in via subsystem lookup:
   ```python
   def midi_action_for_note(self, number: int) -> str | None:
       """Query MIDI note-to-action mapping from registered MIDI subsystem."""
       midi = self.get_subsystem('midi')
       if midi is None:
           return None
       method = getattr(midi, 'action_for_note', None)
       return method(number) if callable(method) else None
   
   def midi_param_for_cc(self, number: int) -> str | None:
       """Query MIDI CC-to-param mapping from registered MIDI subsystem."""
       midi = self.get_subsystem('midi')
       if midi is None:
           return None
       method = getattr(midi, 'param_for_cc', None)
       return method(number) if callable(method) else None
   
   def select_midi_device(self, port_name: str) -> str:
       """Reopen MIDI device on registered MIDI subsystem."""
       midi = self.get_subsystem('midi')
       if midi is None:
           return 'MIDI: subsystem unavailable'
       method = getattr(midi, 'reopen', None)
       return method(port_name) if callable(method) else 'MIDI selection failed'
   
   def get_midi_ports(self) -> list[str]:
       """List available MIDI ports from registered MIDI subsystem."""
       midi = self.get_subsystem('midi')
       if midi is None:
           return []
       method = getattr(midi, 'list_ports', None)
       return method() if callable(method) else []
   ```

### Phase 3: Remove Core MIDI Code (No Remnants)

**Goal:** Delete unicornviz/midi.py and all direct MIDI wiring from hotkeys; no shims.

**Changes:**

1. **Delete unicornviz/midi.py entirely** (after drop-in is complete)
2. **Remove MIDI from `unicornviz/hotkeys.py`:**
   - Remove line 18 import
   - Remove lines 24–34 (_MIDI_NOTE_KEY_BINDINGS and midi_selector hotkey definition)
   - Remove lines 59–83 (_MIDI_CONTEXT_SLOT_BINDINGS)
   - Remove lines 168–169 (pending MIDI event queue and lock)
   - Remove lines 171–177 (attach_midi method)
   - Remove lines 179–232 (process_pending_midi and _dispatch_midi_event)
   - Remove lines 261–287 (_active_midi_context)
   - Remove MIDI selector navigation section (lines 755–767)
   - Remove Alt+M hotkey handler section (lines 1093–1099)
   - Remove call to `hotkeys.attach_midi(midi_manager)` from app.py line 2421
3. **Remove `process_pending_midi()` call from app main loop** (app.py line 2676)

### Phase 4: Move Overlay UI to Drop-In

**Goal:** MIDI selector modal and state belong in drop-in, not core overlays.

**Changes to `unicornviz/overlays.py`:**

1. Remove lines 870, 879–881 (MIDI state variables)
2. Remove lines 2289–2330 (set_midi_ports, move_midi_selection, get_midi_selected_port, etc. and _render_midi_selector)
3. Remove line 3786–3787 (midi_selector_visible property)
4. Remove MIDI selector generation in snapshot (lines 3870–3876)
5. Remove line 4230–4231 (toggle_midi_selector)
6. Remove MIDI modal check from render path (lines 2135–2136, 2169–2170)
7. Remove call to toggle_midi_selector in ESC handler

Drop-in registers its own overlay renderer via subsystem or custom VJ API surface if needed.

### Phase 5: Move Configuration to Drop-In

**Goal:** MIDI config lives under drop-in namespace only.

**Changes to `unicornviz/config.py`:**

1. Remove lines 65–69 ([midi] section from _DEFAULTS dict)
2. Update config comments to note MIDI is now optional and configured within drop-in if installed

**Update `config.toml`:**

1. Keep [midi] section commented-out with note pointing to drop-in docs
2. Add comment: "MIDI support is optional. See drop-ins/midi-01/docs/ for configuration."

### Phase 6: Remove MIDI from Core Dependencies

**Goal:** Make python-rtmidi optional for distributors.

**Changes:**

1. **Remove from `pyproject.toml`:**
   - Delete line 17: `"python-rtmidi>=1.5",`
2. **Remove from `requirements.txt`:**
   - Delete line 7: `python-rtmidi>=1.5`
3. **Optional: Add optional dependency group in pyproject.toml:**
   ```toml
   [project.optional-dependencies]
   midi = ["python-rtmidi>=1.5"]
   ```
   So developers can install with `pip install unicorn-viz[midi]` if desired, but it's not required.

### Phase 7: Migrate and Update Tests

**Goal:** Move MIDI tests to drop-in; update hotkey tests to not assume MIDI.

**Moves:**

1. Move `tests/test_midi_port_resolution.py` → `drop-ins/midi-01/tests/test_midi_port_resolution.py`
2. Move `tests/test_midi_apc_preset.py` → `drop-ins/midi-01/tests/test_midi_apc_preset.py`
3. Update imports in moved tests to reference drop-in module paths

**Updates in Core Tests:**

1. `tests/test_hotkeys_m_family.py`:
   - Remove Alt+M test that assumed core MIDI selector
   - Add new test: `test_alt_m_with_midi_drop_in_available()` that verifies Alt+M routes through drop-in key handler
   - Keep MIDI-agnostic contextual dispatch tests

2. `tests/test_hotkeys_behavior.py`:
   - Remove/rewrite tests that directly dispatch MidiEvent on core hotkeys (lines 264–373)
   - Add new integration tests in drop-in test suite verifying end-to-end MIDI→action flow through subsystem

**New Drop-In Tests** (`drop-ins/midi-01/tests/test_midi_integration.py`):

1. Test app boots without MIDI drop-in (python-rtmidi not installed)
2. Test app boots with MIDI drop-in but device unavailable
3. Test app boots with MIDI drop-in and valid device (or loopback)
4. Test MIDI selector modal opens/closes via VJ API when drop-in present
5. Test note/CC routing dispatches correctly through drop-in key handler
6. Test device hot-swap via select_midi_device() through drop-in

---

## Execution Order (Phased Approach)

### Phase A: Scaffold Drop-In

**Deliverable:** Drop-in with feature parity, runnable without core integration.

1. Create private drop-ins/midi-01 submodule repository
2. Move/rewrite unicornviz/midi.py → drop-ins/midi-01/midi_engine.py
3. Implement MidiController with DROPIN_CAPABILITIES
4. Implement midi_hotkey_handler.py with MIDI dispatch logic (copied from hotkeys.py)
5. Implement midi_overlay.py with modal rendering (copied from overlays.py)
6. Add config_validator.py if needed
7. Add pyproject.toml with python-rtmidi dependency
8. Add documentation (operations, configuration, integration)
9. Verify drop-in loads in isolation with test app harness
10. Run drop-in tests to confirm feature parity

### Phase B: Cut Core MIDI Wiring

**Deliverable:** App initializes drop-in via capability system; core no longer owns MIDI.

1. Update app.py to remove direct MIDI construction and startup
2. Add subsystem lookup wrappers in app.py for midi_action_for_note, etc.
3. Remove attach_midi call from hotkeys initialization
4. Add drop-in capability discovery and registration in app._build_optional_controllers()
5. Verify app boots without drop-in (graceful no-op)
6. Verify app boots with drop-in present and MIDI functions work

### Phase C: Remove Core MIDI Code

**Deliverable:** No legacy code; single source of truth in drop-in.

1. Delete unicornviz/midi.py
2. Remove MIDI logic from unicornviz/hotkeys.py
3. Remove MIDI state/rendering from unicornviz/overlays.py
4. Remove MIDI config defaults from unicornviz/config.py
5. Update config.toml comments
6. Remove python-rtmidi from pyproject.toml and requirements.txt
7. Run full test suite to confirm no regressions

### Phase D: Test Migration & Verification

**Deliverable:** All tests passing; regression coverage confirmed.

1. Move MIDI unit tests to drop-in test suite
2. Update hotkey tests to remove MIDI-specific direct tests
3. Add integration tests in drop-in
4. Run core test suite (no MIDI tests, all passing)
5. Run drop-in test suite (all passing)
6. Verify help text and hotkey audit still passes
7. Manual smoke test: app with MIDI connected, without MIDI connected, MIDI hot-swap

---

## Success Criteria

✓ **Feature Parity**
- MIDI device selection, preset mapping, CC/note dispatch all work identically before/after
- All existing MIDI workflows (APC mini mk2, generic devices) unaffected

✓ **Zero Remnants**
- No import of unicornviz.midi anywhere in core code
- No compatibility shim in unicornviz/
- No duplicate MIDI state or dispatch logic
- unicornviz/midi.py deleted; only drop-in copy exists

✓ **Optional Packaging**
- python-rtmidi removed from core dependencies
- Core package installs and runs without python-rtmidi
- MIDI drop-in installs and runs when present
- Fallback behavior graceful when drop-in missing

✓ **Regression Tests**
- All core tests pass (no MIDI-specific tests in core)
- All drop-in tests pass
- Hotkey/help audit passes
- Integration test suite verifies end-to-end flows

✓ **Documentation**
- Drop-in README and docs complete
- Config examples provided
- Integration guide for app developers

---

## Cleanup Checklist

- [ ] Create drop-ins/midi-01 submodule repository (private)
- [ ] Implement MidiController with parity behavior
- [ ] Add drop-in tests and documentation
- [ ] Verify drop-in loads in isolation
- [ ] Add drop-in discovery/registration in app.py
- [ ] Remove direct MIDI wiring from app.py/hotkeys.py/overlays.py
- [ ] Delete unicornviz/midi.py
- [ ] Update config.py and config.toml
- [ ] Move MIDI tests to drop-in
- [ ] Update core hotkey tests
- [ ] Remove python-rtmidi from dependencies
- [ ] Full regression test pass
- [ ] Manual smoke testing (MIDI connected and disconnected)
- [ ] Update copilot-instructions.md if needed
- [ ] Close issue/PR with summary

---

## References

- [Drop-In Independence Rules](../../.github/copilot-instructions.md#drop-in-independence-rules)
- [Public Runtime Surface Rules](../../.github/copilot-instructions.md#public-runtime-surface-rules)
- Existing drop-in examples: banner-01, control-room-01, postfx-01
- Runtime capability system: unicornviz/dropins.py (register_runtime_capability, etc.)

---

## Roadmap: scenes-01 Drop-In (Scene Recorder & Playback)

**Status:** Planned  
**Target:** v1.x — own private GitHub repo, wired as submodule at `drop-ins/scenes-01/`

### Overview

A scene is a named, ordered list of MIDI actions with relative timestamps.  Tapping
a pad replays the scene; holding a pad + pressing Shift arms it for recording.

### Architecture

```text
drop-ins/scenes-01/
  __init__.py
  scenes_controller.py   # main controller registered as 'scenes' subsystem
  scene_player.py        # timed action replay (deque of (action, fire_at))
  scene_store.py         # load/save TOML scene packs
  assets/
    scenes/default.toml  # default empty pack shipped with the drop-in
```

**SceneDefinition:**

```python
@dataclass
class SceneDefinition:
    name: str
    actions: list[tuple[str, float]]   # (action_name, delay_s_from_start)
    coded: Callable[[], None] | None = None  # overrides recorded actions
```

**SceneStore:**

- Loads TOML packs from `assets/scenes/<pack>.toml`
- A scene pack maps slot names (`slot_1` … `slot_N`) to `SceneDefinition`
- `save_pack()` writes back to the pack file

**ScenesController lifecycle:**

1. Constructed and registered as `vj_api` subsystem `'scenes'`
2. `set_vj_api(api)` → registers MIDI actions and registers itself as key handler
3. `update(dt)` → ticks the `ScenePlayer` timer queue

**MIDI action registration:**

```python
api.register_midi_actions('Scenes', [
    ('scene_arm',    'Arm scene record'),
    ('scene_slot_1', 'Scene Slot 1'),
    ('scene_slot_2', 'Scene Slot 2'),
    ...
    ('scene_slot_8', 'Scene Slot 8'),
])
```

Scene slots map to APC scene launch row (notes 112–119, 8 pads).

**Record flow:**

1. `scene_arm` action → controller enters ARMED state, flash-highlights pads
2. Tap `scene_slot_N` while armed → start recording to slot N; pad pulses red
3. Tap `scene_slot_N` again (or another pad, or key shortcut) → stop, save scene

**Keyboard shortcuts** (registered via `vj_api.register_key_handler`):

- `Ctrl+Alt+R` → arm record (same as `scene_arm` action)
- `Ctrl+Shift+1..8` → play scene slot 1–8
- `Ctrl+Alt+Shift+1..8` → arm record for scene slot 1–8

**Playback:**

- `ScenePlayer` holds a `deque[tuple[str, float]]` of `(action, fire_at)`
- `update(dt)` drains entries whose `fire_at <= time.monotonic()` and calls
  `vj_api.fire_midi_action(action)` for each

**Coded scenes** (v1.1+):

- Register a Python callable under a slot name via
  `scenes_controller.register_coded_scene('slot_5', my_fn)`
- On playback, `my_fn()` is called directly; recorded actions are ignored

**Persistence:**

- Scene packs live in `drop-ins/scenes-01/assets/scenes/default.toml` (ship empty)
- Runtime scenes are saved to `~/.config/unicornviz/scenes/` (user-writable, gitignored)
- The active pack path is configurable via `[scenes] pack = "path"` in `config.toml`

### LED feedback

Scene pads on the APC:

- Unbound slot → dim blue
- Bound scene → cyan
- Armed for record → pulsing orange
- Currently recording → solid red
- Playing back → pulsing green

These require additions to `_ACTION_COLORS` in `apc_leds.py`.

### Dependencies

- Registers via `vj_api.register_midi_actions` and `vj_api.fire_midi_action` (no core changes)
- Tap into the MIDI dispatch chain via existing `register_midi_action_handler` API
- Zero hard dependencies on any other drop-in

---

## Roadmap: Live Effect Builder Mode (v2.0 Feature)

**Status:** Deferred — requires core render pipeline work  
**Target:** v2.0

### Concept

In Effect Builder mode the APC's 8×8 pad grid becomes a **layer compositor**:
each row (or column) maps to a named visual effect running on its own framebuffer,
and pads toggle layers on/off.  The visible output is a real-time blend of all
active layers.

### Why this is v2.0

The current core renders exactly one effect to the primary framebuffer per frame.
Supporting simultaneous layers requires:

1. A `FramebufferStack` abstraction in `unicornviz/app.py` (core change)
2. Each layer effect renders to its own `moderngl.Framebuffer`
3. A blend compositor (additive / screen / multiply / alpha-over) renders the
   composited output
4. `BaseEffect` gains an optional `render_layer(fb, dt, audio)` entry point

### Minimum viable design (v2.0 milestone)

- `LayerCompositor` subsystem owned by a `layer-compositor-01` drop-in
- `VJApi` gains `enable_layer_mode()` / `disable_layer_mode()` and
  `set_layer_effect(index, effect_cls)` / `toggle_layer(index)` surface
- `midi-controllers-01` enters **layer mode** when `layer_mode_toggle` action fires:
  pads remap to `layer_0` … `layer_63` (toggle per pad)
- Shift+layer pad → opens a mini picker showing available effects for that slot

### Intermediate workaround (available today)

The 8 APC scene-launch pads (row 8) can be bound to `scene_slot_1..8` which
replays scenes that call `vj_api.goto_effect(...)`.  This gives a fast preset-switch
grid without layer blending — useful for a lot of live VJ workflows.
