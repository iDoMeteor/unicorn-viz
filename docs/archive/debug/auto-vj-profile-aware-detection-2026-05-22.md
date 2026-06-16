# Auto VJ — Profile-Aware Beat Detection (2026-05-22)

## Context

Picks up directly from
[auto-vj-handoff-2026-05-21.md](./auto-vj-handoff-2026-05-21.md).  Owner
insight: the audio profiles (house / techno / trance / rap / etc.) were only
shaping effect weighting; the onset detector and BPM tracker were running on
fixed, genre-agnostic defaults.  This pass wires the profile into both
stages so beat detection has realistic expectations for the set's genre.

## Changes

### `unicornviz/audio/profiles.py`
Added five beat-detection-shaping fields to `AudioProfile`, with per-genre
tuning across the full preset table:

| Field                  | Purpose                                          |
|------------------------|--------------------------------------------------|
| `onset_bass_emphasis`  | Multiplier for bass-band flux weights            |
| `onset_mid_emphasis`   | Multiplier for mid-band flux weights             |
| `onset_treble_emphasis`| Multiplier for treble-band flux weights          |
| `bpm_prior_mu`         | Centre of the tracker's log2 BPM prior (BPM)     |
| `bpm_prior_sigma`      | Width of the prior in log2(BPM) units            |

Per-genre values chosen to reflect canonical tempo + spectral character:

| Profile     | bass | mid | treble | μ  | σ    |
|-------------|------|-----|--------|----|------|
| house       | 2.2  | 1.0 | 0.6    | 124| 0.20 |
| techno→elec | 1.9  | 1.2 | 0.9    | 125| 0.35 |
| trance      | 1.8  | 1.3 | 0.9    | 138| 0.20 |
| rap         | 2.5  | 1.0 | 0.5    | 88 | 0.30 |
| hyphy       | 2.6  | 1.2 | 0.6    | 95 | 0.25 |
| r&b         | 1.8  | 1.2 | 0.7    | 85 | 0.30 |
| pop         | 1.7  | 1.3 | 0.8    | 110| 0.30 |
| rock        | 1.6  | 1.4 | 1.0    | 120| 0.40 |
| metal       | 1.5  | 1.4 | 1.1    | 140| 0.40 |
| classical   | 1.0  | 1.3 | 1.0    | 110| 0.50 |
| ambient     | 1.2  | 1.2 | 1.0    | 100| 0.60 |
| generic     | 1.8  | 1.2 | 1.0    | 120| 0.55 |

### `unicornviz/audio/analyzer.py`
`_setup_frequency_bands` now multiplies the per-band flux weights by the
profile's emphasis fields, so kick-driven genres suppress hi-hat onsets and
broader genres keep snare/cymbal contributions.  Recomputed whenever
`Analyzer.set_profile` is called.

### `drop-ins/auto-vj-01/beat_grid.py`
Both trackers gained a `set_profile(profile)` method:

* `BeatGridTracker` (v1) — reads `bpm_prior_mu` / `bpm_prior_sigma` and
  updates the in-use prior used by candidate scoring at
  `beat_grid.py:295-299`.
* `BeatTracker` (v2) — same fields, plus recomputes the pre-allocated
  `_acf_prior` array so ACF candidate scoring is biased toward the
  profile's tempo lane immediately.

Both are null-safe; passing `None` is a no-op.

### `drop-ins/auto-vj-01/auto_vj.py`
Added `_sync_grid_audio_profile()` which:

1. Reads the current key from `audio_manager.get_profile_key()`.
2. Diff-checks against a cached `_last_audio_profile_key` (single-frame
   no-op when unchanged — safe to call every frame).
3. Calls `self._grid.set_profile(profile)` on change and logs the new μ/σ.

Hooked at two points so any path that changes the audio profile picks it up
within one frame:

* In `__init__` after the tracker is constructed.
* At the top of `update()` before onsets are drained.

### `tools/bpm_eval.py`
The offline harness now calls `tracker.set_profile(profile)` so eval runs
mirror runtime priors.  Without this, the harness was scoring trackers
against a fixed default prior regardless of `--profile`.

## Verification

```
$ python -c "from unicornviz.audio.profiles import list_profiles, get_profile; ..."
ambient    bass_emph=1.2 mid=1.2 treble=1.0 mu=100.0 sigma=0.6
...
trance     bass_emph=1.8 mid=1.3 treble=0.9 mu=138.0 sigma=0.2

$ python -c "from beat_grid import BeatGridTracker, BeatTracker; ..."
BeatGridTracker house mu 120.0 -> 124.0 sigma= 0.2
BeatGridTracker rap mu-> 88.0 sigma= 0.3
BeatTracker     house mu 120.0 -> 124.0 sigma= 0.2
BeatTracker     rap mu-> 88.0 sigma= 0.3
```

Harness sweep (v1 legacy engine on `assets/audio/bpm_eval/seed`, same
clicks across four profiles) — predictions clearly shift by profile,
confirming the prior is end-to-end wired:

| File           | house | generic | electronic | trance |
|----------------|-------|---------|------------|--------|
| 090bpm_click   | 132.5 | 137.2   | 129.9      | 154.2  |
| 096bpm_click   | 127.0 | 157.7   | 130.6      | 158.0  |
| 120bpm_click   | 132.7 | 133.8   | 147.2      | 150.8  |
| 140bpm_click   | 140.6 | 143.0   | 142.6      | 143.1  |
| 155bpm_click   | 136.8 | 146.3   | 143.6      | 144.6  |

Click-track accuracy on its own remains v1's known weak spot (documented
in the 2026-05-21 handoff).  The wiring change is structural: it gives v1
the profile context it never had before, which is most useful on real
material where the user already knows the genre.

## Operational notes

* No `config.toml` changes are required; profiles already exist there.
  The new fields are read directly off `AudioProfile` objects.
* The hook is null-safe at every layer: missing audio manager, missing
  `get_profile_key`, missing `set_profile` on the tracker, or `None`
  profile each degrade to "do nothing" without raising.
* Auto-VJ's `auto_profile` mode (chill / normie / raver) still drives the
  *director* presets independently — this change only affects the *audio*
  profile (genre).  They are intentionally orthogonal axes.

## Next steps

1. Run a live set with a known-genre profile selected and capture detector
   logs (`autovj-*.jsonl`) to confirm BPM lock stability vs. the
   2026-05-21 baseline on the recurring 96-vs-150 lane problem.
2. If lock is still hi-hat-dominated on dense electronic material, push
   `onset_bass_emphasis` for that profile higher (e.g. 2.6-2.8) and
   `onset_treble_emphasis` lower (e.g. 0.4) before reaching for the
   kick-biased onset detector from the prior handoff's "Next steps".
3. Once stable, consider exposing a runtime CC hotkey to nudge the active
   profile's μ ±4 BPM for live recalibration without restarting.
