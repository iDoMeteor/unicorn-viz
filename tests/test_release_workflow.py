"""Guard tests for ``.github/workflows/release-installers.yml``.

A manual (workflow_dispatch) run is a dry run: it must be able to build the
installer artifacts but must never reach the job that publishes a release.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'release-installers.yml'


def _load() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text())


def test_dispatch_inputs_are_dry_run_defaults() -> None:
    wf = _load()
    inputs = wf[True]['workflow_dispatch']['inputs']  # PyYAML parses the key `on` as True
    assert inputs['version']['default'] == '0.0.0-ci'
    assert inputs['source_ref']['default'] == 'master'


def test_real_releases_still_only_come_from_version_tags() -> None:
    wf = _load()
    assert wf[True]['push']['tags'] == ['v*.*.*']


def test_publish_job_is_gated_on_a_version_tag() -> None:
    wf = _load()
    publish = wf['jobs']['publish']
    assert publish['if'] == "startsWith(github.ref, 'refs/tags/v')"
    # ...and it is the only job that can write a release.
    text = _WORKFLOW.read_text()
    assert text.count('softprops/action-gh-release') == 1
    assert 'action-gh-release' in str(publish['steps'])


def test_every_build_job_fetches_the_verified_wheelhouse() -> None:
    wf = _load()
    for name in ('linux-installer', 'native-deb', 'native-rpm'):
        steps = [s.get('run', '') for s in wf['jobs'][name]['steps']]
        assert any('fetch_wheelhouse.sh' in r for r in steps), name
