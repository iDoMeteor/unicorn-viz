"""ProjectM preset HUD label normalization — regression tests.

Covers ``_projectm_preset_label()`` (unicornviz/app.py), which replaced the
raw ``f"{effect.NAME} - {current_label}"`` the effect banner pane used to
show for every ProjectM preset: a redundant "ProjectM Presets -" prefix
(identical on every preset) ahead of an arbitrarily long, un-trimmed
filename that visibly overflowed the fixed-width effect banner.
"""
from __future__ import annotations

from unicornviz.app import _projectm_preset_label, _smart_trim_label


def test_empty_label_returns_bare_prefix() -> None:
    assert _projectm_preset_label('') == 'pM:'
    assert _projectm_preset_label('   ') == 'pM:'


def test_short_name_gets_the_short_prefix_untrimmed() -> None:
    assert _projectm_preset_label('Fractal Bloom') == 'pM: Fractal Bloom'


def test_long_name_is_capped_at_the_limit() -> None:
    raw = (
        'TonyMilkdrop - Nuclear [Flexi - help out + alien complex] '
        '--- Isosceles edit1'
    )
    out = _projectm_preset_label(raw)
    assert len(out) == 44
    assert out.startswith('pM: TonyMilkdrop')


def test_version_marker_at_the_tail_survives_trimming() -> None:
    # Two presets differing only by their trailing edit number must not
    # collapse to the same displayed label -- that was the whole complaint:
    # a head-only truncation lost exactly this differentiator.
    raw1 = (
        'TonyMilkdrop - Nuclear [Flexi - help out + alien complex] '
        '--- Isosceles edit1'
    )
    raw2 = raw1[:-1] + '2'  # ...edit1 -> ...edit2
    out1 = _projectm_preset_label(raw1)
    out2 = _projectm_preset_label(raw2)
    assert out1 != out2
    assert out1.endswith('edit1')
    assert out2.endswith('edit2')


def test_custom_limit_is_respected() -> None:
    # _smart_trim_label floors head/tail at 20/12 chars (readability), so a
    # limit below ~35 doesn't actually shrink the output further -- pick a
    # limit above that floor to exercise the cap meaningfully.
    raw = 'Artist - A Fairly Long Effect Description Here That Keeps Going'
    out = _projectm_preset_label(raw, limit=40)
    assert len(out) == 40


def test_matches_the_shared_smart_trim_helper() -> None:
    # Confirms the label is exactly the generic HUD trim applied to a
    # short "pM:" prefix -- no bespoke re-implementation to drift from
    # _smart_trim_label's own (well-tested) head/tail arithmetic.
    raw = 'Some Preset Name That Runs On For Quite A While Past The Cap'
    assert _projectm_preset_label(raw) == _smart_trim_label(f'pM: {raw}', 44)


def test_output_never_exceeds_the_limit_across_many_real_shaped_names() -> None:
    samples = [
        'TonyMilkdrop - Nuclear [Flexi - help out + alien complex] --- Isosceles edit1',
        'Slow transition to black - gas effect + zoom out === amandio c - '
        'magnetosphere --- Isosceles edit',
        'amandio c, flexi, martin - Op illusions - curved4',
        'amandio c, flexi - Planet escher - random2 nz love grace hope charity',
        'flexi + bdrv - ultramix#05 [alien complex mix] [not roaring at all]',
        'martin - massif central [laser blasting]',
        'A',
    ]
    for raw in samples:
        assert len(_projectm_preset_label(raw)) <= 44, raw
