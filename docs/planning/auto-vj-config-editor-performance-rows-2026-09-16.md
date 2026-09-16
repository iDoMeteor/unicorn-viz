# auto-vj-01 — Performance rows for the core config editor (handoff)

Owner: overlays / core manager seat (author) → VJ seat (implementer)
Status: Proposed; waiting for the VJ seat's word (owner-gated area)
Last updated: 2026-09-16

Written for the VJ seat. Everything else in the 2026-09-16 drop-in
performance audit (`docs/audits/2026-09-16-dropin-performance-options.md`)
is wired; auto-vj-01 was deliberately left alone because its knobs sit in
the detector / recommender / training area the owner gates. This doc says
exactly what a Performance-tab contribution would look like so it can be
landed in one short commit when you decide it should be.

## Why these rows exist

Outside rendering, auto-vj-01 is the biggest CPU consumer in the process:
a second full beat tracker (the v3 shadow engine), recommender scoring on
every evaluation, and per-beat / heartbeat JSONL logging for training.
None of that is reachable from the app today: the `[auto_vj]` keys are
read once at startup. A live switch matters most on the show machine
(training off, shadow engine off) and on a weak laptop.

## The rows (Tier A in the audit)

All live unless marked RESTART. Names are the existing `[auto_vj]` keys so
a remembered value and a hand-set config value mean the same thing.

| Row (label) | `name` | Kind | Cost it trades | Notes |
|---|---|---|---|---|
| Shadow engine | `shadow_engine` | toggle | a second full beat tracker per audio block | live if the shadow tracker can be created/dropped on toggle; RESTART otherwise. **Your call**: this is the v3 soak instrument (see `feedback-detector-soak-freeze`); a live toggle must not silently end a soak. |
| Genre matcher | `genre_matcher_enabled` | toggle | matcher pass per recommender eval | live |
| Candidate scoring | `genre_candidate_scoring_enabled` | toggle | per-candidate scoring per eval | live |
| Live training log | `live_training_enabled` | toggle | JSONL write per beat | live; the show-machine switch |
| Sequence training log | `sequence_training_enabled` | toggle | heartbeat JSONL | live |
| Recommender eval | `profile_auto_reco_eval_interval_s` | slider (s) | eval cadence | live; keep the current default as the row's initial value |
| Detector log | `detector_log_interval_s` | slider (s) | log cadence | live |
| Wide-BPM sample | `wide_bpm_sample_interval_s` | slider (s) | detector side-analysis cadence | live |

Not proposed: any weight, threshold or prior. Those follow the ADR /
weights-doc discipline in CLAUDE.md and are not performance knobs.

## How to wire it (contributor convention 2.0, core beta.146)

The controller is already registered as a subsystem, so core discovers it
with no core change. Add to `AutoVJController`:

```python
CONFIG_EDITOR_CATEGORY = 'Performance'
CONFIG_EDITOR_KEY = 'auto_vj'
CONFIG_EDITOR_TITLE = 'Auto VJ'

def config_editor_settings(self) -> list[dict[str, object]]:
    return [
        {'name': 'live_training_enabled', 'label': 'Live training log',
         'kind': 'toggle', 'value': 1.0 if self._live_training_enabled else 0.0,
         'hint': 'JSONL row per beat for the training kit; off for a show'},
        {'name': 'profile_auto_reco_eval_interval_s', 'label': 'Recommender eval',
         'value': float(self._reco_eval_interval_s), 'min': 1.0, 'max': 30.0,
         'display': f'{self._reco_eval_interval_s:.1f} s',
         'hint': 'Seconds between recommender evaluations'},
        # ... one dict per row above; a RESTART row adds 'restart': 'auto_vj'
        #     and its setter returns {'shadow_engine': bool}
    ]

def set_config_setting(self, name: str, value: float):
    ...  # apply live; return the {config_key: value} dict for restart rows
```

What core does for you (see the developer guide, "Contributing Settings to
the Config Editor"):

- Live Performance rows are remembered as `perf_dropin.auto_vj.<name>` in
  `runtime/global_state.json` and replayed through `set_config_setting`
  at the end of the next startup. Nothing to persist on your side.
- A `restart` row's return value is laid over `[auto_vj]` in memory now and
  at the next launch (`config_overrides.auto_vj.<key>`), before the
  controller is built, so the existing startup read just works.
- `kind`, `choices`, `label`, `display`, `hint`, `badge`, `section` are
  presentation only; `name` stays the setter key.

Row order and section header come from the list order and
`CONFIG_EDITOR_TITLE`; no core edit is needed for any of it.

## Tests to add (hermetic, same pattern as the other nine drop-ins)

One file, `tests/test_config_editor_rows.py`: build the controller with
`object.__new__`, set the handful of attributes the rows read, assert the
row shapes, then drive each setter and assert the attribute (and, for a
restart row, the returned dict). See `drop-ins/webcam-01/tests/test_selfie_seg.py`
for the row-shape projection helper and `drop-ins/spotify-01/tests/test_config_editor_rows.py`
for the smallest complete example.

## Decisions for the VJ seat

1. Whether the shadow engine is a live toggle or a RESTART row.
2. Whether toggling training logs mid-session is acceptable for the
   training-kit packaging (a session with a gap in its JSONL).
3. Whether the two log cadences belong on the tab at all, or only the
   recommender eval interval.

Everything else is mechanical. Bump the drop-in MINOR, add the changelog
line, and the pointer bump lands like any other.
