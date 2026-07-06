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
        start_name: str = cfg.get("playlist", "start_effect", default="Audio Spectrum")

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
        # Numeric-hotkey slot pins: {slot_index (0-39): effect NAME or class
        # name}. Persisted globally by the app. See shortcut_effects().
        self._hotkey_pins: dict[int, str] = {}

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

    def _cls_enabled(self, cls: Type[BaseEffect]) -> bool:
        return cls.NAME not in self._disabled and cls.__name__ not in self._disabled

    def _is_enabled(self, idx: int) -> bool:
        return self._cls_enabled(self._effects[idx])

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

    def set_mode(self, mode: str) -> None:
        """Set the traversal mode ('random' or 'sequential')."""
        new_mode = "random" if str(mode).lower() == "random" else "sequential"
        if new_mode == self._mode:
            return
        self._mode = new_mode
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

    HOTKEY_SLOT_COUNT = 40  # naked/shift/ctrl/alt x (1-9, 0)

    def set_hotkey_pins(self, pins: 'dict[int, str] | None') -> None:
        """Set numeric-hotkey slot pins: {slot_index (0-39): effect name}."""
        clean: dict[int, str] = {}
        for k, v in (pins or {}).items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            name = str(v).strip()
            if name and 0 <= idx < self.HOTKEY_SLOT_COUNT:
                clean[idx] = name
        self._hotkey_pins = clean

    def hotkey_pins(self) -> dict[int, str]:
        """Return a copy of the current numeric-hotkey slot pins."""
        return dict(self._hotkey_pins)

    @property
    def shortcut_effects(self) -> list[Type[BaseEffect]]:
        """Effects reachable via numeric hotkeys, dynamically re-packed.

        Only *enabled* effects are included (excluding special-key effects),
        so the mapping automatically consolidates/expands as effects are
        enabled or disabled — recomputed fresh on every call, never cached.
        Pinned effects (see set_hotkey_pins) claim their slot when enabled;
        remaining slots fill with the rest of the enabled effects in catalog
        order. A pin whose effect is currently disabled, or whose slot index
        is beyond the enabled count, is simply not honoured until it fits.
        """
        excluded = {"UnicornTears"}
        eligible = [
            cls for cls in self._effects
            if cls.__name__ not in excluded and self._cls_enabled(cls)
        ]
        # Accept either the display name (NAME) or the class name as a pin
        # identifier, matching the convention used by the disabled-effects set.
        by_name: dict[str, Type[BaseEffect]] = {}
        for cls in eligible:
            by_name.setdefault(cls.NAME, cls)
            by_name.setdefault(cls.__name__, cls)
        n = len(eligible)

        slots: list[Type[BaseEffect] | None] = [None] * n
        used: set[Type[BaseEffect]] = set()
        for idx, name in sorted(self._hotkey_pins.items()):
            cls = by_name.get(name)
            if cls is None or cls in used or not (0 <= idx < n):
                continue
            slots[idx] = cls
            used.add(cls)

        remaining = iter(cls for cls in eligible if cls not in used)
        for i in range(n):
            if slots[i] is None:
                slots[i] = next(remaining)
        return slots  # type: ignore[return-value]
