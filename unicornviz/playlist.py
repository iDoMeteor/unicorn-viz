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

        # Find starting index by NAME attribute (display name) or class name
        self._index = 0
        if start_name:
            for i, cls in enumerate(self._effects):
                if cls.NAME == start_name or cls.__name__ == start_name:
                    self._index = i
                    break

    def current(self) -> Type[BaseEffect]:
        return self._effects[self._index]

    def advance(self) -> Type[BaseEffect]:
        if self._mode == "random":
            self._index = random.randrange(len(self._effects))
        else:
            self._index = (self._index + 1) % len(self._effects)
        return self._effects[self._index]

    def go_prev(self) -> Type[BaseEffect]:
        self._index = (self._index - 1) % len(self._effects)
        return self._effects[self._index]

    def go_index(self, i: int) -> Type[BaseEffect]:
        self._index = i % len(self._effects)
        return self._effects[self._index]

    def toggle_random(self) -> None:
        self._mode = "random" if self._mode != "random" else "sequential"

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
        excluded = {"ANSIViewer", "UnicornTears"}
        return [cls for cls in self._effects if cls.__name__ not in excluded]
