"""The multi-head fallback must accept exactly what app.py calls it with.

Regression for a first-run crash on a Windows bundle without multi-head-01:
``_NullMultiHeadController.rebuild_multihead_outputs`` required ``title`` and
``fullscreen`` while ``App._rebuild_multihead_outputs`` passes only the size,
so the first SDL display-topology event raised TypeError and ended the app.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

from unicornviz._null_controllers import _NullMultiHeadController

_REAL = Path(__file__).resolve().parents[1] / 'drop-ins' / 'multi-head-01' / 'multihead.py'


def test_null_rebuild_accepts_the_app_call_shape() -> None:
    null = _NullMultiHeadController.__new__(_NullMultiHeadController)
    assert null.rebuild_multihead_outputs(1920, 1080) == 0
    assert null.rebuild_multihead_outputs(1920, 1080, 'Unicorn Viz', True) == 0


def test_null_matches_the_drop_in_signature_when_present() -> None:
    if not _REAL.is_file():
        return                                  # submodule not checked out
    spec = importlib.util.spec_from_file_location('uv_multihead_sig', _REAL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real = [p for p in inspect.signature(mod.MultiHeadController.rebuild_multihead_outputs).parameters if p != 'self']
    null = inspect.signature(_NullMultiHeadController.rebuild_multihead_outputs)
    required = [n for n, p in null.parameters.items() if n != 'self' and p.default is inspect.Parameter.empty]
    assert required == real
