from pathlib import Path

import pytest

from trailer_studio.models import Edit, Music, Recipe, Shot, identifier, inside


@pytest.mark.parametrize("value", ["../take", "a/b", "a\\b", "", "a b", "x" * 81, ".take"])
def test_take_ids_cannot_escape_directories(value):
    with pytest.raises(ValueError):
        identifier(value)


def test_workspace_rejects_absolute_and_relative_traversal(tmp_path):
    for path in [tmp_path.parent / "secret.txt", Path("../secret.txt")]:
        with pytest.raises(ValueError):
            inside(tmp_path, path)


def test_timeline_requires_exact_duration_and_frame_alignment():
    edit = Edit(name="cut", expected_duration=60, shots=[Shot(kind="card", duration=59)])
    with pytest.raises(ValueError, match="expected"):
        edit.validate_timeline(30)
    with pytest.raises(ValueError, match="aligned"):
        Edit(name="cut", shots=[Shot(kind="card", duration=0.25)]).validate_timeline(30)


def test_manifest_typos_and_ambiguous_steps_are_rejected():
    with pytest.raises(ValueError):
        Shot(take="one", duration=1, duraton=2)
    with pytest.raises(ValueError):
        Recipe(name="test", record=[{"hold": 1, "command": "capture_stop"}])
    with pytest.raises(ValueError):
        Music(path="music.wav", envelope=[(2, 1), (1, 0.5)])
