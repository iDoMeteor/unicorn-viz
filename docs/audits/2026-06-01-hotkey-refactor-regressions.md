# Hotkey Refactor — P0 Regression Hotfix Brief (2026-06-01)

Owner: Auto VJ team + Effects team + Core
Status: action required — blocks demo/tag
Last updated: 2026-06-01

This is the actionable companion to
`docs/audits/2026-06-01-system-audit.md`. It isolates the two showstopper
regressions introduced by the in-flight hotkey-architecture refactor
(`docs/planning/hotkey-architecture-refactor.md`) so the owning teams can ship a
hotfix without reading the full audit.

Both regressions share a root cause: drop-in `handle_key()` methods were added,
but (a) one overwrote an existing method definition, and (b) one calls
`VJApi` methods that don't exist / have the wrong signature. Neither is caught
at import time, and the key-dispatch path has no exception isolation, so they
surface as a **hard crash or a silently dead subsystem at runtime**.

---

## P0-1 — Auto VJ is dead on load (`_profile_value` deleted)

**Repo:** `drop-ins/auto-vj-01` (private submodule)
**File:** `auto_vj.py`
**Regressing commit:** `dbd656b` ("feat(hotkeys): add handle_key() and migrate
_ctrlj leader state…")

### What happened
The new `def handle_key(...)` was written over the line that previously held
`def _profile_value(self, key: str, fallback: Any) -> Any:`. The method *body*
survived as unreachable code after `handle_key`'s `return False`
(`auto_vj.py:810–817`), but the `def` header is gone.

Proof:
- `git show HEAD~1:auto_vj.py | grep -n 'def _profile_value'` → present at 654.
- Current file → **absent** (AST scan confirms no `_profile_value` FunctionDef).
- `self._profile_value(...)` is called **122×**, first at `auto_vj.py:633`
  inside `__init__`.

### Runtime effect
`AutoVJController.__init__` raises `AttributeError: ... has no attribute
'_profile_value'`. `app.py` swallows it in the drop-in load `try/except`, so the
app launches but **Auto VJ never loads** — no automation, no ping-pong, no
profiles. A bare `import auto_vj` does **not** fail, so import-only CI misses it.

### Fix
1. Delete the orphaned block after `handle_key`'s `return False`
   (`auto_vj.py:811–817`).
2. Re-add the method at its original home (next to `_profile_label` /
   `_set_active_profile`):
   ```python
   def _profile_value(self, key: str, fallback: Any) -> Any:
       """Resolve a profile-tunable value: user override → preset default → fallback."""
       if self._use_user_profile_overrides and key in self._explicit_profile_override_keys:
           return self._cfg.get(key)
       if key in self._profile_defaults:
           return self._profile_defaults[key]
       return fallback
   ```
3. Verify locally:
   ```bash
   cd /home/jj/Repos/unicorn-viz
   .venv/bin/python - <<'PY'
   import ast
   t = ast.parse(open('drop-ins/auto-vj-01/auto_vj.py').read())
   names = {n.name for n in ast.walk(t) if isinstance(n, ast.FunctionDef)}
   assert '_profile_value' in names, 'still missing!'
   print('OK: _profile_value defined')
   PY
   ```
4. Commit + push in `auto-vj-01`, then bump the submodule pointer in
   `unicorn-viz` (Drop-In Source Policy).

---

## P0-2 — `U` / `Shift+U` crash the whole app (unicorn-tears)

**Repos:** `drop-ins/unicorn-tears-01` (drop-in) + `unicornviz/vj_api.py` (core)
**Files:** `unicorn_tears.py:444–467`, `vj_api.py:231`

### What happened
`UnicornTearsController.handle_key` calls two `VJApi` methods that don't match
the surface:

| Line | Call | Problem |
|------|------|---------|
| `unicorn_tears.py:466` | `self._vj_api.show_splash()` | `VJApi` has **no** `show_splash` (only `App` does, `app.py:1730`) → `AttributeError` on plain `U` |
| `unicorn_tears.py:461` | `self._vj_api.find_effect('UnicornTears')` | `VJApi.find_effect(class_name, display_name)` needs **2** positional args (`vj_api.py:231`) → `TypeError` on `Shift+U` |

Because `hotkeys.py:204–210` and `app.py:2043` have no `try/except`, the
exception propagates out of the event loop and **crashes the app**.

### Fix — Core (`unicornviz/vj_api.py`)
Add the missing splash shim and make the display-name optional:
```python
def show_splash(self) -> None:
    """Replay the startup splash sequence."""
    self._app.show_splash()

def find_effect(self, class_name: str, display_name: str | None = None) -> type | None:
    """Return the effect class matching class_name or (optional) display_name."""
    for cls in get_effects():
        if cls.__name__ == class_name or (display_name and cls.NAME == display_name):
            return cls
    return None
```

### Fix — Drop-in (`drop-ins/unicorn-tears-01/unicorn_tears.py`)
Use the explicit two-arg form (matches the refactor plan, Task 12) and flash the
effect name so `Shift+U` keeps its banner (audit A-11):
```python
if mod & sdl2.KMOD_SHIFT:
    cls = self._vj_api.find_effect('UnicornTears', 'Unicorn Tears')
    if cls is not None:
        self._vj_api.goto_effect(cls)
        return cls.NAME           # dispatch loop flashes the name
    return 'Unicorn Tears not found'
self._vj_api.show_splash()
return 'Splash replay'
```
Also correct `HELP_ENTRIES` (audit A-07): `Shift+U` = jump to effect, `U` =
replay splash.

---

## Strongly recommended alongside the hotfix — make dispatch crash-proof (A-03)

So the *next* drop-in key bug degrades instead of crashing, harden the loop in
`unicornviz/hotkeys.py` (`~line 204`):
```python
for _name, _handler in a.vj_api.key_handler_items():   # add this public iterator to VJApi
    try:
        _result = _handler(sym, mod)
    except Exception:
        log.exception('Key handler %r raised; unregistering', _name)
        a.vj_api.unregister_key_handler(_name)
        continue
    if _result is not False:
        if isinstance(_result, str) and _result:
            o.flash_message(_result, 2.0)
        return
```
Add to `VJApi`:
```python
def key_handler_items(self) -> list[tuple[str, Callable[[int, int], 'str | None | bool']]]:
    """Registered (name, handler) pairs in insertion order."""
    return list(self._key_handlers.items())
```

---

## Verification checklist (run after all three fixes)

- [ ] App launches; log shows `AutoVJController Phase 4 enabled` (not the
      `not available` warning).
- [ ] `Ctrl+Alt+J` toggles Auto VJ; `Ctrl+J` then `A/B/P/R/C/M` works.
- [ ] Plain `U` replays splash; `Shift+U` jumps to Unicorn Tears and flashes its
      name; `Ctrl+U`, `Alt+U`, `Ctrl+Alt+U` fire their overlays — **no crash**.
- [ ] Temporarily make a drop-in `handle_key` raise → app logs and unregisters
      it, keeps running (A-03 isolation works).
- [ ] `H` help overlay shows corrected Unicorn Tears bindings.
