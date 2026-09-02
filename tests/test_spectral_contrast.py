"""Functional test for the analyzer's spectral contrast (2026-09-01).

Known physics: a harmonic tone stack has tall spectral peaks over quiet
valleys (high contrast); broadband noise fills the valleys (low).
The recommender term ships dormant (weight 0.0, all profile mus unset)
— source-pinned here so activation is a deliberate act.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from unicornviz.audio.analyzer import Analyzer
from unicornviz.effects.base import AudioData

SR = 48000
BLOCK = 512


def _run(pcm: np.ndarray) -> float:
    an = Analyzer()
    an.set_sample_rate(SR)
    data = AudioData()
    for i in range(len(pcm) // BLOCK):
        an.process(pcm[i * BLOCK:(i + 1) * BLOCK], t=i * BLOCK / SR, out=data)
    return data.spectral_contrast


def test_harmonic_material_reads_higher_contrast_than_noise() -> None:
    t = np.arange(SR * 6) / SR
    tone = sum(0.2 * np.sin(2 * np.pi * f * t) for f in (440.0, 880.0, 1320.0, 2200.0))
    tone = tone.astype(np.float32)
    noise = np.random.default_rng(7).normal(0, 0.2, SR * 6).astype(np.float32)
    c_tone, c_noise = _run(tone), _run(noise)
    assert c_tone > c_noise + 0.3, (c_tone, c_noise)


def test_term_ships_dormant() -> None:
    src = (Path(__file__).resolve().parents[1] / 'drop-ins' / 'auto-vj-01'
           / 'auto_vj.py').read_text(encoding='utf-8')
    assert re.search(r"'spectral_contrast_fit': 0\.0,", src), \
        'weight must stay 0.0 until the bake-off earns it a value'
    prof = (Path(__file__).resolve().parents[1] / 'unicornviz' / 'audio'
            / 'profiles.py').read_text(encoding='utf-8')
    assert 'spectral_contrast_mu: float | None = None' in prof
    assert not re.search(r'spectral_contrast_mu\s*=\s*[0-9]', prof), \
        'no profile may carry a hand-authored contrast mu'
