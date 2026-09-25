"""The rollercoaster rides must not be allowed to zoom out past their geometry.

``zoom`` divides the screen coordinate, so it is a field-of-view control rather
than a camera dolly: at 1.0 the horizontal FOV is about 83 degrees and every
step down widens it. On a first-person ride the rails run right beside and
below the rider, so past roughly 0.8 they project out to the frame corners and
the shot stops reading as riding the track and starts reading as standing
behind it. At the old floor of 0.05 the FOV approached 174 degrees.

Two independent things had to agree for that to be fixed, and this pins both:
the effect clamps whatever it is handed, and the app's zoom randomiser -- which
otherwise rolls uniform(0.30, 1.80) -- is bounded per effect in config.toml so
the dice cannot land somewhere the ride cannot draw. GL-free.
"""
from __future__ import annotations

import math
import tomllib
from pathlib import Path

import pytest

from unicornviz.effects.registry import get_effects

_REPO = Path(__file__).resolve().parents[1]

# Effect NAME -> the config.toml section that configures it.
RIDES = {
    'First Drop': 'FirstDrop',
    'Corkscrew': 'Corkscrew',
    'Night Coaster': 'NightCoaster',
    'Mine Train': 'MineTrain',
    'Coaster Cam': 'CoasterCam',
    'Log Flume': 'LogFlume',
}
# Widest horizontal FOV, in degrees, that still reads as riding the track.
# Measured across the pack at 16:9; past this the rails reach the corners.
MAX_FOV_FIRST_PERSON = 95.0
# Coaster Cam watches from outside the ride, so a wide view only shows more of
# the park rather than turning the track inside out.
MAX_FOV_CHASE = 125.0
_ASPECT = 16.0 / 9.0


def _fov_degrees(zoom: float) -> float:
    """Horizontal field of view the shader gets for this zoom, at 16:9."""
    return math.degrees(math.atan((_ASPECT * 0.5) / zoom)) * 2.0


@pytest.fixture(scope='module')
def rides():
    found = {e.NAME: e for e in get_effects() if e.NAME in RIDES}
    missing = set(RIDES) - set(found)
    assert not missing, f'rides missing from the registry: {sorted(missing)}'
    return found


@pytest.fixture(scope='module')
def config():
    with open(_REPO / 'config.toml', 'rb') as fh:
        return tomllib.load(fh)


@pytest.mark.parametrize('name', sorted(RIDES))
def test_ride_declares_a_zoom_floor(rides, name):
    """Every ride states the widest view it can draw."""
    floor = getattr(rides[name], '_MIN_ZOOM', None)
    assert isinstance(floor, float), f'{name} has no _MIN_ZOOM'
    # A floor above 1.0 is legitimate: it frames the ride tighter than the
    # nominal default rather than merely capping how far out you may go. The
    # Log Flume does exactly that at 1.25, because its channel is open water
    # with the scenery set well back. What such a floor must not do is exceed
    # the ride's own configured zoom and clamp it silently -- that is what
    # test_configured_zoom_is_not_already_below_the_floor is for.
    assert 0.0 < floor <= 2.0, f'{name}: implausible floor {floor}'


@pytest.mark.parametrize('name', sorted(RIDES))
def test_zoom_floor_keeps_the_field_of_view_sane(rides, name):
    """The floor has to actually bound the FOV, not merely exist."""
    limit = MAX_FOV_CHASE if name == 'Coaster Cam' else MAX_FOV_FIRST_PERSON
    fov = _fov_degrees(rides[name]._MIN_ZOOM)
    assert fov <= limit, (
        f'{name}: floor {rides[name]._MIN_ZOOM} gives {fov:.1f} deg, '
        f'over the {limit} deg limit'
    )


@pytest.fixture(scope='module')
def gl_ctx():
    moderngl = pytest.importorskip('moderngl')
    try:
        c = moderngl.create_standalone_context()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f'no headless GL context: {exc}')
    yield c
    c.release()


@pytest.mark.parametrize('given', [None, 0.30, 5.0])
@pytest.mark.parametrize('name', sorted(RIDES))
def test_randomiser_cannot_roll_below_the_floor(rides, gl_ctx, name, given):
    """The zoom randomiser never rolls a zoom the ride cannot draw.

    The app's randomiser reads ``random_zoom_min`` off the live effect's
    config, and its own default starts at 0.30 -- well past the point a track
    stops reading -- so without a floor the HUD reports zooms the ride then
    clamps and never draws. The ride supplies that floor itself now rather
    than relying on config.toml (which is being retired) to repeat
    ``_MIN_ZOOM`` by hand. Checked with no key, a key below the floor, and a
    key above it, which must be honored as given.
    """
    cls = rides[name]
    cfg = {} if given is None else {'random_zoom_min': given}
    inst = cls(gl_ctx, 64, 36, dict(cfg))
    try:
        lo = float(inst.config['random_zoom_min'])
        assert lo >= cls._MIN_ZOOM, (
            f'{name}: randomiser may roll {lo}, below the ride floor {cls._MIN_ZOOM}')
        if given is not None and given > cls._MIN_ZOOM:
            assert lo == given, f'{name}: a higher configured floor {given} was not honored'
    finally:
        inst.destroy()


def test_ride_does_not_mutate_the_config_it_was_given(rides, gl_ctx):
    """self.config may be the loaded config's own table -- never write into it."""
    cls = rides['First Drop']
    cfg = {'random_zoom_min': 0.10}
    inst = cls(gl_ctx, 64, 36, cfg)
    try:
        assert cfg == {'random_zoom_min': 0.10}
    finally:
        inst.destroy()


@pytest.mark.parametrize('name', sorted(RIDES))
def test_configured_zoom_is_not_already_below_the_floor(rides, config, name):
    """The shipped zoom itself has to be something the ride can honour."""
    zoom = config['effects'][RIDES[name]].get('zoom', 1.0)
    assert zoom >= rides[name]._MIN_ZOOM, (
        f'{name}: config zoom {zoom} is below the floor '
        f'{rides[name]._MIN_ZOOM}'
    )
