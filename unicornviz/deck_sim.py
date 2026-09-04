"""Deck-sim layout descriptors — device-model geometry for a controller
mirror view.

A "deck-sim" is a Control Room view that mirrors a connected MIDI
controller's physical surface (grid pads, scene/track strips, faders) so an
operator can click/drag it exactly like the real hardware. The mapping data
(which note/CC does what) already lives generically in
``unicornviz.vj_api.VJApi.midi_note_map()``/``midi_cc_map()`` — what's
missing is the *physical shape*: which note sits at which row/column, how
many faders there are, whether a scene or track strip exists at all. That's
what :class:`DeckSimLayout` describes.

One drop-in per device model registers exactly one :class:`DeckSimLayout`
at startup (see ``VJApi.register_deck_sim_layout``); a consumer (the Control
Room deck-sim view) resolves whichever one is active via
``VJApi.active_deck_sim_layout()`` and renders generically off the
descriptor — adding a second controller model means registering a second
layout, not writing a second view. See
``drop-ins/control-room-01/docs/deck-sim-plan.md`` for the full design.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class FaderSpec:
    """One physical fader/slider on a controller surface.

    ``label`` names the fader's *physical position* ("1".."8", "MASTER"),
    not the parameter currently bound to ``cc`` — that binding is
    config/profile-driven and can change independently of where the fader
    sits on the hardware.
    """

    cc: int
    label: str
    is_master: bool = False


@dataclass(frozen=True, slots=True)
class DeckSimLayout:
    """Physical layout of one controller model, for a deck-sim mirror view.

    ``device`` must match the token a registered ``ControllerProfile``
    stamps into ``meta.device`` (see ``midi-controllers-01/
    controller_profiles.py``) — that's how ``VJApi.active_deck_sim_layout()``
    resolves which layout applies to the currently active preset.

    ``grid_note`` maps ``(row, col)`` — row 0 at the bottom, matching how a
    physical clip-launch grid is read — to a MIDI note number. Pure
    function of the device's own note-numbering scheme; no per-instance
    state.
    """

    device: str
    label: str
    grid_rows: int
    grid_cols: int
    grid_note: Callable[[int, int], int]
    scene_notes: tuple[int, ...] = ()
    track_notes: tuple[int, ...] = ()
    faders: tuple[FaderSpec, ...] = ()
