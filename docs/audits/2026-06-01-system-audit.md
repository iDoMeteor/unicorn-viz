# Unicorn Viz — Full System Audit (2026-06-01)

Owner: Engineering
Status: active — findings open, awaiting team execution
Last updated: 2026-06-01

Scope: Whole-system consistency, latent bugs / side-effects, and optimization
opportunities, captured *during* the in-flight Fedora 44 compatibility pass and
the hotkey-architecture refactor (see
`docs/planning/hotkey-architecture-refactor.md`). This audit reviews the core
`unicornviz/` package and the core ↔ drop-in boundary, with the uncommitted
worktree changes included.

Companion document: `docs/audits/2026-06-01-hotkey-refactor-regressions.md`
holds the focused, copy-paste hotfix brief for the two P0 regressions below.

---

## How to read this

Each finding has: **ID**, **Severity**, **Owner team**, **Evidence**
(file:line), **Impact**, and a **Recommended solution / strategy**. Severities:

- 🔴 **P0 blocker** — breaks a shipping subsystem; fix before any demo/tag.
- 🟠 **P1 major** — incorrect behavior, crash risk, or independence violation.
- 🟡 **P2 quality** — consistency / maintainability / performance.
- 🔵 **P3 nice-to-have** — hygiene and future-proofing.

---

## Summary table

| ID | Sev | Area | Title | Owner |
|----|-----|------|-------|-------|
| A-01 | 🔴 | auto-vj-01 | `_profile_value` method deleted by hotkey migration — Auto VJ dead on load | Auto VJ |
| A-02 | 🔴 | unicorn-tears-01 | `handle_key` calls non-existent `vj_api.show_splash()` / wrong `find_effect` arity — crashes app on `U` / `Shift+U` | Effects + Core |
| A-03 | 🟠 | core/hotkeys | Drop-in key dispatch loop has no `try/except` — one bad handler crashes all input | Core |
| A-04 | 🟠 | core/dropins | Each drop-in `.py` is exec'd 2–3× at startup; duplicate class objects | Core |
| A-05 | 🟠 | core/hotkeys | Core reaches into drop-in private `_ctrlj_armed` — independence/surface violation | Core + Auto VJ |
| A-06 | 🟡 | repo | `build/lib/**` (51 stale files) committed — shadow copy with pre-refactor code | Engineering |
| A-07 | 🟡 | unicorn-tears-01 | `HELP_ENTRIES` mislabels `U` vs `Shift+U`; missing splash binding | Effects |
| A-08 | 🟡 | repo/process | No tests and no linter/formatter config despite documented Black/PEP 8 standard | Engineering |
| A-09 | 🟡 | core/app.py | `app.py` is 3,710 lines — monolith concentrating most runtime state | Core |
| A-10 | 🔵 | core/dropins | `abs(hash(str(path)))` module naming is fragile; prefer stable derived names | Core |
| A-11 | 🔵 | core/hotkeys | `Shift+U` no longer flashes effect name (minor UX regression) | Effects |

---

## 🔴 P0 — Blockers

### A-01 — Auto VJ controller crashes on construction (`_profile_value` deleted)

**Owner:** Auto VJ team (`drop-ins/auto-vj-01`)
**Evidence:**
- `drop-ins/auto-vj-01/auto_vj.py` — **no** `def _profile_value` exists in the
  file (AST scan: `has _profile_value def: False`), yet there are **122 call
  sites** of `self._profile_value(...)`, the first inside `__init__`
  (`auto_vj.py:633`).
- The method body is orphaned as unreachable code immediately after
  `handle_key`'s `return False` (`auto_vj.py:810–817`):
  ```python
          return False


          if self._use_user_profile_overrides and key in self._explicit_profile_override_keys:
              return self._cfg.get(key)
          if key in self._profile_defaults:
              return self._profile_defaults[key]
          return fallback
  ```
- History proves regression: `git show HEAD~1:auto_vj.py` has
  `def _profile_value(self, key: str, fallback: Any) -> Any:` at line 654; the
  hotkey-migration commit `dbd656b` overwrote that `def` line with
  `def handle_key(...)` and stranded the body.

**Impact:** `AutoVJController.__init__` raises `AttributeError: 'AutoVJController'
object has no attribute '_profile_value'`. `app.py` catches it in the drop-in
load `try/except`, so the app *starts*, but the **entire Auto VJ subsystem is
silently disabled** — the flagship automation feature. The file still parses
(`ast.parse` OK) and `python -c` import of the bare module won't fail, so CI
that only smoke-imports will miss it. It only manifests on instantiation.

**Recommended solution:**
1. Re-introduce the method header for the orphaned body as a *standalone*
   method (not after `handle_key`). Minimal fix:
   ```python
       def _profile_value(self, key: str, fallback: Any) -> Any:
           if self._use_user_profile_overrides and key in self._explicit_profile_override_keys:
               return self._cfg.get(key)
           if key in self._profile_defaults:
               return self._profile_defaults[key]
           return fallback
   ```
   Place it back at its original location (adjacent to `_profile_label` /
   `_set_active_profile`), and delete the orphaned lines after
   `handle_key`'s `return False`.
2. Commit + push in `auto-vj-01`'s own repo, then bump the submodule pointer in
   `unicorn-viz` (per Drop-In Source Policy).

**Strategy to prevent recurrence (see A-08):** add a one-line instantiation
smoke test that constructs each drop-in controller with a stub `vj_api`/`app`.
A pure import test is insufficient because this bug lives in `__init__`.

---

### A-02 — `UnicornTearsController.handle_key` crashes the app on `U` and `Shift+U`

**Owner:** Effects team (`drop-ins/unicorn-tears-01`) + Core (`vj_api.py`)
**Evidence:** `drop-ins/unicorn-tears-01/unicorn_tears.py:444–467`:
- Line 466: `self._vj_api.show_splash()` — **`VJApi` has no `show_splash`
  method** (`grep` count = 0; `show_splash` exists only on `App`,
  `app.py:1730`). Plain `U` → `AttributeError`.
- Line 461: `self._vj_api.find_effect('UnicornTears') or self._vj_api.find_effect('Unicorn Tears')`
  — but `VJApi.find_effect(self, class_name, display_name)` requires **two**
  positional args (`vj_api.py:231`). `Shift+U` → `TypeError: find_effect()
  missing 1 required positional argument: 'display_name'`.

**Impact:** Because the dispatch loop (`hotkeys.py:204–210`) and the event loop
(`app.py:2043`) have **no `try/except`**, either keypress propagates an
exception out of `handle()` and **crashes the application** mid-set. The
refactor plan (Task 12) specified `find_effect('UnicornTears', 'Unicorn Tears')`
and `return None`; the drop-in diverged from the plan.

**Recommended solution (two coordinated changes):**
1. **Core (`vj_api.py`):** add the missing public shim so drop-ins don't reach
   into `App`:
   ```python
   def show_splash(self) -> None:
       """Replay the startup splash sequence."""
       self._app.show_splash()
   ```
   Also make `find_effect`'s second arg optional to match call-site intent and
   the plan's single-name lookups:
   ```python
   def find_effect(self, class_name: str, display_name: str | None = None) -> type | None:
       for cls in get_effects():
           if cls.__name__ == class_name or (display_name and cls.NAME == display_name):
               return cls
       return None
   ```
2. **Drop-in (`unicorn_tears.py`):** call `find_effect('UnicornTears',
   'Unicorn Tears')` explicitly, and keep the splash path using the new shim.

---

## 🟠 P1 — Major

### A-03 — Drop-in key dispatch is not exception-isolated

**Owner:** Core (`unicornviz/hotkeys.py`, `unicornviz/app.py`)
**Evidence:** `hotkeys.py:204–210` calls `_handler(sym, mod)` with no guard;
`app.py:2043` calls `hotkeys.handle(...)` with no guard inside the event poll
loop (`app.py:2036–2043`).
**Impact:** Violates Drop-In Independence rule #3 ("missing/buggy drop-in must
degrade gracefully, never crash"). A-01/A-02 escalate from "feature broken" to
"app crash" precisely because of this missing isolation. Third-party / paid
effect packs make this a security-of-uptime concern.
**Recommended solution:** wrap each handler call defensively and disable a
repeatedly-failing handler:
```python
for _name, _handler in list(a.vj_api._key_handlers.items()):  # owner-module access OK
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
Prefer adding a public iterator on `VJApi` (e.g. `key_handler_items()`) so
`hotkeys.py` does not touch `_key_handlers` directly (keeps with Public Runtime
Surface Rules). As defense-in-depth, also wrap the `KEYDOWN` branch at
`app.py:2043` in `try/except` that logs and continues the frame.

### A-04 — Drop-in modules are executed multiple times at startup

**Owner:** Core (`unicornviz/dropins.py`)
**Evidence:** Three independent loaders each `spec.loader.exec_module()` the
same files with *different* synthetic module names:
- `discover_dropin_effect_classes()` globs `drop-ins/*/*.py` and execs all
  (`dropins.py:199–214`).
- `discover_dropin_help_entries()` globs `drop-ins/*/*.py` and execs all again
  (`dropins.py:233–266`).
- `load_dropin_symbol()` execs the specific controller file again per load
  (`dropins.py:176–189`).

There are **48** drop-in `.py` files. Effect + help discovery alone exec every
one **twice**; controller-bearing drop-ins (auto-vj, postfx, candy-frame, …) a
**third** time. Each exec re-imports `sdl2`/`numpy`, recompiles large embedded
GLSL strings, and **creates distinct class objects** — so the `UnicornTears`
class seen by effect discovery is a *different object* than the one in the help
pass, which can break `isinstance`/identity assumptions and doubles any
module-level side effects.
**Impact:** Slower, noisier startup; subtle identity bugs; duplicated
module-level logging.
**Recommended solution:** add a process-wide module cache in `dropins.py` keyed
by the resolved absolute path, and have all three loaders share it:
```python
_MODULE_CACHE: dict[Path, ModuleType] = {}

def _load_module_from_file(file_path: Path, module_name: str) -> ModuleType:
    key = file_path.resolve()
    cached = _MODULE_CACHE.get(key)
    if cached is not None:
        return cached
    ...  # existing exec logic
    _MODULE_CACHE[key] = module
    return module
```
Then derive `module_name` deterministically from the drop-in folder + stem
(see A-10) so cache keys and `sys.modules` entries are stable.

### A-05 — Core peeks at drop-in private state `_ctrlj_armed`

**Owner:** Core (`hotkeys.py`) + Auto VJ
**Evidence:** `hotkeys.py:122` —
`bool(getattr(a.auto_vj_controller, '_ctrlj_armed', False))`. The refactor moved
the leader-key state into `AutoVJController` (correct) but core still reaches
across the boundary into a private field to decide `is_auto_vj_control`.
**Impact:** Violates Public Runtime Surface Rules #2/#5 (cross-module callers
should use public surfaces). Couples core to an Auto-VJ internal that could be
renamed, silently breaking the user-action guard.
**Recommended solution:** expose a public read on the controller, e.g.
`AutoVJController.is_leader_armed -> bool`, and have core call that:
```python
or bool(getattr(a.auto_vj_controller, 'is_leader_armed', False))
```
Optionally promote to `vj_api.is_auto_vj_leader_armed()` so even the attribute
name is surface-stable.

---

## 🟡 P2 — Quality / consistency / performance

### A-06 — Stale `build/lib/**` committed to the repo

**Owner:** Engineering
**Evidence:** `git ls-files build/` → 51 tracked files, including
`build/lib/unicornviz/overlays.py` (still has the **old** hard-coded
`DROPIN_HELP_SECTIONS`) and `build/lib/unicornviz/app.py` (pre-refactor). Not in
`.gitignore` (`grep build .gitignore` → no match).
**Impact:** Confuses grep/audits (every search returns two hits), risks editing
the wrong copy, and bloats the repo with a divergent snapshot.
**Recommended solution:** `git rm -r --cached build/` and add `build/` to
`.gitignore`. Confirm `pyproject.toml` build backend regenerates it on demand.

### A-07 — `unicorn-tears-01` HELP_ENTRIES disagree with actual bindings

**Owner:** Effects
**Evidence:** `unicorn_tears.py:291–296` lists `('Unicorn Tears', 'U', 'Unicorn
Tears effect')`, but `handle_key` maps **plain `U` → splash replay** and
**`Shift+U` → goto effect** (`unicorn_tears.py:460–467`). Splash has no help
entry at all.
**Impact:** The `H` overlay (single source of truth for bindings) misleads
operators. Likely pre-existing, surfaced by the refactor.
**Recommended solution:** correct to:
```python
('Unicorn Tears', 'Shift+U', 'Jump to Unicorn Tears effect'),
('Unicorn Tears', 'U', 'Replay splash'),
('Unicorn Tears', 'Ctrl+U', 'Dancing unicorn overlay'),
('Unicorn Tears', 'Alt+U', 'Rainbow Nova celebration'),
('Unicorn Tears', 'Ctrl+Alt+U', 'Screen burst'),
```

### A-08 — No tests and no linter/formatter configuration

**Owner:** Engineering
**Evidence:** No `tests/`, no `test_*.py` (outside `build/`), and no
`ruff`/`flake8`/`black`/`pytest`/`mypy` config in `pyproject.toml` or
`requirements.txt`, despite the documented "PEP 8 + Black" and type-annotation
standards.
**Impact:** Regressions like A-01 (a deleted method) and A-02 (wrong arity /
missing attribute) ship undetected. These are exactly the class of bug a
linter (`undefined-name`, `no-member` via mypy) or a controller-construction
smoke test catches instantly.
**Recommended strategy (do not add tooling without owner sign-off):**
1. Adopt `ruff` (fast, single binary) with `F` (pyflakes) + `E` rules; it flags
   unreachable code after `return` and undefined names.
2. Add a minimal `pytest` smoke suite: (a) import every core module; (b)
   construct each drop-in controller against a stub `App`/`VJApi`; (c) assert
   `discover_dropin_help_entries()` and effect registry are non-empty.
3. Wire both into the existing GitHub Actions matrix (`.github/workflows`).

### A-09 — `app.py` monolith (3,710 lines)

**Owner:** Core
**Evidence:** `wc -l unicornviz/app.py` = 3,710; it holds all `_Null*`
fallbacks, every `_load_*` loader, SDL/GL init, the run loop, and ~15 drop-in
controller fields.
**Impact:** High cognitive load; merge-conflict hotspot; the place where the
A-01-style edit accidents are most likely.
**Recommended strategy (incremental, no behavior change):** extract cohesive
units behind the existing public surfaces — e.g. `app/_nulls.py` (all `_Null*`
classes), `app/_dropin_loaders.py` (all `_load_*_class` functions),
`app/_multihead.py` (mirror/PBO plumbing). Keep `App` as the orchestrator.

---

## 🔵 P3 — Hygiene / future-proofing

### A-10 — Fragile synthetic module names in `dropins.py`

**Owner:** Core
**Evidence:** `dropins.py:185,204,238` build module names via
`abs(hash(str(file_path)))`. With per-process hash randomization the name
differs every run, and three loaders coin three different names for one file
(feeding A-04).
**Recommended solution:** derive a stable, collision-resistant name, e.g.
`f'dropin.{file_path.parent.name}.{file_path.stem}'`, and pair it with the A-04
cache so each file maps to exactly one `sys.modules` entry.

### A-11 — `Shift+U` lost its effect-name banner

**Owner:** Effects
**Evidence:** Pre-refactor core called `o.flash_name(cls.NAME)` for `Shift+U`;
the new handler returns `None` (`unicorn_tears.py:464`) with a comment assuming
the caller flashes the name, but the dispatch loop only flashes on a returned
string.
**Recommended solution:** return the effect display name string from
`handle_key` (`return cls.NAME`) so the dispatch loop flashes it, or call
`vj_api.flash_message(cls.NAME)` before returning `None`.

---

## Cross-cutting strengths (no action needed)

- Drop-in independence pattern (`_Null*` fallbacks + `try/except` around every
  `load_dropin_symbol`) is consistently applied across all load sites in
  `app.py`; a missing submodule degrades cleanly (the A-03 gap is only on the
  *key-dispatch* path, not load).
- `paths.py` `APP_ROOT`/`resolve_path` cleanly fixes the F44-01 CWD-relative
  path class of bugs.
- `VJApi` is now a broad, well-documented surface; the new shims (A-02 aside)
  correctly centralize drop-in → app access.

---

## Recommended execution order

1. **A-01** (Auto VJ team) and **A-02** (Effects + Core) — unblock the two
   shipping subsystems. See the companion hotfix brief.
2. **A-03** (Core) — make the dispatch loop crash-proof so future drop-in bugs
   degrade instead of crashing.
3. **A-05**, **A-04**, **A-10** (Core) — tighten the boundary and startup cost.
4. **A-06**, **A-07**, **A-11** (Engineering/Effects) — hygiene + help accuracy.
5. **A-08**, **A-09** (Engineering/Core) — process and structural debt; schedule
   before the v1.0 tag.
