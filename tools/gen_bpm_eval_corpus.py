"""Generate synthetic click-track WAV files for the BPM evaluation seed corpus.

Each file is a 30-second mono WAV at 48000 Hz containing:
- A band-limited kick transient (short sine burst in the bass band) on every beat.
- A lighter snare transient (mid-band sine burst) on beats 2 and 4.
- Low-level white noise floor to prevent silence-detection corner cases.

Ground truth is written as a companion <name>.bpm.json sidecar.

Usage::

    python tools/gen_bpm_eval_corpus.py [output_dir]

Default output: assets/audio/bpm_eval/seed/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import scipy.io.wavfile as wav

SR = 48000         # sample rate
DURATION_S = 30    # clip length
NOISE_FLOOR = 0.005


def _kick(sr: int, freq: float = 60.0, dur_s: float = 0.04) -> np.ndarray:
    """Short bass-band sine burst with fast exponential decay (kick-like)."""
    n = int(sr * dur_s)
    t = np.linspace(0, dur_s, n, endpoint=False)
    env = np.exp(-t * 80.0)
    return (np.sin(2 * np.pi * freq * t) * env * 0.9).astype(np.float32)


def _snare(sr: int, freq: float = 900.0, dur_s: float = 0.025) -> np.ndarray:
    """Short mid-band burst with noise blend (snare-like)."""
    n = int(sr * dur_s)
    t = np.linspace(0, dur_s, n, endpoint=False)
    env = np.exp(-t * 120.0)
    tone = np.sin(2 * np.pi * freq * t)
    noise = np.random.default_rng(42).standard_normal(n).astype(np.float32) * 0.3
    return ((tone + noise) * env * 0.5).astype(np.float32)


def generate_clip(
    bpm: float,
    sr: int = SR,
    duration_s: float = DURATION_S,
    seed: int = 0,
    downbeat_offset_s: float = 0.0,
) -> tuple[np.ndarray, dict]:
    """Return (pcm_float32, truth_dict) for a click track at the given BPM."""
    n_samples = int(sr * duration_s)
    pcm = np.zeros(n_samples, dtype=np.float32)

    # Noise floor
    rng = np.random.default_rng(seed)
    pcm += (rng.standard_normal(n_samples) * NOISE_FLOOR).astype(np.float32)

    kick = _kick(sr)
    snare = _snare(sr)
    beat_period_s = 60.0 / bpm
    beat_num = 0
    t = downbeat_offset_s
    while t < duration_s:
        start = int(t * sr)
        # Downbeats and odd beats: kick
        transient = kick if (beat_num % 2 == 0) else snare
        end = min(start + len(transient), n_samples)
        if end > start:
            pcm[start:end] += transient[: end - start]
        beat_num += 1
        t += beat_period_s

    pcm = np.clip(pcm, -1.0, 1.0)
    truth = {
        'bpm': float(bpm),
        'downbeat_offset_s': float(downbeat_offset_s),
    }
    return pcm, truth


# Seed corpus: (bpm, filename_stem, downbeat_offset_s)
CORPUS: list[tuple[float, str, float]] = [
    (90.0,  '090bpm_click', 0.0),
    (96.0,  '096bpm_click', 0.0),   # specific failing case from live sessions
    (120.0, '120bpm_click', 0.0),
    (140.0, '140bpm_click', 0.0),
    (155.0, '155bpm_click', 0.0),   # genuinely fast — must not regress
]


def main(output_dir: Path) -> None:
    """Write all seed corpus files to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f'Writing seed corpus to {output_dir}/')
    for bpm, stem, offset in CORPUS:
        pcm, truth = generate_clip(bpm, downbeat_offset_s=offset)
        wav_path = output_dir / f'{stem}.wav'
        json_path = output_dir / f'{stem}.bpm.json'
        # Write as int16 WAV for compatibility
        pcm_int16 = (pcm * 32767).astype(np.int16)
        wav.write(str(wav_path), SR, pcm_int16)
        json_path.write_text(json.dumps(truth, indent=2) + '\n', encoding='utf-8')
        print(f'  {stem}.wav  ({bpm} BPM, {len(pcm)/SR:.1f}s)')
    print('Done.')


if __name__ == '__main__':
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('assets/audio/bpm_eval/seed')
    main(out)
