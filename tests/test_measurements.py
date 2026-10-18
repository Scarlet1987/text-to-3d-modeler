"""Tests for the measurement gate: no dimension altered without reference backing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gates.measurements import check_measurements, extract_dimensions, is_backed

REFS = ["40mm", "20mm", "5mm", "6mm"]

GOOD_SCRIPT = '''
import cadquery as cq
result = cq.Workplane("XY").box(40, 20, 5).faces(">Z").hole(6)
'''

SNEAKY_SCRIPT = '''
import cadquery as cq
result = cq.Workplane("XY").box(40, 20, 99).faces(">Z").hole(6)
'''

TOLERANT_SCRIPT = '''
import cadquery as cq
result = cq.Workplane("XY").box(40, 20, 5.1).faces(">Z").hole(6)
'''


def test_first_draft_all_backed_passes():
    c = check_measurements(GOOD_SCRIPT, None, REFS)
    assert c.passed, c.notes


def test_sneaky_revision_rejected():
    c = check_measurements(SNEAKY_SCRIPT, GOOD_SCRIPT, REFS)
    assert not c.passed
    assert 99.0 in c.unbacked


def test_tolerance_allows_small_changes():
    c = check_measurements(TOLERANT_SCRIPT, GOOD_SCRIPT, REFS)
    assert c.passed, c.notes


def test_extract_dimensions_ignores_non_dims():
    dims = extract_dimensions("x = 0\nfor i in range(10):\n    y = box(40, 20, 5)")
    assert 40.0 in dims and 20.0 in dims and 5.0 in dims
    assert 0.0 not in dims  # below MIN_DIM
    assert 10.0 in dims  # range(10) — acceptable noise, gate uses backing check


def test_is_backed_with_units():
    assert is_backed(40.0, ["40mm"])
    assert is_backed(5.0, ["5 mm"])
    assert not is_backed(99.0, ["40mm"])
