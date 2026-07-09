"""GL driver debug-env startup wiring — regression tests.

``_install_gl_debug_env`` sets MESA_DEBUG/LIBGL_DEBUG/EGL_LOG_LEVEL when
``[logging] level = "DEBUG"``, so diagnosing a driver-level issue (e.g. a
PBO buffer mapping failure) no longer requires the owner to remember and
manually export three env vars before every debug run.
"""
from __future__ import annotations

import os

from unicornviz import __main__ as main_module


class _StubCfg:
    def __init__(self, level: str = 'INFO') -> None:
        self._level = level

    def get(self, *keys, default=None):
        if keys == ('logging', 'level'):
            return self._level
        return default


_GL_DEBUG_VARS = ('MESA_DEBUG', 'LIBGL_DEBUG', 'EGL_LOG_LEVEL')


def _clear_gl_debug_env(monkeypatch) -> None:
    for var in _GL_DEBUG_VARS:
        monkeypatch.delenv(var, raising=False)


def test_sets_all_three_vars_when_level_is_debug(monkeypatch) -> None:
    _clear_gl_debug_env(monkeypatch)
    main_module._install_gl_debug_env(_StubCfg(level='DEBUG'))
    assert os.environ.get('MESA_DEBUG') == '1'
    assert os.environ.get('LIBGL_DEBUG') == 'verbose'
    assert os.environ.get('EGL_LOG_LEVEL') == 'debug'


def test_case_insensitive_debug_level(monkeypatch) -> None:
    _clear_gl_debug_env(monkeypatch)
    main_module._install_gl_debug_env(_StubCfg(level='debug'))
    assert os.environ.get('MESA_DEBUG') == '1'


def test_leaves_env_untouched_for_non_debug_levels(monkeypatch) -> None:
    for level in ('INFO', 'WARN', 'NONE', 'ERROR'):
        _clear_gl_debug_env(monkeypatch)
        main_module._install_gl_debug_env(_StubCfg(level=level))
        for var in _GL_DEBUG_VARS:
            assert var not in os.environ


def test_does_not_clobber_an_operator_set_value(monkeypatch) -> None:
    monkeypatch.setenv('MESA_DEBUG', 'custom')
    monkeypatch.delenv('LIBGL_DEBUG', raising=False)
    monkeypatch.delenv('EGL_LOG_LEVEL', raising=False)
    main_module._install_gl_debug_env(_StubCfg(level='DEBUG'))
    assert os.environ.get('MESA_DEBUG') == 'custom'  # untouched
    assert os.environ.get('LIBGL_DEBUG') == 'verbose'  # still filled in
