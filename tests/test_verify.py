"""Tests for post-build verification: the STEP must measure right."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cadquery as cq
from gates.verify import verify_step


def _make_step(path: Path, x: float, y: float, z: float) -> Path:
    cq.exporters.export(cq.Workplane("XY").box(x, y, z), str(path))
    return path


def test_correct_part_passes(tmp_path):
    p = _make_step(tmp_path / "good.step", 40, 20, 5)
    v = verify_step(p, ["40mm", "20mm", "5mm"])
    assert v.passed, v.failures
    assert v.measured["x"] == 40.0


def test_wrong_part_fails(tmp_path):
    p = _make_step(tmp_path / "bad.step", 40, 20, 50)
    v = verify_step(p, ["40mm", "20mm", "5mm"])
    assert not v.passed
    assert v.failures


def test_missing_file_fails(tmp_path):
    v = verify_step(tmp_path / "nope.step", ["40mm"])
    assert not v.passed
