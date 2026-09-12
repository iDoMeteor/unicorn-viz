"""Regression tests for the auto_vj perf-bucket sub-spans (2026-09-12).

The ``auto_vj`` bucket of the ``Perf frame:`` line wraps five controllers.
A live session showed it holding a 6-10 ms median with no way to tell which
controller it was, so the line now also reports ``osc=``, ``lyrics=`` and
``vj=`` sub-spans.  These tests pin the format and the parser in
``tools/profiling/perf_frames.py`` that reads it.
"""
from __future__ import annotations

import importlib.util
import inspect
import re
from pathlib import Path

import unicornviz.app as app_mod

ROOT = Path(__file__).resolve().parents[1]
PERF_TOOL = ROOT / 'tools' / 'profiling' / 'perf_frames.py'


def _run_source() -> str:
    return inspect.getsource(app_mod.App.run)


def test_perf_line_reports_osc_lyrics_and_vj_sub_spans() -> None:
    src = _run_source()
    start = src.index("'Perf frame: total=%.2fms")
    # Join the adjacent string literals into the one format string.
    fmt = re.sub(r"'\s+'", '', src[start:src.index("mode=%s'", start)])
    for key in ('auto_vj=%.2fms', 'osc=%.2fms', 'lyrics=%.2fms', 'vj=%.2fms'):
        assert key in fmt, f'{key} missing from the Perf frame line'
    # auto_vj stays the whole bucket so older logs and the tool read alike;
    # the sub-spans follow it in loop order.
    assert fmt.index('auto_vj=') < fmt.index(' osc=') < fmt.index(' lyrics=') < fmt.index(' vj=')
    # Every sub-span has a matching perf_counter() marker in the loop.
    for marker in ('perf_before_osc', 'perf_after_osc', 'perf_after_lyrics'):
        assert f'{marker} = time.perf_counter()' in src


def test_perf_frames_tool_parses_new_fields(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location('perf_frames', PERF_TOOL)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    log = tmp_path / 'unicornviz_test.log'
    log.write_text(
        '12:00:00 INFO [unicornviz.app] hello\n'
        '12:00:01 DEBUG [unicornviz.app] Perf frame: total=40.00ms events=1.00ms '
        'midi=0.01ms auto=0.00ms audio=0.50ms auto_vj=9.00ms osc=0.50ms '
        'lyrics=2.50ms vj=6.00ms finale=0.00ms subsys_upd=20.00ms effects=1.00ms '
        'hud=0.10ms draw=3.00ms swap=5.00ms subsys_present=0.39ms fps=25.0 '
        'mode=single\n',
        encoding='utf-8',
    )
    rows = tool.parse(log)
    assert len(rows) == 1
    row = rows[0]
    assert row['auto_vj'] == 9.0 and row['osc'] == 0.5
    assert row['lyrics'] == 2.5 and row['vj'] == 6.0
    assert row['mode'] == 'single' and row['fps'] == 25.0
    names = tool.bucket_names(rows)
    assert names[0] == 'total' and 'vj' in names and 'fps' not in names
