# sims-01 external USD asset packs

This directory holds **locally-curated USD asset packs** for the Sim Showcase
effect (`drop-ins/sims-01`). The `sims` loader scans `assets/sims/` (resolved
via the app root) in addition to the drop-in's own `scenes/` folder.

## Licensing — why these are git-ignored

Subdirectories here are **git-ignored on purpose**. Packs such as the NVIDIA
Reallusion character set (`Characters_NVD`) are bound by the
[NVIDIA Omniverse License Agreement](https://docs.omniverse.nvidia.com/platform/latest/common/NVIDIA_Omniverse_License_Agreement.html),
which restricts redistribution. We therefore **do not commit** these assets to
any repository; each operator downloads and places them locally.

Only this `README.md` is tracked (see the `.gitignore` rule
`assets/sims/*/` + `!assets/sims/README.md`).

## Placement

Curate **geometry-only** copies (skip the texture image sets — Sim Showcase
renders with its own procedural palette shader and ignores materials, so the
`.usd` layers are all that is needed; this is ~35 MB vs ~600 MB for the full
character pack):

```bash
# Example: NVIDIA Reallusion characters → assets/sims/characters-nvidia/
SRC=~/Downloads/openusd/Characters_NVD@10012/Assets/Characters/Reallusion
for c in Orc Debra Worker; do
  rsync -am --include='*/' --include='*.usd' --include='*.usdc' \
        --include='*.usda' --exclude='*' "$SRC/$c/" \
        "assets/sims/characters-nvidia/$c/"
done
```

Resulting layout:

```
assets/sims/
  README.md                      (tracked)
  characters-nvidia/             (git-ignored)
    Orc/Orc.usd
    Debra/Debra.usd
    Worker/Worker.usd
```

## Loader support

Skinned/animated character rigs are handled by the reusable USD loader in
`drop-ins/sims-01/usd_scene.py` (prim filtering, UsdSkel skinning, animation
baking, audio-reactive blendshapes). See
`drop-ins/sims-01/docs/planning-usd-characters.md` for the design and
`drop-ins/sims-01/docs/configuration.md` for the config keys.

Requires OpenUSD: `pip install -r drop-ins/sims-01/requirements.txt`.
