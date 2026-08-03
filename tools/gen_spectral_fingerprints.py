"""Generate spectral fingerprints for AudioProfiles using OpenAI.

One-time synthesis script.  Calls gpt-4o with a detailed prompt grounded in
MIR literature (AcousticBrainz, GTZAN, FMA, EDM classification papers) to
produce 64-element normalized spectral magnitude vectors per genre profile.

The 64 log-spaced bands (30 Hz – 16 kHz) exactly match the band structure used
in unicornviz/effects/audio_spectrum.py (_N_BARS=64, _F_MIN=30, _F_MAX=16000).

Output: a Python file ``tools/spectral_fingerprints_out.py`` containing a
dict of profile_key → list[float] (64 elements, normalized 0.0–1.0) ready to
review and paste into unicornviz/audio/profiles.py as ``expected_bands`` fields.

Usage::

    OPENAI_API_KEY=sk-... python tools/gen_spectral_fingerprints.py

Requires: openai >= 1.0.0
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Band structure — must match unicornviz/effects/audio_spectrum.py exactly
# ---------------------------------------------------------------------------

_N_BARS: int = 64
_F_MIN: float = 30.0
_F_MAX: float = 16_000.0

_edges = np.logspace(np.log10(_F_MIN), np.log10(_F_MAX), _N_BARS + 1)
_centers = np.sqrt(_edges[:-1] * _edges[1:])  # geometric center of each band

# ---------------------------------------------------------------------------
# Profile catalogue — parallel to unicornviz/audio/profiles.py PROFILES dict.
# Includes MIR-relevant acoustic notes per genre to steer LLM synthesis.
# ---------------------------------------------------------------------------

_PROFILE_META: dict[str, dict] = {
    "house": {
        "name": "House",
        "bpm": "120–128",
        "acoustic_notes": (
            "Strong sub-bass kick at 50–80 Hz; punchy kick body at 80–150 Hz; "
            "snare/clap at 150–300 Hz; open hi-hats and percussion at 5–14 kHz; "
            "modest low-mid energy; moderate presence 1–3 kHz from percussion tail."
        ),
    },
    "tech_house": {
        "name": "Tech House",
        "bpm": "122–130",
        "acoustic_notes": (
            "Similar kick profile to house but tighter transients; more mid content "
            "from minimal synth stabs 200–800 Hz; pronounced hi-hat energy 8–16 kHz; "
            "occasional clipped clap burst 2–4 kHz; sustained sub-bass rumble 30–60 Hz."
        ),
    },
    "peak_time": {
        "name": "Peak-Time Techno",
        "bpm": "126–136",
        "acoustic_notes": (
            "Festival techno: wide-frequency energy; powerful kick 40–120 Hz with "
            "prominent attack click 800–1200 Hz; bright reverb tails 3–8 kHz; "
            "synth pads add constant energy 200–1000 Hz; hi-hats and crashes 6–16 kHz."
        ),
    },
    "trance": {
        "name": "Trance",
        "bpm": "134–142",
        "acoustic_notes": (
            "Sub kick 50–100 Hz; strong melodic synth leads 400–2000 Hz and 2–6 kHz; "
            "offbeat bass line 80–200 Hz; heavily used pad layers 200–800 Hz; "
            "arpeggios and supersaws 1–8 kHz; snappy hi-hats 10–16 kHz."
        ),
    },
    "psytrance": {
        "name": "Psytrance",
        "bpm": "140–148",
        "acoustic_notes": (
            "Rolling 16th-note bassline at 60–160 Hz; psychedelic mid textures and "
            "FM synths 300–3000 Hz; busy hi-hats 8–16 kHz; nearly constant spectral "
            "energy from bass to treble; high spectral centroid from complex textures."
        ),
    },
    "electronic": {
        "name": "Electronic (broad)",
        "bpm": "118–132",
        "acoustic_notes": (
            "Broad genre catch-all; balanced spectrum; moderate sub-bass; synth textures "
            "across 100–4000 Hz; electronic percussion contributes across 200–10 kHz; "
            "relatively flat mid/treble distribution with moderate bass emphasis."
        ),
    },
    "hardgroove": {
        "name": "Hardgroove Techno",
        "bpm": "132–140",
        "acoustic_notes": (
            "Tribal, relentless percussion: prominent conga/bongo tones 150–600 Hz; "
            "dry tight kick 50–120 Hz; busy mid percussion 500–2000 Hz; "
            "fast hat patterns 8–16 kHz; low-mid groove emphasis 200–800 Hz."
        ),
    },
    "uk_garage": {
        "name": "UK Garage",
        "bpm": "128–136",
        "acoustic_notes": (
            "Swinging kick-snare; vocal chop energy 200–3000 Hz; crisp hi-hats 8–14 kHz; "
            "sub-bass wobble 40–100 Hz; 2-step rhythmic pattern spreads transients "
            "across bass and mid; vocal presence lifts 1–5 kHz above house baseline."
        ),
    },
    "breaks": {
        "name": "Breakbeat / Breaks",
        "bpm": "132–145",
        "acoustic_notes": (
            "Amen/Breakbeat drum loops: complex snare tone 150–400 Hz; syncopated kick "
            "less dominant than techno; busy 2–8 kHz from hi-hat and cymbal runs; "
            "mid energy from samples 300–2000 Hz; wide spectral spread typical."
        ),
    },
    "hard_techno": {
        "name": "Hard Techno",
        "bpm": "142–154",
        "acoustic_notes": (
            "Punishing kick with distorted body 50–200 Hz; industrial mid textures "
            "200–2000 Hz from clipped/distorted elements; screech/acid elements "
            "1–5 kHz; consistent hi-hat noise 8–16 kHz; high spectral density overall."
        ),
    },
    "hardstyle": {
        "name": "Hardstyle",
        "bpm": "145–165",
        "acoustic_notes": (
            "Heavily distorted, often pitch-bent kick with wide harmonic spread "
            "50–300 Hz (not clean sub-bass like house/techno — distortion pushes "
            "energy well into the low-mids); 'reverse bass' sweep leading into each "
            "kick adds continuous low-mid energy 150–600 Hz; aggressive 'screech' "
            "synth leads and euphoric melodic leads dominate 1.5–4 kHz; wall-of-sound "
            "compression keeps energy elevated across nearly the whole spectrum, "
            "similar in continuity to metal but from synthesized/distorted electronic "
            "sources; hi-hats and crash cymbals in builds add 6–12 kHz presence; "
            "high spectral centroid and high ZCR from pervasive distortion, comparable "
            "to hard techno but pushed further by the screech-lead register."
        ),
    },
    "dubstep": {
        "name": "Dubstep",
        "bpm": "138–142 (produced/tagged tempo; perceived half-time feel)",
        "acoustic_notes": (
            "Defined by sparse, syncopated rhythm rather than continuous 4/4 — "
            "produced/tagged at ~140 BPM but the audible pulse (snare on the "
            "half-time backbeat, huge bass hits) feels like ~70 BPM. Deep sub-bass "
            "'wobble' (LFO-modulated bass) dominates 30–100 Hz; aggressive mid-range "
            "'growl'/'screech' bass texture spans a wide low-mid band 100–600 Hz with "
            "complex distorted harmonic content; scooped upper-mids (1.5–4 kHz) is a "
            "genre hallmark — noticeably less presence here than trance/psytrance; "
            "snare snap sits around 200–400 Hz; sparse hi-hats/cymbal shimmer in verses "
            "add modest high-treble energy; low onset density relative to 4/4 club "
            "genres given the sparse/syncopated hit pattern; moderate-high ZCR from "
            "the distorted growl-bass texture."
        ),
    },
    "fire_dj": {
        "name": "Fire DJ (wide-tempo electronic)",
        "bpm": "132–170",
        "acoustic_notes": (
            "High-energy wide-tempo electronic: strong kick 40–120 Hz; active hats "
            "8–16 kHz; synth mid drive 200–3000 Hz; fills across full spectrum; "
            "similar to peak_time but with wider tempo and more synth mid content."
        ),
    },
    "drum_and_bass": {
        "name": "Drum & Bass",
        "bpm": "168–178",
        "acoustic_notes": (
            "Reese bass sub rumble 30–80 Hz; snappy Amen-style break with bright snare "
            "150–500 Hz and busy hi-hats 6–16 kHz; DnB bass line 60–200 Hz; "
            "very fast transients; high treble energy from live-sounding break drums."
        ),
    },
    "rap": {
        "name": "Rap / Hip-Hop",
        "bpm": "70–100",
        "acoustic_notes": (
            "Heavy 808/sub kick 30–80 Hz; mid kick punch 80–150 Hz; rap vocals are "
            "a SUSTAINED (not transient) signal emphasising 200–3000 Hz — the "
            "fingerprint should show a broad, continuous plateau across that range "
            "rather than a choppy percussion-style peak; hi-hats relatively subdued "
            "6–12 kHz; low spectral centroid; strong sub dominance; AcousticBrainz "
            "shows hip-hop centroids typically 800–1200 Hz."
        ),
    },
    "hyphy": {
        "name": "Hyphy",
        "bpm": "90–110",
        "acoustic_notes": (
            "Aggressive Oakland hip-hop: heavier bass than rap 30–100 Hz; "
            "punchy mid synth hits 200–1500 Hz; hype vocal chops are a SUSTAINED "
            "signal spanning 500–3000 Hz — broader and brighter than rap's vocal "
            "plateau but still continuous, not choppy; bright hats and snare "
            "4–12 kHz; more treble presence than classic rap."
        ),
    },
    "r&b": {
        "name": "R&B / Soul",
        "bpm": "75–100",
        "acoustic_notes": (
            "Warm: smooth bass 40–150 Hz; vocal-forward 200–3000 Hz is the most "
            "SUSTAINED vocal presence of the three vocal-forward genres — the "
            "fingerprint should show the broadest, steadiest mid-band plateau of "
            "the set (150 Hz–3.2 kHz), reflecting continuous, not choppy, vocal "
            "and harmonic content; piano/keys add harmonic content 100–2000 Hz; "
            "soft hi-hats 6–10 kHz; very low ZCR (smooth not noisy) — the lowest "
            "of the three vocal genres; low spectral centroid ~1400 Hz; "
            "low onset density — laid-back grooves."
        ),
    },
    "generic": {
        "name": "Generic (balanced)",
        "bpm": "80–160",
        "acoustic_notes": (
            "Flat catch-all: approximately equal energy distribution across all bands "
            "with slight bass emphasis; represents a balanced neutral starting point "
            "without strong genre bias in any frequency region."
        ),
    },
    "ambient": {
        "name": "Ambient / Chillout",
        "bpm": "60–120 (or beatless)",
        "acoustic_notes": (
            "Very low spectral energy overall; pad/drone emphasis 60–800 Hz; "
            "almost no content above 8 kHz; very soft treble from distant textures; "
            "sub-bass may be present as drone 30–60 Hz; "
            "AcousticBrainz ambient centroid typically 600–1000 Hz; lowest ZCR of all genres."
        ),
    },
    "chillstep": {
        "name": "Chillstep / Downtempo",
        "bpm": "78–112",
        "acoustic_notes": (
            "Slow electronic: sub-bass kick 40–80 Hz; atmospheric pads 100–1200 Hz; "
            "soft female vocal or vocal chops 200–2500 Hz; soft hi-hats 6–10 kHz; "
            "higher treble than pure ambient but lower than club genres; "
            "centroid ~900 Hz reflecting atmospheric and bass-dominant balance."
        ),
    },
    # 2026-08-03: added to the catalogue for provenance consistency when this
    # batch tool is next re-run; the live expected_bands currently in
    # profiles.py for this key were hand-authored (not generated via this
    # script's LLM call) -- see the "synthwave" entry's own comment in
    # unicornviz/audio/profiles.py for the full first-pass rationale.
    "synthwave": {
        "name": "Synthwave / Retrowave",
        "bpm": "85–118 (classic/melodic; Kavinsky-style)",
        "acoustic_notes": (
            "Retro 80s electronic: warm analog bassline 40–100 Hz, not a "
            "modern sub-bass floor; gated-reverb drum kit with snare body "
            "150–400 Hz and a bright noise 'snap' 2–6 kHz; lush pad/string "
            "synths 200–1500 Hz; bright melodic lead synth is the genre's "
            "defining register, 1.4–2.4 kHz, often the strongest peak in "
            "the spectrum; analog/vintage character rolls off well before "
            "psytrance/trance's harsh digital extreme-treble extension; "
            "moderate onset density from arpeggios/hooks, clearly above "
            "ambient/chillstep but below house/trance's percussion density."
        ),
    },
}


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_band_table() -> str:
    lines = ['Band index | Center freq (Hz) | Approximate musical region']
    lines.append('---------- | ---------------- | --------------------------')
    for i, f in enumerate(_centers):
        if f < 60:
            region = 'Deep sub-bass'
        elif f < 100:
            region = 'Sub-bass / kick fundamental'
        elif f < 200:
            region = 'Bass body / kick attack'
        elif f < 400:
            region = 'Low-mid / bass guitar / snare'
        elif f < 800:
            region = 'Mid / lower vocal formants'
        elif f < 1600:
            region = 'Mid / vocal presence'
        elif f < 3200:
            region = 'Upper mid / presence / guitar harmonic'
        elif f < 6400:
            region = 'Low treble / breath / hi-hat body'
        elif f < 10000:
            region = 'Treble / hi-hat shimmer / cymbal'
        else:
            region = 'Air / cymbal overtone / extremes'
        lines.append(f'{i:10d} | {f:16.1f} | {region}')
    return '\n'.join(lines)


def _build_profile_section() -> str:
    sections = []
    for key, meta in _PROFILE_META.items():
        sections.append(
            f'### {key}\n'
            f'Name: {meta["name"]}\n'
            f'Typical BPM: {meta["bpm"]}\n'
            f'Acoustic notes: {meta["acoustic_notes"]}'
        )
    return '\n\n'.join(sections)


def _build_prompt() -> str:
    band_table = _build_band_table()
    profile_section = _build_profile_section()
    return f"""\
You are a music information retrieval (MIR) expert synthesizing spectral
fingerprints for a real-time audio visualization system.

## Task

For each of the {len(_PROFILE_META)} music genre profiles listed below, produce a 64-element
vector of normalized spectral magnitudes (values 0.0–1.0).  Each element
corresponds to one log-spaced frequency band covering 30 Hz to 16 kHz.

These fingerprints will be used as genre reference spectra: a live fast Fourier
transform window average is compared by cosine similarity against each profile's
fingerprint to score how well the current audio matches the genre.

## Band structure

The 64 bands are log-spaced from 30 Hz to 16 kHz.  Band edges were computed as:
  numpy.logspace(log10(30), log10(16000), 65)
with band centres at the geometric mean of adjacent edges.

{band_table}

## Synthesis guidelines

Base your fingerprints on findings from established MIR datasets and papers:

- **AcousticBrainz** (archived 2022) — large-scale spectral descriptor dataset
  with per-genre distributions of spectral centroid, MFCC, and band energy.
- **GTZAN** (Tzanetakis & Cook, 2002) — 10-genre dataset; well-studied spectral
  characteristics for blues, classical, country, disco, hip-hop, jazz, metal,
  pop, reggae, rock.
- **FMA: A Dataset for Music Analysis** (Defferrard et al., 2017) — 106,574
  tracks across 161 unbalanced genres with full audio; spectral analysis papers
  cite energy distributions by frequency region.
- **EDM genre classification literature** — multiple papers (Sturm 2012,
  Bonnin & Jannach 2014, Schedl et al. 2018) characterise techno, trance,
  house, DnB by sub-bass to treble ratios and mid-energy content.

Rules for fingerprint values:
- Values are RELATIVE magnitudes within the profile, not absolute levels.
- The most prominent frequency region(s) for the genre should be near 1.0.
- Relatively inactive regions should still have non-zero values (0.05–0.20)
  to avoid cosine similarity collapse.
- Smooth transitions between adjacent bands unless the genre has sharp spectral
  peaks (e.g., pure-tone synth leads).
- Sub-bass (30–60 Hz) is typically very high for electronic kick-driven genres
  and very low for classical/acoustic.
- Distorted guitar genres (rock, metal) have elevated mid energy 80–5000 Hz.
- Ambient genres have very low overall energy, highest in 60–800 Hz range.

## Profiles to fingerprint

{profile_section}

## Output format

Respond with ONLY a JSON object.  Keys are the profile key strings exactly as
shown (e.g. "house", "tech_house", "r&b").  Values are arrays of exactly 64
floats, each in [0.0, 1.0].  No prose before or after the JSON block.

Example structure (values not real):
{{
  "house": [0.92, 0.88, 0.75, ...],
  "tech_house": [0.90, 0.85, 0.72, ...],
  ...
}}
"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

_MODEL = 'gpt-4o'


def _call_openai(prompt: str) -> str:
    """Call gpt-4o with streaming; return full response text."""
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit('ERROR: openai package not installed.  Run: pip install openai')

    client = OpenAI()
    full_text = ''

    print(f'Calling {_MODEL} (streaming)…', flush=True)
    stream = client.chat.completions.create(
        model=_MODEL,
        max_tokens=16384,
        messages=[{'role': 'user', 'content': prompt}],
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            full_text += delta
            sys.stdout.write('.')
            sys.stdout.flush()

    print('\nDone.', flush=True)
    return full_text


# ---------------------------------------------------------------------------
# Parse + validate
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> dict[str, list[float]]:
    """Extract and validate the JSON fingerprint dict from LLM output."""
    # Strip markdown code fences if the model added them.
    text = raw.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        text = '\n'.join(
            line for line in lines
            if not line.startswith('```')
        ).strip()

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f'Expected a JSON object, got {type(data).__name__}')

    result: dict[str, list[float]] = {}
    for key, vec in data.items():
        if not isinstance(vec, list):
            raise ValueError(f'Profile {key!r}: expected list, got {type(vec).__name__}')
        floats = [float(v) for v in vec]
        n = len(floats)
        if n < _N_BARS:
            print(f'  WARNING: {key!r} has {n} bands (expected {_N_BARS}); padding with last value')
            floats += [floats[-1]] * (_N_BARS - n)
        elif n > _N_BARS:
            print(f'  WARNING: {key!r} has {n} bands (expected {_N_BARS}); truncating')
            floats = floats[:_N_BARS]
        lo, hi = min(floats), max(floats)
        if lo < -0.01 or hi > 1.01:
            raise ValueError(
                f'Profile {key!r}: values out of [0,1] range (min={lo:.3f}, max={hi:.3f})'
            )
        result[key] = floats

    missing = set(_PROFILE_META) - set(result)
    if missing:
        raise ValueError(f'Missing profiles in LLM response: {sorted(missing)}')

    return result


# ---------------------------------------------------------------------------
# Output writer
# ---------------------------------------------------------------------------

_OUT_PATH = Path(__file__).resolve().parent / 'spectral_fingerprints_out.py'


def _write_output(fingerprints: dict[str, list[float]]) -> None:
    """Write a ready-to-review Python file with expected_bands data."""
    lines = [
        '"""Synthesized spectral fingerprints for unicornviz/audio/profiles.py.',
        '',
        'Generated by tools/gen_spectral_fingerprints.py using claude-opus-4-8.',
        'Grounded in AcousticBrainz, GTZAN, FMA, and EDM classification literature.',
        '',
        'HOW TO APPLY',
        '============',
        '1. Review each 64-element list below for plausibility.',
        '2. Add ``expected_bands: list[float] | None = None`` to the AudioProfile',
        '   dataclass in unicornviz/audio/profiles.py (after ``onset_density_mu``).',
        '3. Paste the ``expected_bands=[...]`` keyword argument into each profile',
        '   constructor in the PROFILES dict.',
        '4. Integrate cosine-similarity scoring in the auto-vj recommender.',
        '"""',
        '',
        'from __future__ import annotations',
        '',
        '# Band centres (Hz) for reference — 64 log-spaced bands 30 Hz – 16 kHz.',
        '# numpy.logspace(log10(30), log10(16000), 65) → geometric means.',
        f'BAND_CENTERS_HZ: list[float] = {[round(float(f), 2) for f in _centers]!r}',
        '',
        'EXPECTED_BANDS: dict[str, list[float]] = {',
    ]

    for key in _PROFILE_META:
        vec = fingerprints[key]
        # Format as 8 values per line for readability.
        rows = []
        for i in range(0, _N_BARS, 8):
            chunk = vec[i:i + 8]
            rows.append('        ' + ', '.join(f'{v:.3f}' for v in chunk) + ',')
        lines.append(f'    {key!r}: [')
        lines.extend(rows)
        lines.append('    ],')

    lines += [
        '}',
        '',
        '',
        '# -----------------------------------------------------------------------',
        '# Paste snippet — copy the block below for each profile in profiles.py',
        '# and replace the placeholder list with the matching entry from',
        '# EXPECTED_BANDS above.',
        '# -----------------------------------------------------------------------',
        '#',
        '# expected_bands=EXPECTED_BANDS["<key>"],',
        '#',
        '# After pasting, remove the EXPECTED_BANDS import and inline the lists.',
        '',
    ]

    _OUT_PATH.write_text('\n'.join(lines), encoding='utf-8')
    print(f'\nWrote {_OUT_PATH}')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    raw_cache = _OUT_PATH.with_suffix('.raw.txt')

    if raw_cache.exists():
        print(f'Re-using cached raw response from {raw_cache}')
        raw = raw_cache.read_text(encoding='utf-8')
    else:
        prompt = _build_prompt()
        print(f'Prompt length: {len(prompt):,} chars')
        print(f'Generating fingerprints for {len(_PROFILE_META)} profiles × {_N_BARS} bands …\n')
        raw = _call_openai(prompt)

    print('\nParsing response…')
    try:
        fingerprints = _extract_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f'ERROR parsing LLM response: {exc}', file=sys.stderr)
        raw_path = _OUT_PATH.with_suffix('.raw.txt')
        raw_path.write_text(raw, encoding='utf-8')
        print(f'Raw response saved to {raw_path}', file=sys.stderr)
        return 1

    print(f'Parsed {len(fingerprints)} profiles successfully.')

    # Sanity-check: report per-profile peak band and centroid estimate.
    print('\nProfile summary (peak band Hz | cosine-diagonal check):')
    for key, vec in fingerprints.items():
        peak_idx = int(np.argmax(vec))
        peak_hz = float(_centers[peak_idx])
        # Rough spectral centroid from fingerprint.
        centroid = float(np.dot(_centers, vec) / max(sum(vec), 1e-9))
        print(f'  {key:<20s} peak={peak_hz:6.0f} Hz  centroid≈{centroid:6.0f} Hz')

    _write_output(fingerprints)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
