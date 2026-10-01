"""Smoke test for the free-threaded sphn wheel (and, optionally, demucs).

Run it with the interpreter the wheel was installed into (see
``build_ft_sphn_wheel.sh --verify-python``).  Checks that sphn imports, that a
short stereo WAV round-trips through ``write_wav`` / ``read`` with the right
shape, rate and content, that ``resample`` and ``durations`` work, and (with
``--with-demucs``) that demucs imports.  It also *reports* whether importing
sphn re-enables the GIL; the module does not declare ``gil_used = false``, so it
is expected to.  That is information, not a failure.

    python tools/packaging/ft_sphn_smoke.py [--with-demucs]
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

RATE = 24_000


def _gil_after_import() -> str:
    proc = subprocess.run([sys.executable, '-W', 'ignore', '-c',
                           'import sys, sphn; print(sys._is_gil_enabled())'],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return f'IMPORT FAILED: {proc.stderr.strip().splitlines()[-1] if proc.stderr else "?"}'
    return 'ON (module did not declare gil_used = false)' if proc.stdout.strip() == 'True' else 'off'


def main(argv: list[str]) -> int:
    import numpy as np
    import sphn

    problems: list[str] = []
    print(f'python {sys.version.split()[0]}  sphn {getattr(sphn, "__version__", "?")} ({sphn.__file__})')
    print(f'  GIL after a fresh `import sphn`: {_gil_after_import()}')

    t = np.arange(RATE) / RATE                      # one second
    tone = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 660 * t)]).astype(np.float32) * 0.5
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / 'tone.wav')
        sphn.write_wav(path, tone, RATE)
        data, rate = sphn.read(path)
        print(f'  wav round trip: shape {data.shape}, rate {rate}')
        if rate != RATE or data.shape != tone.shape:
            problems.append(f'wav round trip gave shape {data.shape} at {rate} Hz')
        elif float(np.abs(data - tone).max()) > 1e-3:
            problems.append('wav round trip changed the samples')
        part, _ = sphn.read(path, start_sec=0.25, duration_sec=0.5)
        if abs(part.shape[-1] - RATE // 2) > 2:
            problems.append(f'partial read returned {part.shape[-1]} samples')
        dur = sphn.durations([path])
        if abs(dur[0] - 1.0) > 0.01:
            problems.append(f'durations() said {dur}')
    res = sphn.resample(tone, RATE, 48_000)
    print(f'  resample 24k -> 48k: {tone.shape} -> {res.shape}')
    # sphn's resampler works in fixed-size chunks, so the output is padded up to a
    # chunk multiple (49152 for this input, identically in upstream's wheel): check
    # that nothing is missing and the signal is intact, not an exact length.
    if res.shape[0] != 2 or res.shape[-1] < 2 * RATE - 64 or not np.isfinite(res).all():
        problems.append(f'resample gave {res.shape} (expected 2 channels, >= {2 * RATE - 64} samples)')
    elif float(np.abs(res[:, 200:2 * RATE - 200]).max()) < 0.4:
        problems.append('resample lost the signal')

    if '--with-demucs' in argv:
        try:
            import demucs
            import demucs.apply
            import demucs.pretrained  # noqa: F401  (imports torch, torchaudio, julius, openunmix, einops)
            print(f'  demucs {getattr(demucs, "__version__", "?")} imports (torch is in this environment)')
        except Exception as exc:  # noqa: BLE001 - report whatever broke the import
            problems.append(f'demucs import failed: {type(exc).__name__}: {exc}')

    print('FAILED: ' + '; '.join(problems) if problems else 'OK')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
