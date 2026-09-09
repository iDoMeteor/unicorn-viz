"""First launch turns the shipped template into config.toml (and rescues
``config.toml.toml``); an explicit --config path is never touched."""
from __future__ import annotations

from pathlib import Path

from unicornviz.__main__ import _seed_config


def test_seeds_from_dist_template(tmp_path: Path) -> None:
    (tmp_path / 'config.dist.toml').write_text('[window]\nfullscreen = true\n')
    _seed_config(tmp_path / 'config.toml')
    assert (tmp_path / 'config.toml').read_text() == '[window]\nfullscreen = true\n'


def test_renames_doubled_extension_into_place(tmp_path: Path) -> None:
    (tmp_path / 'config.dist.toml').write_text('# template\n')
    (tmp_path / 'config.toml.toml').write_text('[logging]\nlevel = "debug"\n')
    _seed_config(tmp_path / 'config.toml')
    assert not (tmp_path / 'config.toml.toml').exists()
    assert (tmp_path / 'config.toml').read_text() == '[logging]\nlevel = "debug"\n'


def test_existing_config_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / 'config.dist.toml').write_text('# template\n')
    (tmp_path / 'config.toml').write_text('# mine\n')
    (tmp_path / 'config.toml.toml').write_text('# stray\n')
    _seed_config(tmp_path / 'config.toml')
    assert (tmp_path / 'config.toml').read_text() == '# mine\n'
    assert (tmp_path / 'config.toml.toml').exists()      # only warned about


def test_explicit_other_path_is_never_seeded(tmp_path: Path) -> None:
    (tmp_path / 'config.dist.toml').write_text('# template\n')
    _seed_config(tmp_path / 'custom.toml')
    assert not (tmp_path / 'custom.toml').exists()


def test_nothing_to_seed_is_fine(tmp_path: Path) -> None:
    _seed_config(tmp_path / 'config.toml')
    assert not (tmp_path / 'config.toml').exists()
