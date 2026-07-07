"""Regression: every rotation effect must carry at least one mood tag.

Mood tags (chill/groovy/energetic/intense/hard) are what the Auto VJ's
scene-based selection filters on. A rotation effect with no mood tag is
invisible to every mood-scoped scene — the class of bug that left the director
"stuck in the psychedelics". This guards that a newly added effect can't ship
without a mood.

See docs/planning/vj-mood-tag-rollout.md for the authoritative assignments.
"""
from __future__ import annotations

from unicornviz.effects.registry import get_effects

MOODS = {'chill', 'groovy', 'energetic', 'intense', 'hard'}


def test_every_rotation_effect_has_a_mood_tag() -> None:
    missing = []
    for cls in get_effects():
        # Manual-only effects (AUTO_ROTATE=False, e.g. Video Player) are never
        # VJ-selected, so a mood tag would be meaningless for them.
        if getattr(cls, 'AUTO_ROTATE', True) is False:
            continue
        tags = {str(t).lower() for t in getattr(cls, 'TAGS', [])}
        if not (tags & MOODS):
            missing.append(cls.NAME)
    assert not missing, (
        'Rotation effects with no mood tag (invisible to the VJ): '
        + ', '.join(sorted(missing))
    )


def test_mood_vocabulary_is_covered() -> None:
    # Each mood should be carried by at least one effect, so no scene that
    # requests it comes up empty (the fallback would fire otherwise).
    seen: set[str] = set()
    for cls in get_effects():
        seen |= {str(t).lower() for t in getattr(cls, 'TAGS', [])} & MOODS
    assert MOODS <= seen, f'Moods with zero effects: {sorted(MOODS - seen)}'
