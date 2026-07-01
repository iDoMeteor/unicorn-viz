from __future__ import annotations

import builtins
import importlib.util
import math
import sys
import wave
from pathlib import Path

import numpy as np


_TRAINING_LIB_PATH = Path(__file__).resolve().parents[1] / 'drop-ins' / 'training-kit-01' / 'tools' / 'training' / 'training_lib.py'
_TRAINING_LIB_SPEC = importlib.util.spec_from_file_location('test_training_lib_module', _TRAINING_LIB_PATH)
assert _TRAINING_LIB_SPEC is not None and _TRAINING_LIB_SPEC.loader is not None
_TRAINING_LIB_MODULE = importlib.util.module_from_spec(_TRAINING_LIB_SPEC)
sys.modules[_TRAINING_LIB_SPEC.name] = _TRAINING_LIB_MODULE
_TRAINING_LIB_SPEC.loader.exec_module(_TRAINING_LIB_MODULE)

extract_audio_features = _TRAINING_LIB_MODULE.extract_audio_features


def _write_tone(path: Path, sample_rate: int = 44_100, duration_s: float = 1.0) -> None:
    t = np.arange(int(sample_rate * duration_s), dtype=np.float32) / sample_rate
    samples = (0.2 * np.sin(2.0 * math.pi * 440.0 * t)).astype(np.float32)
    pcm = (samples * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def test_extract_audio_features_falls_back_without_essentia(tmp_path: Path, monkeypatch) -> None:
    audio_path = tmp_path / 'tone.wav'
    _write_tone(audio_path)

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'essentia' or name.startswith('essentia.'):
            raise ModuleNotFoundError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, '__import__', fake_import)

    row = extract_audio_features(audio_path)

    assert row['analysis_status'] == 'ok'
    assert row['audio_path'] == str(audio_path.resolve())
    assert row['duration_s'] > 0.0
    assert row['rms'] > 0.0
    assert row['peak_amplitude'] > 0.0
    assert row['bpm'] == 0.0
    assert row['beat_count'] == 0
    assert row['key'] == 'unknown'
    assert row['scale'] == 'unknown'
