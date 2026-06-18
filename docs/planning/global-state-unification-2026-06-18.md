# Global Atomic State — Audit & Implementation Plan

Owner: owner + Copilot  
Status: Active — revised 2026-06-18  
Last updated: 2026-06-18

---

## 1) Executive Summary

Unicorn Viz currently has five separate persistence mechanisms. The goal is to
consolidate everything that belongs to the core runtime behind a single
`RuntimeStateStore` at `runtime/global_state.json` — one file, one write path,
one lock, one recovery story.

**Scope decisions (owner-confirmed 2026-06-18):**

- **ProjectM** owns its own state and keeps it. `dark_excluded.txt` and
  `preset_manager_state.json` remain inside the `projectm-01` drop-in's own
  files; they do **not** move to the global store.
- **Spotify** owns its own token file. `runtime/spotify-pro-token.json` stays
  as a standalone credential file.
- **No migration support needed.** Single dev/user; break cleanly, start fresh.
- All state files that are not source code must be gitignored appropriately.

What moves into the global store: **audio source selection**, and **banner
config** (dedup — currently written to both its own file and the global store).

---

## 2) Revised State File Map

### 2a) Global store — what lives in `runtime/global_state.json`

| Namespace | Owner | State items |
|-----------|-------|-------------|
| `audio.*` | core `AudioCapture` | `selected_source_key`, `viable_source_keys` |
| `banner.*` | drop-in `banner-01` | `text`, `scroll_speed`, `alpha`, `font_px`, `beat_color_enabled`, `enabled` |
| `webcam.*` | drop-in `webcam-01` (via core) | `layout`, `selected_camera`, `per_camera.*`, `pip_scale`, `treatment`, `auto_cycle`, `disabled_cameras` |
| `multihead.*` | drop-in `control-room-01` | `monitor_editor.exclude_display_indices` |

### 2b) Drop-in-owned files — untouched

| File | Owner | Why it stays |
|------|-------|-------------|
| `drop-ins/projectm-01/dark_excluded.txt` | `projectm-01` | Owner-decision: ProjectM manages all its own state |
| `runtime/projectm/preset_manager_state.json` | `projectm-01` | Same |
| `drop-ins/projectm-01/preset_manager_state.json` | `projectm-01` (legacy fallback path) | Same |
| `runtime/spotify-pro-token.json` | `spotify-01` | Credential; kept separate, config-driven path |

### 2c) Session/append-only logs — untouched

| File pattern | Owner | Notes |
|--------------|-------|-------|
| `logs/autovj-*.jsonl` | `auto-vj-01` | Append-only telemetry |
| `logs/` (crash, keystroke) | core | Append-only |

---

## 3) Files to Delete (no migration — clean break)

| File | Replaced by |
|------|------------|
| `.audio_source_state.json` | `runtime/global_state.json#audio.*` |
| `logs/banner-state.json` | `runtime/global_state.json#banner.*` (already mirrored there) |

Both files are already gitignored (`.audio_source_state.json` in root
`.gitignore`; `logs/` in root `.gitignore`). They will be deleted from disk
and their private write paths removed from code.

---

## 4) Gitignore Rules

### Root `.gitignore`

Add to the `runtime/` block (already present):
```
# runtime/ is already in root .gitignore — covers global_state.json
```
The root `.gitignore` already has `runtime/` and `.audio_source_state.json`.
After the audio migration, `.audio_source_state.json` becomes a dead path;
keep the entry as a safety net until the old file is gone from all machines.

### `drop-ins/projectm-01/.gitignore`

Already has:
```
dark_excluded.txt
runtime/
```
Add explicit coverage for the two `preset_manager_state.json` locations and
the `preset_manager_states/` undo snapshot directory:
```
preset_manager_state.json
preset_manager_states/
```

### `drop-ins/spotify-01/.gitignore` (need to create or update)

Add:
```
# Spotify PKCE tokens — local credential, never commit
runtime/
*.token.json
spotify-*.json
```
(The `runtime/` entry already present covers `runtime/spotify-pro-token.json`
via the `runtime/` rule that most drop-in gitignores already have.)

### `drop-ins/banner-01/.gitignore` (need to create)

The `banner-01` drop-in currently has no gitignore. Create one covering the
private state file that is being deleted, so if it somehow reappears it stays
out of git:
```
logs/
banner-state.json
runtime/
```

---

## 5) Implementation Plan (no migration, clean break)

### Phase 1 — Audio source state

**Scope:** move `AudioCapture` persistence from `.audio_source_state.json` to
`runtime/global_state.json#audio.*`.

Files: `unicornviz/audio/capture.py`, `unicornviz/audio/manager.py`,
`unicornviz/app.py`

Steps:
1. `AudioCapture.__init__` accepts an optional `state_store: RuntimeStateStore | None`
   parameter (default `None` for backward-compat with tests).
2. `_load_source_state()` reads from `store.get('audio', {})` when a store is
   provided; falls back to an empty dict (no old file read — clean break).
3. `_save_source_state()` calls `store.set('audio', payload)` when a store is
   provided; no-ops otherwise (test path).
4. Remove `_DEFAULT_SOURCE_STATE_PATH`, `_state_path` attribute, and the old
   `read_text`/`write_text` calls.
5. `AudioManager.__init__` passes `self._store` (a `RuntimeStateStore` it
   constructs from the config path, or receives from `App`) to `AudioCapture`.
6. `App.__init__` constructs `RuntimeStateStore` first, then passes it to
   `AudioManager`.
7. Delete `.audio_source_state.json` from disk.

### Phase 2 — Banner deduplication

**Scope:** remove banner's private `logs/banner-state.json` file; use only
`runtime/global_state.json#banner.*` via `VJApi`.

Files: `drop-ins/banner-01/banner_controller.py`

Steps:
1. Remove `_state_path`, `_resolve_state_path()`, `_load_state()` from
   `BannerController`.
2. Change startup state load to use only
   `self._vj_api.get_runtime_state('banner', default={})`.
3. `_persist_runtime_state()` already calls
   `self._vj_api.set_runtime_state('banner', payload)` — keep only that call.
4. Delete `logs/banner-state.json` from disk.
5. Create `drop-ins/banner-01/.gitignore` to cover `logs/` and `runtime/`.

### Phase 3 — Gitignore hygiene (independent of phases 1–2)

Add/update gitignore entries as described in §4 above.

---

## 6) What Does NOT Change

- `VJApi.get_runtime_state()` / `VJApi.set_runtime_state()` — API unchanged.
- `RuntimeStateStore` — no API changes, no schema version bump needed.
- ProjectM state files — completely untouched.
- Spotify token file — completely untouched.
- All append-only logs — completely untouched.
- `config.toml` — not state.

---

## 7) Risk

All changes are additive-then-delete. Phases 1 and 2 are independent and can
ship in separate commits. No test fixtures reference the old file paths (they
mock `AudioCapture` directly), so the test suite needs only the stub interface
