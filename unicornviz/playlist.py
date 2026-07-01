"""
Demo playlist — manages the ordered collection of effect classes and tracks
the currently active index.

Modes
-----
``sequential``  Cycles effects in alphabetical display-name order.
``random``      Picks a random effect on each advance; can produce repeats.

Pinned sequence
---------------
Set ``[playlist] sequence = ["Plasma", "Fire", "Tunnel"]`` in config.toml to
restrict the playlist to exactly those effects in that order.  Unknown names
(typos, missing effects) are silently ignored.

Thread safety
-------------
All mutating operations (advance, go_prev, go_index, toggle_random) are called
from the main thread only, so no locking is required.
"""
from __future__ import annotations

import random
from collections import deque
from typing import Type

from unicornviz.effects.base import BaseEffect
from unicornviz.config import Config


class Playlist:
    def __init__(
        self,
        effect_classes: list[Type[BaseEffect]],
        cfg: Config,
    ) -> None:
        sequence: list[str] = cfg.get("playlist", "sequence", default=[])
        mode: str = cfg.get("demo", "mode", default="sequential")
        start_name: str = cfg.get("playlist", "start_effect", default="")

        if sequence:
            name_map = {cls.__name__: cls for cls in effect_classes}
            filtered = [name_map[n] for n in sequence if n in name_map]
            self._effects = filtered if filtered else effect_classes
        else:
            self._effects = list(effect_classes)

        self._mode = mode
        self._shuffle_cycle: list[int] = []
        self._shuffle_pos: int = 0
        self._shuffle_recent: deque[int] = deque(maxlen=3)
        # Display NAMEs (or class names) excluded from auto-rotation. Manual
        # jumps via go_index() still reach a disabled effect; advance/prev/random
        # skip them. Persisted globally by the app.
        self._disabled: set[str] = set()

        # Find starting index by NAME attribute (display name) or class name
        self._index = 0
        if start_name:
            for i, cls in enumerate(self._effects):
                if cls.NAME == start_name or cls.__name__ == start_name:
                    self._index = i
                    break

        self._reset_shuffle_cycle(avoid_index=self._index)

    def set_disabled(self, names: 'set[str] | list[str] | None') -> None:
        """Set the effects excluded from auto-rotation (by display/class name)."""
        self._disabled = {str(n) for n in (names or [])}
        if self._mode == "random":
            self._reset_shuffle_cycle(avoid_index=self._index)

    def _is_enabled(self, idx: int) -> bool:
        cls = self._effects[idx]
        return cls.NAME not in self._disabled and cls.__name__ not in self._disabled

    def _enabled_indices(self) -> list[int]:
        return [i for i in range(len(self._effects)) if self._is_enabled(i)]

    def _reset_shuffle_cycle(self, avoid_index: int | None = None) -> None:
        """Build a shuffled traversal order over the enabled effects.

        Falls back to all effects if every effect is disabled so rotation never
        deadlocks on an empty cycle.
        """
        enabled = self._enabled_indices()
        self._shuffle_cycle = enabled if enabled else list(range(len(self._effects)))
        random.shuffle(self._shuffle_cycle)

        blocked: set[int] = set(self._shuffle_recent)
        if avoid_index is not None:
            blocked.add(avoid_index)

        # Move a blocked first pick to the end when alternatives exist.
        if len(self._shuffle_cycle) > 1 and self._shuffle_cycle[0] in blocked:
            for i, idx in enumerate(self._shuffle_cycle):
                if idx not in blocked:
                    self._shuffle_cycle[0], self._shuffle_cycle[i] = self._shuffle_cycle[i], self._shuffle_cycle[0]
                    break
        self._shuffle_pos = 0

    def _advance_shuffle(self) -> Type[BaseEffect]:
        if not self._shuffle_cycle or self._shuffle_pos >= len(self._shuffle_cycle):
            self._reset_shuffle_cycle(avoid_index=self._index)
        self._index = self._shuffle_cycle[self._shuffle_pos]
        self._shuffle_pos += 1
        self._shuffle_recent.append(self._index)
        return self._effects[self._index]

    def current(self) -> Type[BaseEffect]:
        return self._effects[self._index]

    def _step_to_enabled(self, direction: int) -> None:
        """Move ``_index`` to the next enabled effect in ``direction`` (+1/-1).

        No-op when nothing is enabled so the current effect stays put.
        """
        n = len(self._effects)
        for step in range(1, n + 1):
            cand = (self._index + direction * step) % n
            if self._is_enabled(cand):
                self._index = cand
                return

    def advance(self) -> Type[BaseEffect]:
        if self._mode == "random":
            return self._advance_shuffle()
        self._step_to_enabled(1)
        return self._effects[self._index]

    def go_prev(self) -> Type[BaseEffect]:
        self._step_to_enabled(-1)
        if self._mode == "random":
            self._shuffle_recent.append(self._index)
            self._reset_shuffle_cycle(avoid_index=self._index)
        return self._effects[self._index]

    def go_index(self, i: int) -> Type[BaseEffect]:
        self._index = i % len(self._effects)
        if self._mode == "random":
            self._shuffle_recent.append(self._index)
            self._reset_shuffle_cycle(avoid_index=self._index)
        return self._effects[self._index]

    def toggle_random(self) -> None:
        self._mode = "random" if self._mode != "random" else "sequential"
        if self._mode == "random":
            self._reset_shuffle_cycle(avoid_index=self._index)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def index(self) -> int:
        return self._index

    @property
    def effects(self) -> list[Type[BaseEffect]]:
        return self._effects

    @property
    def shortcut_effects(self) -> list[Type[BaseEffect]]:
        """Effects used by numeric hotkeys (exclude special-key effects)."""
        excluded = {"UnicornTears"}
        return [cls for cls in self._effects if cls.__name__ not in excluded]
