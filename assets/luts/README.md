# Color-Grade LUTs

Drop Adobe `.cube` 3D LUT files in this directory and the **color-grade-01**
drop-in will discover them automatically at startup, appending each as a
selectable look after the built-in procedural grades.

- Only `LUT_3D_SIZE` cubes are supported (1D `.cube` LUTs are rejected).
- The file stem becomes the look's display name (e.g. `Kodak2383.cube` →
  "Kodak2383").
- Cycle through looks (built-ins + LUTs) with `Ctrl+Shift+Alt+.` / `,`.

Override this location with `lut_dir` under `[color_grade]` in `config.toml`.

This folder is intentionally tracked (via this README) so the default
`lut_dir` always resolves cleanly even before any LUTs are added.
