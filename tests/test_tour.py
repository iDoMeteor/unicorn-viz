"""First-run tour — regression tests.

Covers the three layers of the v1 tour
(``docs/planning/first-run-tour-plan-2026-07-18.md``):

* ``unicornviz.tour`` — slide deck content, ``{key:...}`` token resolution,
  startup policy, and slide-index clamping.
* ``Overlays`` — dialog state machine, pure-geometry layout, and pointer
  hit-testing (bare ``__new__`` instances, no GL context — the same pattern
  as the other overlay tests).
* ``App`` — persistence round-trip through the runtime state store and the
  startup trigger (``__new__`` instance with stubbed state getters).
"""
from __future__ import annotations

from unicornviz.app import App
from unicornviz.overlays import Overlays
from unicornviz.tour import (
    CORE_TOUR_SLIDES,
    STATE_LAST_SLIDE,
    STATE_SHOW_ON_STARTUP,
    TourSlide,
    clamp_slide_index,
    resolve_slide_body,
    should_show_on_startup,
)

# --------------------------------------------------------------------------- #
# unicornviz.tour — content + policy
# --------------------------------------------------------------------------- #


def test_resolve_slide_body_replaces_known_tokens() -> None:
    out = resolve_slide_body(
        'Press {key:Next effect} to advance.',
        lambda desc: 'N' if desc == 'Next effect' else '',
    )
    assert out == 'Press N to advance.'


def test_resolve_slide_body_falls_back_to_description() -> None:
    out = resolve_slide_body('Press {key:Missing binding}.', lambda desc: '')
    assert out == 'Press Missing binding.'


def test_resolve_slide_body_passthrough_and_empty() -> None:
    assert resolve_slide_body('no tokens here', lambda d: 'X') == 'no tokens here'
    assert resolve_slide_body('', lambda d: 'X') == ''


def test_clamp_slide_index_bounds_and_bad_input() -> None:
    assert clamp_slide_index(3, 8) == 3
    assert clamp_slide_index(-2, 8) == 0
    assert clamp_slide_index(99, 8) == 7
    assert clamp_slide_index('4', 8) == 4
    assert clamp_slide_index('junk', 8) == 0
    assert clamp_slide_index(None, 8) == 0
    assert clamp_slide_index(5, 0) == 0


def test_should_show_on_startup_defaults_true_on_first_run() -> None:
    store: dict[str, object] = {}
    assert should_show_on_startup(lambda k, d: store.get(k, d)) is True
    store[STATE_SHOW_ON_STARTUP] = False
    assert should_show_on_startup(lambda k, d: store.get(k, d)) is False


def test_core_deck_is_nonempty_with_complete_slides() -> None:
    assert len(CORE_TOUR_SLIDES) >= 5
    for slide in CORE_TOUR_SLIDES:
        assert isinstance(slide, TourSlide)
        assert slide.section and slide.title and slide.body


def test_core_deck_never_hardcodes_key_chords() -> None:
    # Bindings live in the help registry; slide copy must use {key:...}.
    for slide in CORE_TOUR_SLIDES:
        for fragment in ('Ctrl+', 'Shift+', 'Alt+', 'press N', 'press H'):
            assert fragment not in slide.body, (slide.title, fragment)


def test_core_deck_tokens_resolve_against_the_real_help_registry() -> None:
    o = _bare_overlays()
    for slide in CORE_TOUR_SLIDES:
        resolved = resolve_slide_body(slide.body, o.lookup_help_key)
        # A token that failed lookup degrades to its description text; that
        # fallback keeps copy readable but means the registry drifted.
        assert '{key:' not in resolved, slide.title
        import re

        for match in re.finditer(r'\{key:([^}]+)\}', slide.body):
            assert o.lookup_help_key(match.group(1).strip()) != '', (
                slide.title,
                match.group(1),
            )


# --------------------------------------------------------------------------- #
# Overlays — state machine, layout, hit-testing
# --------------------------------------------------------------------------- #


def _bare_overlays(width: float = 1280.0, height: float = 720.0) -> Overlays:
    o = object.__new__(Overlays)
    o._width = width
    o._height = height
    o._dynamic_help_order = []
    o._dynamic_help_sections = {}
    # blocking_modal_open reads every modal flag; only tour state has
    # class-level shell defaults, so zero the rest here.
    for flag in (
        '_show_presets', '_show_effects_browser', '_show_projectm_manager',
        '_show_system_monitor_modal', '_show_controller_help_modal',
        '_show_webcam_editor_modal', '_show_audio', '_show_midi',
        '_show_config_editor',
    ):
        setattr(o, flag, False)
    return o


def test_open_tour_requires_a_deck() -> None:
    o = _bare_overlays()
    o.open_tour(0, True)
    assert not o.tour_visible


def test_open_close_round_trip_preserves_state() -> None:
    o = _bare_overlays()
    o.set_tour_slides(CORE_TOUR_SLIDES)
    o.open_tour(2, False)
    assert o.tour_visible
    assert o.tour_state() == (2, False)
    assert o.close_tour() == (2, False)
    assert not o.tour_visible


def test_open_tour_clamps_out_of_range_resume_index() -> None:
    o = _bare_overlays()
    o.set_tour_slides(CORE_TOUR_SLIDES)
    o.open_tour(999, True)
    assert o.tour_state()[0] == len(CORE_TOUR_SLIDES) - 1
    o.open_tour(-5, True)
    assert o.tour_state()[0] == 0


def test_tour_next_reports_done_and_resets_resume_position() -> None:
    o = _bare_overlays()
    o.set_tour_slides(CORE_TOUR_SLIDES[:3])
    o.open_tour(0, True)
    assert o.tour_next() is False
    assert o.tour_next() is False
    assert o.tour_next() is True  # DONE on the last slide
    assert o.tour_state()[0] == 0  # resume position reset for the next open


def test_tour_prev_clamps_at_first_slide() -> None:
    o = _bare_overlays()
    o.set_tour_slides(CORE_TOUR_SLIDES)
    o.open_tour(1, True)
    o.tour_prev()
    o.tour_prev()
    assert o.tour_state()[0] == 0


def test_tour_toggle_startup_flips() -> None:
    o = _bare_overlays()
    o.set_tour_slides(CORE_TOUR_SLIDES)
    o.open_tour(0, True)
    assert o.tour_toggle_startup() is False
    assert o.tour_toggle_startup() is True


def test_tour_counts_as_blocking_modal() -> None:
    o = _bare_overlays()
    o.set_tour_slides(CORE_TOUR_SLIDES)
    assert not o.blocking_modal_open
    o.open_tour(0, True)
    assert o.blocking_modal_open


def test_layout_controls_sit_inside_the_panel() -> None:
    o = _bare_overlays()
    layout = o._tour_layout()
    px, py, pw, ph = layout['panel']
    for kind in ('prev', 'next', 'close', 'startup'):
        bx, by, bw, bh = layout[kind]
        assert px <= bx and bx + bw <= px + pw, kind
        assert py <= by and by + bh <= py + ph, kind


def test_layout_fits_small_windows() -> None:
    o = _bare_overlays(width=800.0, height=480.0)
    px, py, pw, ph = o._tour_layout()['panel']
    assert pw <= 800.0 * 0.9 + 1e-6
    assert ph <= 480.0 * 0.9 + 1e-6
    assert px >= 0 and py >= 0


def test_click_hit_testing_matches_layout() -> None:
    o = _bare_overlays()
    o.set_tour_slides(CORE_TOUR_SLIDES)
    o.open_tour(0, True)
    layout = o._tour_layout()
    for kind in ('prev', 'next', 'close', 'startup'):
        bx, by, bw, bh = layout[kind]
        assert o.handle_tour_click(bx + bw / 2, by + bh / 2) == kind
    px, py, pw, ph = layout['panel']
    assert o.handle_tour_click(px + 4.0, py + 4.0) == ''  # panel body: no-op


def test_click_and_motion_ignored_when_closed() -> None:
    o = _bare_overlays()
    o.set_tour_slides(CORE_TOUR_SLIDES)
    assert o.handle_tour_click(640.0, 360.0) == ''
    assert o.handle_tour_motion(640.0, 360.0) is False


def test_motion_updates_hover() -> None:
    o = _bare_overlays()
    o.set_tour_slides(CORE_TOUR_SLIDES)
    o.open_tour(0, True)
    bx, by, bw, bh = o._tour_layout()['next']
    assert o.handle_tour_motion(bx + bw / 2, by + bh / 2) is True
    assert o._tour_hover == 'next'
    o.handle_tour_motion(0.0, 0.0)
    assert o._tour_hover == ''


def test_help_registry_lists_the_tour_key() -> None:
    o = _bare_overlays()
    assert o.lookup_help_key('Take the tour') == 'F1'


# --------------------------------------------------------------------------- #
# App — persistence + startup trigger
# --------------------------------------------------------------------------- #


def _bare_app(store: dict[str, object]) -> App:
    app = object.__new__(App)
    o = _bare_overlays()
    o.set_tour_slides(CORE_TOUR_SLIDES)
    app._overlays = o
    app.get_runtime_state = lambda key, default=None: store.get(key, default)
    app.set_runtime_state = lambda key, value: store.__setitem__(key, value)
    return app


def test_open_tour_resumes_from_persisted_state() -> None:
    store: dict[str, object] = {STATE_LAST_SLIDE: 3, STATE_SHOW_ON_STARTUP: False}
    app = _bare_app(store)
    app.open_tour()
    assert app._overlays.tour_visible
    assert app._overlays.tour_state() == (3, False)


def test_close_tour_persists_slide_and_startup_toggle() -> None:
    store: dict[str, object] = {}
    app = _bare_app(store)
    app.open_tour()
    app._overlays.tour_next()
    app._overlays.tour_toggle_startup()  # True -> False
    app.close_tour()
    assert not app._overlays.tour_visible
    assert store[STATE_LAST_SLIDE] == 1
    assert store[STATE_SHOW_ON_STARTUP] is False


def test_tour_advance_on_last_slide_completes_and_persists_reset() -> None:
    app = _bare_app({})
    # The live deck may include discovered drop-in slides beyond the core set.
    store: dict[str, object] = {STATE_LAST_SLIDE: len(app._tour_deck()) - 1}
    app.get_runtime_state = lambda key, default=None: store.get(key, default)
    app.set_runtime_state = lambda key, value: store.__setitem__(key, value)
    app.open_tour()
    app.tour_advance()
    assert not app._overlays.tour_visible
    assert store[STATE_LAST_SLIDE] == 0  # next open starts from the top


def test_tour_advance_mid_deck_saves_resume_position() -> None:
    store: dict[str, object] = {}
    app = _bare_app(store)
    app.open_tour()
    app.tour_advance()
    assert app._overlays.tour_visible
    assert store[STATE_LAST_SLIDE] == 1


def test_startup_trigger_offers_tour_on_first_run() -> None:
    store: dict[str, object] = {}
    app = _bare_app(store)
    app._maybe_open_tour_on_startup()
    assert app._overlays.tour_visible


def test_startup_trigger_respects_disabled_toggle() -> None:
    store: dict[str, object] = {STATE_SHOW_ON_STARTUP: False}
    app = _bare_app(store)
    app._maybe_open_tour_on_startup()
    assert not app._overlays.tour_visible


# --------------------------------------------------------------------------- #
# Drop-in TOUR_SLIDES discovery (P2)
# --------------------------------------------------------------------------- #


def test_discovery_normalises_and_skips_malformed_entries(tmp_path, monkeypatch) -> None:
    import unicornviz.dropins as dropins

    mod_dir = tmp_path / 'demo-01'
    mod_dir.mkdir()
    (mod_dir / 'demo.py').write_text(
        "TOUR_SLIDES = [\n"
        "    ('Demo', 'Good tuple', 'Body one'),\n"
        "    {'section': 'Demo', 'title': 'Good dict', 'body': 'Body two'},\n"
        "    ('Missing body',),\n"
        "    {'section': 'Demo', 'title': '', 'body': 'empty title'},\n"
        "    'not a slide',\n"
        "]\n"
    )
    monkeypatch.setattr(dropins, '_dropins_root', lambda: tmp_path)
    monkeypatch.setattr(dropins, '_is_dropin_excluded', lambda name: False)
    slides = dropins.discover_dropin_tour_slides()
    assert slides == [
        ('Demo', 'Good tuple', 'Body one'),
        ('Demo', 'Good dict', 'Body two'),
    ]


def test_real_dropin_tour_slides_are_wellformed_and_tokens_resolve() -> None:
    import re

    from unicornviz.dropins import (
        discover_dropin_help_entries,
        discover_dropin_tour_slides,
    )

    slides = discover_dropin_tour_slides()
    known = {
        desc.strip().lower()
        for _, entries in Overlays.CORE_HELP_SECTIONS
        for _, desc in entries
    }
    known.update(
        desc.strip().lower() for _, _, desc in discover_dropin_help_entries()
    )
    for section, title, body in slides:
        assert section and title and body
        for match in re.finditer(r'\{key:([^}]+)\}', body):
            assert match.group(1).strip().lower() in known, (title, match.group(1))


def test_tour_deck_appends_discovered_slides(monkeypatch) -> None:
    import unicornviz.app as app_mod

    monkeypatch.setattr(
        app_mod,
        'discover_dropin_tour_slides',
        lambda: [('Demo', 'Extra', 'Extra body')],
    )
    app = _bare_app({})
    deck = app._tour_deck()
    assert deck[: len(CORE_TOUR_SLIDES)] == CORE_TOUR_SLIDES
    assert deck[-1] == TourSlide('Demo', 'Extra', 'Extra body')


def test_tour_deck_survives_discovery_failure(monkeypatch) -> None:
    import unicornviz.app as app_mod

    def _boom() -> list[tuple[str, str, str]]:
        raise RuntimeError('scan exploded')

    monkeypatch.setattr(app_mod, 'discover_dropin_tour_slides', _boom)
    app = _bare_app({})
    assert app._tour_deck() == CORE_TOUR_SLIDES


def test_toggle_tour_opens_and_closes() -> None:
    store: dict[str, object] = {}
    app = _bare_app(store)
    app.toggle_tour()
    assert app._overlays.tour_visible
    app.toggle_tour()
    assert not app._overlays.tour_visible
    assert STATE_LAST_SLIDE in store
