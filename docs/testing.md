# Unicorn Viz Testing Guide

Owner: Studio Engineering
Status: active
Last updated: 2026-06-03

This guide defines the baseline test workflow for Unicorn Viz.

## Scope

- Unit tests cover core runtime behavior that can be validated without opening
  an SDL window or running a live OpenGL render loop.
- Focus areas include:
  - config defaults and startup policy
  - audio fallback state-machine behavior
  - public VJ API safety when optional drop-ins are absent

## Test Layout

- Test root: tests/
- Current baseline suite:
  - tests/test_audio_capture_fallback.py
  - tests/test_audio_manager_startup.py
  - tests/test_hotkeys_behavior.py
  - tests/test_ansi_loader_edge_cases.py
  - tests/test_vj_api_postfx.py
  - tests/test_config_audio_defaults.py

## Running Tests

Use the project virtual environment:

```bash
/home/jj/Repos/unicorn-viz/.venv/bin/python -m pytest
```

Run a focused module:

```bash
/home/jj/Repos/unicorn-viz/.venv/bin/python -m pytest tests/test_audio_capture_fallback.py
```

Run a single test:

```bash
/home/jj/Repos/unicorn-viz/.venv/bin/python -m pytest tests/test_vj_api_postfx.py::test_vj_api_state_safe_with_null_postfx_controller
```

Install the local pre-commit hook so tests run before each commit:

```bash
/home/jj/Repos/unicorn-viz/.venv/bin/python -m pip install pre-commit
/home/jj/Repos/unicorn-viz/.venv/bin/pre-commit install
```

Run the hook manually on demand:

```bash
/home/jj/Repos/unicorn-viz/.venv/bin/pre-commit run --all-files
```

## pytest Configuration

pytest settings are stored in pyproject.toml under tool.pytest.ini_options:

- testpaths = ["tests"]
- python_files = ["test_*.py"]
- python_functions = ["test_*"]
- addopts = "-ra"

## Policy

- Any runtime bug fix in core modules should include at least one regression
  test when the behavior is testable in a headless unit test.
- New optional-drop-in integration points in core should include at least one
  safety test that validates behavior when the drop-in is unavailable.
- Commits should pass the local pre-commit pytest hook; test enforcement is
  local pre-commit-first rather than relying on a GitHub workflow gate.

## Next Expansion Targets

- Add smoke tests for startup retry/failure paths in AudioManager.
- Add HotkeyHandler behavior tests for key chords and passive/system key rules.
- Add parser/asset tests for ANSI loading edge-cases (CP437 + SAUCE handling).