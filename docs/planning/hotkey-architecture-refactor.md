# Hotkey Architecture Refactor Plan

Owner: Effects Team
Status: superseded in part
Last updated: 2026-06-03

---

## Background & Motivation

Two related bugs were diagnosed on 2026-06-01 via keystroke and app logs:

1. **Ctrl+Alt+J not toggling Auto VJ** — Wayland compositor was intercepting the
    keypress after the first few successful fires. `Left Ctrl` and `Left Alt` arrived
    in SDL but `J` was silently eaten by the compositor.
    Historical note: this document originally proposed/used SDL keyboard grab as a
    workaround. That runtime path was intentionally removed on 2026-06-03.

2. **Ctrl+N/P/R not changing ProjectM presets** — Two sub-causes:
    a. Same Wayland interception (previously mitigated by keyboard grab; now removed).
   b. ProjectM loaded with `0 preset(s)` because `preset_dir` was not configured —
      `next_preset()` returns `None` silently with no user feedback.

The architectural refactor below is the follow-on work to enforce the rule that
**drop-in hotkeys must be registered by the drop-in, not hard-coded in core**.

---

## Current State (Problem)

`unicornviz/hotkeys.py` `HotkeyHandler.handle()` contains hard-coded key
dispatch for every drop-in:

- `Ctrl+Alt+J/C/O/F/S/K` and `Ctrl+Alt+1..0` — auto-vj, candy-frame,
  control-room, grand-finale, spotify-pro, postfx slots
- `F8`, `Ctrl+F9/F10/F11` — streaming provider selection
- `Alt+U`, `Ctrl+U`, `Ctrl+Alt+U`, `Shift+U` — unicorn-tears overlays
- `KP_0..9`, `KP_PERIOD`, `KP_÷/×/−/+/Enter`, `Alt+[/]` — webcam PiP

Also, `VJApi` does not expose shims for several `App` methods that drop-ins
need to call, requiring them to reach into `app._private` state or be wired
through core indefinitely.

---

## Target Architecture

```
App startup
  └─ load drop-in
      └─ vj_api.register_key_handler('name', instance.handle_key)

Per-frame SDL KEYDOWN
  └─ HotkeyHandler.handle(sym, mod)
      ├─ Keystroke logger
      ├─ Auto VJ user-action guard
      ├─ Ctrl+Shift+N/P/R  (effect variant protocol — stays in core)
      ├─ Ctrl+N/P/R        (effect preset/scene/variant protocol — stays in core)
      ├─ for handler in vj_api.key_handlers:   ← NEW dispatch loop
      │    result = handler(sym, mod)
      │    if result is not False: flash result & return
      └─ Core keys (N/P/R playlist, F, Space, Tab, H, A, R, S, V, Z, …)
```

Handler return convention:
- `str` — handled; flash the string as an overlay message
- `None` — handled silently (no flash needed)
- `False` — not handled; pass to next handler / fall through to core

---

## Implementation Tasks

### Task 1 — Fix ProjectM silent failure feedback
**File:** `unicornviz/hotkeys.py` lines 281–317
**Change:** In the `Ctrl+N/P/R` variant-navigation block, when the method
returns a falsy result (method exists but returns `None` or `''`), flash
`'No presets / variants loaded'` instead of silently returning. This gives
the user immediate feedback if ProjectM has no presets configured.

```python
# Current (simplified):
result = method()
if result:
    o.flash_message(f'{label}: {result}', 1.5)
return

# Target:
result = method()
if result:
    o.flash_message(f'{label}: {result}', 1.5)
else:
    o.flash_message(f'{label}: nothing loaded', 1.5)
return
```

---

### Task 2 — Add missing shims to `VJApi`
**File:** `unicornviz/vj_api.py`

Add thin delegation methods so drop-ins never need `self._app.*`:

| New method | Delegates to |
|---|---|
| `toggle_auto_vj() -> str` | `self._app.toggle_auto_vj()` |
| `toggle_candy_frame() -> str` | `self._app.toggle_candy_frame()` |
| `select_postfx_slot(slot: int) -> str` | `self._app.select_postfx_slot(slot)` |
| `set_stream_provider(provider: str) -> str` | `self._app.set_stream_provider(provider)` |
| `abort_grand_finale() -> str` | `self._app.abort_grand_finale()` |
| `set_camera_layout(token: str) -> bool` | `self._app.set_camera_layout(token)` |
| `scale_pip(delta: float) -> float` | `self._app.scale_pip(delta)` |
| `goto_prev_webcam_effect() -> str \| None` | `self._app.goto_prev_webcam_effect()` |
| `goto_next_webcam_effect() -> str \| None` | `self._app.goto_next_webcam_effect()` |
| `toggle_webcam_auto_cycle() -> bool` | `self._app.toggle_webcam_auto_cycle()` |

Existing shims already in `VJApi` (no change needed): `toggle_streaming`,
`toggle_control_room`, `trigger_rainbow_nova`, `trigger_dancing_unicorn`,
`trigger_grand_finale`, `trigger_burst`.

---

### Task 3 — Add hotkey handler registry to `VJApi`
**File:** `unicornviz/vj_api.py`

```python
# Add to __init__:
self._key_handlers: dict[str, Callable[[int, int], str | None | bool]] = {}

def register_key_handler(
    self,
    name: str,
    handler: Callable[[int, int], 'str | None | bool'],
) -> None:
    """Register a drop-in key handler.

    handler(sym, mod) must return:
      str   — handled; flash this message
      None  — handled silently
      False — not handled; pass through
    """
    self._key_handlers[name] = handler
    log.debug('Key handler registered: %s', name)

def unregister_key_handler(self, name: str) -> None:
    """Remove a previously registered handler (e.g. on drop-in teardown)."""
    self._key_handlers.pop(name, None)

@property
def key_handlers(self) -> list[Callable[[int, int], 'str | None | bool']]:
    """Current list of registered handlers in insertion order."""
    return list(self._key_handlers.values())
```

---

### Task 4 — Update `HotkeyHandler.handle()` dispatch loop
**File:** `unicornviz/hotkeys.py`

After the `Ctrl+N/P/R` block (line ~317) and before the `if sym == sdl2.SDLK_ESCAPE`
block (line ~368), insert the registered-handler dispatch:

```python
# Registered drop-in key handlers.
for _handler in a.vj_api.key_handlers:
    _result = _handler(sym, mod)
    if _result is not False:
        if isinstance(_result, str) and _result:
            o.flash_message(_result, 2.0)
        return
```

Then **remove** these now-redundant blocks from `handle()`:
- `if (mod & KMOD_CTRL) and (mod & KMOD_ALT):` entire block (lines 165–219)
    except `Ctrl+Alt+K` (webcam editor modal — keep it)
- `elif sym == sdl2.SDLK_F8:` streaming toggle
- `elif (mod & sdl2.KMOD_CTRL) and sym == sdl2.SDLK_F9/F10/F11:` stream providers
- `elif sym == sdl2.SDLK_u:` all unicorn-tears U variants
- `elif sym == sdl2.SDLK_KP_*:` all webcam numpad controls (lines 849–915)
- `elif sym == sdl2.SDLK_LEFTBRACKET` and `RIGHTBRACKET` Alt+variant PiP sizing
  (keep the plain `[` and `]` reactivity cases)
- The `_ctrlj_armed` state vars and leader-key block (lines 36–38, 221–278) —
  this state moves into `AutoVJController.handle_key()`

**Stays in core (do not remove):**
- `Ctrl+Shift+N/P/R` effect variant protocol
- `Ctrl+N/P/R` effect preset/scene/variant protocol
- `Ctrl+Alt+K` webcam editor modal toggle
- All single-key bindings: N/P/R playlist, F, Space, Tab, H, ?, A, M, R, S, V,
  Z, K, T, G, E, +, -, ,, ., ;, ', \\, I, X, F6, F7, F9 streaming CTA,
  digit shortcuts 0–9 / Shift+0–9 / Ctrl+0–9 / Alt+0–9

---

### Task 5 — auto-vj-01: move hotkeys into `AutoVJController`
**File:** `drop-ins/auto-vj-01/auto_vj.py`

Add `handle_key(self, sym: int, mod: int) -> str | None | bool` to
`AutoVJController`. Move all Auto VJ key logic from core into this method:

| Combo | Action |
|---|---|
| `Ctrl+Alt+J` | `self.toggle()` |
| `Ctrl+Shift+J` | `self.toggle()` |
| `Ctrl+J` (no Alt) | arm leader key (set `_ctrlj_armed`, `_ctrlj_arm_t`) |
| `*` (when armed) | sub-command dispatch: A/B/P/R/C/M |
| `Ctrl+Alt+Shift+D` | dev: reset + trigger `_trigger_fire_dj_celebration()` |

State fields `_ctrlj_armed: bool` and `_ctrlj_arm_t: float` move from
`HotkeyHandler.__init__` into `AutoVJController.__init__`.

The flash messages for the armed state and sub-commands are returned as
strings from `handle_key()` so the dispatch loop flashes them.

Note: `SDLK_j` sub-command constant and `_CTRLJ_WINDOW = 3.0` move here too.

---

### Task 6 — candy-frame-01: move hotkey into `CandyFrameController`
**File:** `drop-ins/candy-frame-01/candy_frame_controller.py`

```python
def handle_key(self, sym: int, mod: int) -> str | None | bool:
    if (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_ALT) and sym == sdl2.SDLK_c:
        return self._vj_api.toggle_candy_frame()
    return False
```

---

### Task 7 — control-room-01: add top-level hotkey handler
**File:** `drop-ins/control-room-01/control_room.py`

The control room already has internal keyboard handling for its own UI (not
changed). Add a top-level `handle_key` that handles only the
open/close trigger:

```python
def handle_key(self, sym: int, mod: int) -> str | None | bool:
    if (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_ALT) and sym == sdl2.SDLK_o:
        _active, msg = self._vj_api.toggle_control_room()
        return msg
    return False
```

---

### Task 8 — grand-finale-01: move hotkeys into `GrandFinaleController`
**File:** `drop-ins/grand-finale-01/grand_finale.py`

```python
def handle_key(self, sym: int, mod: int) -> str | None | bool:
    if (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_ALT) and sym == sdl2.SDLK_f:
        if mod & sdl2.KMOD_SHIFT:
            return self._vj_api.abort_grand_finale()
        return self._vj_api.trigger_grand_finale()
    return False
```

---

### Task 9 — spotify-01: move Spotify auth hotkeys into `SpotifyController`
**File:** `drop-ins/spotify-01/spotify_controller.py`

```python
def handle_key(self, sym: int, mod: int) -> str | None | bool:
    if (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_ALT) and sym == sdl2.SDLK_s:
        if mod & sdl2.KMOD_SHIFT:
            return self.logout()
        return self.begin_auth_async()
    return False
```

---

### Task 10 — postfx-01: move hotkeys into `PostFXController`
**File:** `drop-ins/postfx-01/postfx_controller.py`

```python
def handle_key(self, sym: int, mod: int) -> str | None | bool:
    if (mod & sdl2.KMOD_CTRL) and (mod & sdl2.KMOD_ALT):
        if sdl2.SDLK_1 <= sym <= sdl2.SDLK_9:
            slot = int(sym - sdl2.SDLK_0)
            return self._vj_api.select_postfx_slot(slot)
        if sym == sdl2.SDLK_0:
            return self._vj_api.select_postfx_slot(10)
    return False
```

---

### Task 11 — streaming-01: move hotkeys into `RTMPStreamer`
**File:** `drop-ins/streaming-01/rtmp_streamer.py`

```python
def handle_key(self, sym: int, mod: int) -> str | None | bool:
    import sdl2 as _sdl2
    if sym == _sdl2.SDLK_F8:
        _active, msg = self._vj_api.toggle_streaming()
        return msg
    if mod & _sdl2.KMOD_CTRL:
        if sym == _sdl2.SDLK_F9:
            return self._vj_api.set_stream_provider('rumble')
        if sym == _sdl2.SDLK_F10:
            return self._vj_api.set_stream_provider('youtube')
        if sym == _sdl2.SDLK_F11:
            return self._vj_api.set_stream_provider('custom')
    return False
```

---

### Task 12 — unicorn-tears-01: add `handle_key` to overlay controller
**File:** `drop-ins/unicorn-tears-01/unicorn_tears.py` (or whichever class is
registered as the runtime controller; check what `app.py` instantiates)

```python
def handle_key(self, sym: int, mod: int) -> str | None | bool:
    import sdl2 as _sdl2
    if sym == _sdl2.SDLK_u:
        if (mod & _sdl2.KMOD_CTRL) and (mod & _sdl2.KMOD_ALT):
            self._vj_api.trigger_burst()
            return '\U0001f300  BURST'
        if mod & _sdl2.KMOD_ALT:
            self._vj_api.trigger_rainbow_nova()
            return '\U0001f308  RAINBOW NOVA'
        if mod & _sdl2.KMOD_CTRL:
            self._vj_api.trigger_dancing_unicorn()
            return '\U0001f984  UNICORN INCOMING'
        if mod & _sdl2.KMOD_SHIFT:
            # Jump to Unicorn Tears effect
            cls = self._vj_api.find_effect('UnicornTears', 'Unicorn Tears')
            if cls:
                self._vj_api.goto_effect(cls)
                return None   # flash_name handled elsewhere
            return 'Unicorn Tears not found'
    return False
```

Note: `vj_api.find_effect(class_name, display_name)` and
`vj_api.goto_effect(cls)` may need to be added (Task 2 extension).

---

### Task 13 — webcam-01: add `handle_key` to `WebcamSystem`
**File:** `drop-ins/webcam-01/webcam_overlay.py`

Handle the full webcam key surface:

| Key | Action |
|---|---|
| `KP_0` | `set_camera_layout('0')` → `'Camera: fullscreen'` or `'Camera: not available'` |
| `KP_PERIOD` | `set_camera_layout('.')` → `'Camera: hidden'` |
| `KP_1..9` | `set_camera_layout('1'..'9')` → position label |
| `KP_DIVIDE` | `goto_prev_webcam_effect()` → name or not-available |
| `KP_MULTIPLY` | `goto_next_webcam_effect()` → name or not-available |
| `KP_MINUS` | `scale_pip(-0.05)` → `'Camera PiP: X%'` |
| `KP_PLUS` | `scale_pip(+0.05)` → `'Camera PiP: X%'` |
| `KP_ENTER` | `toggle_webcam_auto_cycle()` → `'Camera treatment auto-cycle: ON/OFF'` |
| `Alt+[` | `scale_pip(-0.05)` |
| `Alt+]` | `scale_pip(+0.05)` |

---

### Task 14 — `app.py`: wire `register_key_handler` after each load
**File:** `unicornviz/app.py`

After each drop-in controller is instantiated, call:

```python
self.vj_api.register_key_handler('auto_vj', self._auto_vj.handle_key)
self.vj_api.register_key_handler('candy_frame', self._candy_frame.handle_key)
self.vj_api.register_key_handler('control_room', self._control_room.handle_key)
self.vj_api.register_key_handler('grand_finale', self._grand_finale.handle_key)
self.vj_api.register_key_handler('spotify', self._spotify.handle_key)
self.vj_api.register_key_handler('postfx', self._postfx.handle_key)
self.vj_api.register_key_handler('streaming', self._streaming.handle_key)
self.vj_api.register_key_handler('unicorn_tears', self._unicorn_tears.handle_key)
self.vj_api.register_key_handler('webcam', self._webcam_system.handle_key)
```

Each registration must be inside the same `try/except` block that loads the
drop-in, so a missing drop-in simply skips registration without crashing.

On drop-in teardown (e.g., control room unload), call:
```python
self.vj_api.unregister_key_handler('control_room')
```

---

## Files Changed (summary)

| File | Change |
|---|---|
| `unicornviz/hotkeys.py` | Add dispatch loop; remove drop-in key blocks; remove `_ctrlj_armed` state |
| `unicornviz/vj_api.py` | Add 10 new shims; add `register_key_handler` / `unregister_key_handler` / `key_handlers` |
| `unicornviz/app.py` | Wire `register_key_handler` after each drop-in load |
| `drop-ins/auto-vj-01/auto_vj.py` | Add `handle_key`; absorb `_ctrlj_armed` state |
| `drop-ins/candy-frame-01/candy_frame_controller.py` | Add `handle_key` |
| `drop-ins/control-room-01/control_room.py` | Add top-level `handle_key` |
| `drop-ins/grand-finale-01/grand_finale.py` | Add `handle_key` |
| `drop-ins/spotify-01/spotify_controller.py` | Add `handle_key` |
| `drop-ins/postfx-01/postfx_controller.py` | Add `handle_key` |
| `drop-ins/streaming-01/rtmp_streamer.py` | Add `handle_key` |
| `drop-ins/unicorn-tears-01/unicorn_tears.py` | Add `handle_key` |
| `drop-ins/webcam-01/webcam_overlay.py` | Add `handle_key` |

---

## What Does NOT Change

- `HELP_ENTRIES` / `register_help_entries` / `discover_dropin_help_entries` —
  the help overlay registration system is already correct; this refactor does
  not touch it
- `Ctrl+Alt+K` (webcam editor modal) — stays in `hotkeys.py`
- All single-key and Ctrl+Shift+N/P/R bindings in `hotkeys.py`
- The `Ctrl+N/P/R` effect preset/scene/variant protocol in `hotkeys.py`
- The Ctrl+J leader key flash message `'AUTO VJ → A/B/P/R/C/M'` format
- Control room's internal UI keyboard handling (arrow keys, Enter, Escape) —
  this is separate from the open/close trigger

---

## Testing Checklist

After implementation, verify each binding still fires correctly by running the
app and pressing each key combination once while watching the keystroke log
and app log:

- [ ] `Ctrl+Alt+J` / `Ctrl+Shift+J` — toggle Auto VJ
- [ ] `Ctrl+J` then `A/B/P/R/C/M` — Auto VJ sub-commands
- [ ] `Ctrl+Alt+C` — toggle Candy Frame
- [ ] `Ctrl+Alt+O` — open/close Control Room
- [ ] `Ctrl+Alt+F` / `Ctrl+Alt+Shift+F` — trigger/abort Grand Finale
- [ ] `Ctrl+Alt+S` / `Ctrl+Alt+Shift+S` — Spotify auth/logout
- [ ] `Ctrl+Alt+1..9`, `Ctrl+Alt+0` — PostFX slot selection
- [ ] `F8` — streaming toggle
- [ ] `Ctrl+F9/F10/F11` — streaming provider selection
- [ ] `Alt+U`, `Ctrl+U`, `Ctrl+Alt+U`, `Shift+U` — unicorn-tears triggers
- [ ] `KP_0..9`, `KP_PERIOD`, `KP_÷/×/−/+/Enter` — webcam layout / treatment
- [ ] `Alt+[`, `Alt+]` — webcam PiP size
- [ ] `Ctrl+N/P/R` with ProjectM active — flash `'No presets / variants loaded'`
  when 0 presets configured
- [ ] All core single-key bindings still work (N, P, R, F, Space, etc.)
- [ ] Help overlay (H) still shows all drop-in entries correctly
