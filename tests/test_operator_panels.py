"""Operator-panel registry (Control Room panel/page contract) -- P1 tests.

Covers unicornviz/operator_panels.py descriptor validation and the VJApi
registry (register/replace/unregister, page filtering, ordering, tab order).
No GL, no app: VJApi binds to a bare stub exactly as test_deck_sim.py does.
See docs/planning/control-room-panel-registry-plan-2026-09-04.md section 4.
"""
from __future__ import annotations

import pytest

from unicornviz.operator_panels import (
    MAIN_PAGE,
    PANEL_SIZES,
    OperatorPage,
    OperatorPanel,
    PanelButton,
    PanelCanvas,
    PanelContent,
    PanelMeter,
    PanelRow,
    sort_pages,
)
from unicornviz.vj_api import VJApi


class _StubApp:
    def __init__(self) -> None:
        self._midi_manager = None


def _content() -> PanelContent:
    return PanelContent(rows=(PanelRow('A', '1'),))


def _panel(name: str, **kw) -> OperatorPanel:
    kw.setdefault('content', _content)
    return OperatorPanel(name=name, title=name.upper(), **kw)


# --------------------------------------------------------------------------- #
# Descriptors
# --------------------------------------------------------------------------- #

def test_panel_content_defaults_are_empty() -> None:
    c = PanelContent()
    assert c.rows == () and c.buttons == () and c.meters == ()
    assert c.columns == 1 and c.status == ''


def test_row_button_meter_shapes() -> None:
    assert PanelRow('L').value == '' and PanelRow('L').emphasis == ''
    b = PanelButton('go', 'GO')
    assert (b.tooltip, b.active, b.accent, b.payload) == ('', False, '', None)
    m = PanelMeter('BASS', 0.5)
    assert m.text == ''


def test_panel_requires_name() -> None:
    with pytest.raises(ValueError):
        OperatorPanel(name='', title='X', content=_content)
    with pytest.raises(ValueError):
        OperatorPanel(name='   ', title='X', content=_content)


def test_panel_name_rejects_namespace_separator() -> None:
    with pytest.raises(ValueError):
        _panel('a:b')


def test_panel_size_must_be_known() -> None:
    for size in PANEL_SIZES:
        _panel('ok', size=size)
    with pytest.raises(ValueError):
        _panel('bad', size='huge')


def test_panel_needs_content_or_draw() -> None:
    with pytest.raises(ValueError):
        OperatorPanel(name='x', title='X')
    OperatorPanel(name='x', title='X', draw=lambda canvas: None)  # draw alone is fine


def test_panel_defaults() -> None:
    p = _panel('p')
    assert p.page == MAIN_PAGE and p.priority == 0 and p.size == 'medium'
    assert p.on_action is None and p.draw is None and p.tooltips is None


def test_panel_is_frozen() -> None:
    p = _panel('p')
    with pytest.raises(AttributeError):
        p.title = 'other'  # type: ignore[misc]


def test_page_validation() -> None:
    with pytest.raises(ValueError):
        OperatorPage(name='', title='X')
    with pytest.raises(ValueError):
        OperatorPage(name='a:b', title='X')
    with pytest.raises(ValueError):
        OperatorPage(name=MAIN_PAGE, title='Main')
    pg = OperatorPage(name='deck_sim', title='Deck Sim', owner='control-room-01')
    assert pg.draw is None and pg.available is None


def test_panel_canvas_shape() -> None:
    calls = []
    canvas = PanelCanvas(draw=object(), rect=(0, 0, 10, 10), theme=object(), fonts={},
                         add_hotspot=lambda a, p, r: calls.append((a, p, r)))
    canvas.add_hotspot('x', None, (1, 2, 3, 4))
    assert calls == [('x', None, (1, 2, 3, 4))]


def test_sort_pages_is_by_title_case_insensitive_then_name() -> None:
    pages = [
        OperatorPage('z', 'beta'),
        OperatorPage('a', 'Alpha'),
        OperatorPage('m', 'alpha'),
    ]
    assert [p.name for p in sort_pages(pages)] == ['a', 'm', 'z']


# --------------------------------------------------------------------------- #
# VJApi registry
# --------------------------------------------------------------------------- #

def test_register_and_list_panels_ordered_by_priority_then_name() -> None:
    api = VJApi(_StubApp())
    api.register_operator_panel(_panel('zeta', priority=1))
    api.register_operator_panel(_panel('beta', priority=0))
    api.register_operator_panel(_panel('alpha', priority=1))
    assert [p.name for p in api.operator_panels()] == ['beta', 'alpha', 'zeta']


def test_register_panel_replaces_by_name() -> None:
    api = VJApi(_StubApp())
    api.register_operator_panel(_panel('x', priority=5))
    api.register_operator_panel(OperatorPanel(name='x', title='NEW', content=_content))
    panels = api.operator_panels()
    assert len(panels) == 1 and panels[0].title == 'NEW' and panels[0].priority == 0


def test_unregister_panel() -> None:
    api = VJApi(_StubApp())
    api.register_operator_panel(_panel('x'))
    assert api.unregister_operator_panel('x') is True
    assert api.unregister_operator_panel('x') is False
    assert api.operator_panels() == []
    assert api.operator_panel('x') is None


def test_operator_panels_filters_by_page() -> None:
    api = VJApi(_StubApp())
    api.register_operator_panel(_panel('a'))
    api.register_operator_panel(_panel('b', page='deck_sim'))
    assert [p.name for p in api.operator_panels(MAIN_PAGE)] == ['a']
    assert [p.name for p in api.operator_panels('deck_sim')] == ['b']
    assert [p.name for p in api.operator_panels('nope')] == []
    assert len(api.operator_panels()) == 2


def test_register_panel_rejects_wrong_type() -> None:
    api = VJApi(_StubApp())
    with pytest.raises(TypeError):
        api.register_operator_panel({'name': 'x'})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        api.register_operator_page('x')  # type: ignore[arg-type]


def test_pages_listed_in_tab_order_and_replace_by_name() -> None:
    api = VJApi(_StubApp())
    api.register_operator_page(OperatorPage('z', 'Zulu'))
    api.register_operator_page(OperatorPage('d', 'Deck Sim'))
    api.register_operator_page(OperatorPage('z', 'Alpha'))  # replaces 'z'
    assert [(p.name, p.title) for p in api.operator_pages()] == [('z', 'Alpha'), ('d', 'Deck Sim')]
    assert api.operator_page('d').title == 'Deck Sim'
    assert api.unregister_operator_page('d') is True
    assert api.unregister_operator_page('d') is False
    assert [p.name for p in api.operator_pages()] == ['z']


def test_empty_registry() -> None:
    api = VJApi(_StubApp())
    assert api.operator_panels() == []
    assert api.operator_pages() == []
    assert api.operator_page('main') is None


# --------------------------------------------------------------------------- #
# Standard shared pages (integration plan section 3.7)
# --------------------------------------------------------------------------- #

def test_standard_pages_shape_and_names() -> None:
    from unicornviz.operator_panels import STANDARD_PAGES

    names = [n for n, _t in STANDARD_PAGES]
    assert names == ['fx', 'output', 'overlays', 'sources']
    assert len(set(names)) == len(names)
    for name, title in STANDARD_PAGES:
        assert name != MAIN_PAGE
        assert ':' not in name
        assert title and title[0].isupper()
        # Every standard page must be a valid OperatorPage as-is.
        OperatorPage(name=name, title=title, owner='control-room-01')


def test_standard_pages_sort_after_main_by_title() -> None:
    from unicornviz.operator_panels import STANDARD_PAGES

    pages = [OperatorPage(name=n, title=t) for n, t in STANDARD_PAGES]
    assert [p.name for p in sort_pages(pages)] == ['fx', 'output', 'overlays', 'sources']
