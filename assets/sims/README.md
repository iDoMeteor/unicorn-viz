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

## Open-source robots (MuJoCo Menagerie)

`drop-ins/sims-01/tools/fetch_robots.py` downloads robots from the **Apache-2.0**
[MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie),
converts their MJCF + OBJ meshes to USD with gently-sweeping joints, and writes
them to `assets/sims/robots-menagerie/` (git-ignored) plus a `CREDITS.txt`:

```bash
python drop-ins/sims-01/tools/fetch_robots.py   # needs network + OpenUSD
```

Ships two by default — `universal_robots_ur5e` (arm) and `unitree_go2`
(quadruped). They're real, higher-res meshes (~360-420k verts), so at the
default 48-frame bake each uses a few hundred MB of RAM; lower
`[effects.SimShowcase] skel_frames` (e.g. 24) if memory is tight. Add more by
editing the `_MODELS` list (Franka, Spot, ANYmal, Unitree G1/H1, Shadow Hand, …).

## Loader support

Skinned/animated character rigs are handled by the reusable USD loader in
`drop-ins/sims-01/usd_scene.py` (prim filtering, UsdSkel skinning, animation
baking, audio-reactive blendshapes). See
`drop-ins/sims-01/docs/planning-usd-characters.md` for the design and
`drop-ins/sims-01/docs/configuration.md` for the config keys.

Requires OpenUSD: `pip install -r drop-ins/sims-01/requirements.txt`.
