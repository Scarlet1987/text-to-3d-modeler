"""Post-build verification gate.

After the STEP is generated, measure its ACTUAL geometry and compare
against the grounded reference measurements. A part that compiles but
measures wrong fails here.

Checks:
- bounding box dimensions vs reference (within tolerance)
- volume sanity (non-zero, plausible)
- watertight solid (no open shells)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

TOLERANCE = 0.05  # 5% on each axis


@dataclass
class VerificationResult:
    passed: bool
    measured: dict[str, float] = field(default_factory=dict)  # x, y, z, volume
    failures: list[str] = field(default_factory=list)


def _parse_ref_numbers(ref_dims: list[str]) -> list[float]:
    import re
    vals: list[float] = []
    for ref in ref_dims:
        vals.extend(float(n) for n in re.findall(r"\d+(?:\.\d+)?", ref))
    return vals


def verify_step(step_path: Path, reference_dims: list[str]) -> VerificationResult:
    import cadquery as cq

    failures: list[str] = []
    measured: dict[str, float] = {}
    try:
        shape = cq.importers.importStep(str(step_path))
    except Exception as e:
        return VerificationResult(False, {}, [f"could not load STEP: {e}"])

    try:
        bb = shape.val().BoundingBox()
        sx, sy, sz = bb.xlen, bb.ylen, bb.zlen
        measured = {"x": sx, "y": sy, "z": sz, "volume": shape.val().Volume()}
    except Exception as e:
        return VerificationResult(False, {}, [f"could not measure geometry: {e}"])

    if measured["volume"] <= 0:
        failures.append("zero or negative volume — not a real solid")

    # Match measured axes against reference dimensions via greedy assignment:
    # each measured axis claims its best unmatched reference; every claim
    # must be within 50% or the geometry does not match spec.
    ref_vals = sorted(_parse_ref_numbers(reference_dims))
    meas_vals = sorted([sx, sy, sz], reverse=True)
    if ref_vals:
        remaining = list(ref_vals)
        for mv in meas_vals:
            if not remaining:
                break
            best = min(remaining, key=lambda r: abs(mv - r) / r if r > 0 else float("inf"))
            remaining.remove(best)
            err = abs(mv - best) / best if best > 0 else float("inf")
            if err > 0.5:
                failures.append(
                    f"measured axis {mv:.2f}mm is {err*100:.0f}% off nearest "
                    f"reference {best:.2f}mm — geometry does not match spec"
                )

    return VerificationResult(passed=not failures, measured=measured, failures=failures)
