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
    assert 0.0 < floor <= 1.0, f'{name}: implausible floor {floor}'


@pytest.mark.parametrize('name', sorted(RIDES))
def test_zoom_floor_keeps_the_field_of_view_sane(rides, name):
    """The floor has to actually bound the FOV, not merely exist."""
    limit = MAX_FOV_CHASE if name == 'Coaster Cam' else MAX_FOV_FIRST_PERSON
    fov = _fov_degrees(rides[name]._MIN_ZOOM)
    assert fov <= limit, (
        f'{name}: floor {rides[name]._MIN_ZOOM} gives {fov:.1f} deg, '
        f'over the {limit} deg limit'
    )


@pytest.mark.parametrize('name', sorted(RIDES))
def test_randomiser_cannot_roll_below_the_floor(rides, config, name):
    """config.toml bounds the app's zoom randomiser to what the ride can draw.

    Without this the randomiser's own default range starts at 0.30, well past
    the point the track stops reading, and no amount of clamping inside the
    effect would stop the HUD from reporting a zoom the ride never honoured.
    """
    section = config['effects'][RIDES[name]]
    lo = section.get('random_zoom_min')
    assert lo is not None, f'{name}: config.toml sets no random_zoom_min'
    assert lo >= rides[name]._MIN_ZOOM, (
        f'{name}: randomiser may roll {lo}, below the ride floor '
        f'{rides[name]._MIN_ZOOM}'
    )


@pytest.mark.parametrize('name', sorted(RIDES))
def test_configured_zoom_is_not_already_below_the_floor(rides, config, name):
    """The shipped zoom itself has to be something the ride can honour."""
    zoom = config['effects'][RIDES[name]].get('zoom', 1.0)
    assert zoom >= rides[name]._MIN_ZOOM, (
        f'{name}: config zoom {zoom} is below the floor '
        f'{rides[name]._MIN_ZOOM}'
    )
