"""Tests for ShotSpec validation and serialization."""

import pytest
from qc.spec import ShotExpectation, ShotSpec


def test_shot_spec_defaults():
    spec = ShotSpec(shot_id="S01")
    assert spec.shot_id == "S01"
    assert spec.expect.dogs == 0
    assert spec.expect.faces_visible is False
    assert spec.min_motion == 0.15
    assert spec.max_motion == 2.5
    assert spec.allow_light_change is False


def test_shot_spec_from_file(synthetic_spec_factory):
    path = synthetic_spec_factory(shot_id="S03", dogs=1, bowls=1)
    spec = ShotSpec.from_file(path)
    assert spec.shot_id == "S03"
    assert spec.expect.dogs == 1
    assert spec.expect.bowls == 1
    assert spec.caption.y_ratio == 0.20


def test_shot_spec_missing_file():
    with pytest.raises(FileNotFoundError):
        ShotSpec.from_file("non_existent_spec_file.json")
