"""Measurement check gate.

Rule: before the agent alters any measurement during iteration,
it must check the new value against grounded reference data.
Measurements come from reality, not from making the code compile.

This gate runs on every script revision. A revision that changes a
dimension without reference backing is rejected and sent back.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

# Matches things like 42, 3.5, 0.5 in code — candidate dimensions.
# We filter to plausible part sizes (0.1mm to 2000mm) to skip
# indices, counts, and other non-dimensional numbers.
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
MIN_DIM = 0.1
MAX_DIM = 2000.0
# Tolerance: a generated dimension within this fraction of a reference
# dimension counts as "backed by reference".
TOLERANCE = 0.05


@dataclass
class MeasurementCheck:
    passed: bool
    changed: list[float] = field(default_factory=list)      # dims changed vs previous
    unbacked: list[float] = field(default_factory=list)     # changed dims with no reference backing
    notes: list[str] = field(default_factory=list)


def extract_dimensions(script: str) -> list[float]:
    """Pull plausible dimensional literals out of a CadQuery script."""
    dims: list[float] = []
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return dims
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            v = float(node.value)
            if MIN_DIM <= v <= MAX_DIM:
                dims.append(v)
    return sorted(set(dims))


def _parse_ref_dimension(text: str) -> list[float]:
    """Extract numeric values from a reference dimension string like '42mm' or '10 x 20'."""
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]


def is_backed(value: float, reference_dims: list[str]) -> bool:
    """Is this dimension within tolerance of any grounded reference dimension?"""
    for ref in reference_dims:
        for ref_val in _parse_ref_dimension(ref):
            if ref_val == 0:
                continue
            if abs(value - ref_val) / ref_val <= TOLERANCE:
                return True
    return False


def check_measurements(
    new_script: str,
    previous_script: str | None,
    reference_dims: list[str],
) -> MeasurementCheck:
    """Compare a revised script's dimensions against the previous version
    and the grounded reference data.

    - First revision (no previous): all dims must be reference-backed,
      or flagged for user review.
    - Later revisions: any *changed* dim must be reference-backed.
      Unchanged dims pass through.
    """
    notes: list[str] = []
    new_dims = set(extract_dimensions(new_script))
    old_dims = set(extract_dimensions(previous_script)) if previous_script else set()
    changed = sorted(new_dims - old_dims)

    unbacked: list[float] = []
    if not previous_script:
        # First pass: every dimension should come from reference data.
        for d in sorted(new_dims):
            if not is_backed(d, reference_dims):
                unbacked.append(d)
        if unbacked:
            notes.append(
                f"First-draft dimensions not found in reference data: {unbacked}. "
                "Agent must cite a source or ask the user before keeping them."
            )
    else:
        for d in changed:
            if not is_backed(d, reference_dims):
                unbacked.append(d)
        if unbacked:
            notes.append(
                f"Revised dimensions with no reference backing: {unbacked}. "
                "Check the measurement against grounded data before altering it."
            )

    return MeasurementCheck(
        passed=not unbacked,
        changed=changed,
        unbacked=unbacked,
        notes=notes,
    )
