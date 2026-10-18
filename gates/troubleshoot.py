"""Troubleshooting: categorized errors with specific recovery.

Not all failures are the same. A syntax error needs a different fix
than a geometry kernel crash. This module classifies failures so the
loop (and the user) responds correctly instead of retrying blindly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureKind(Enum):
    SYNTAX = "syntax"              # Python won't parse — fix the code
    API_MISUSE = "api_misuse"      # wrong CadQuery call — fix the API usage
    GEOMETRY = "geometry"          # OCC kernel rejected the shape — rethink the geometry
    KERNEL_CRASH = "kernel_crash"  # segfault — the shape broke the kernel, simplify
    TIMEOUT = "timeout"            # took too long — simplify or split the part
    MEASUREMENT = "measurement"    # gate rejected dims — check against reference
    VERIFICATION = "verification"  # STEP measured wrong — geometry doesn't match spec
    GROUNDING = "grounding"        # no reference data — user must provide dims
    RESOURCE = "resource"          # out of RAM/disk/VRAM — free resources, don't retry
    UNKNOWN = "unknown"


@dataclass
class Diagnosis:
    kind: FailureKind
    advice: str
    retryable: bool


def diagnose(log: str, returncode: int) -> Diagnosis:
    l = log.lower()
    if returncode == -11 or "segmentation fault" in l or "segfault" in l:
        return Diagnosis(
            FailureKind.KERNEL_CRASH,
            "The geometry kernel crashed (segfault). The shape is too complex or "
            "degenerate for OCC. Simplify: fewer operations, avoid zero-thickness "
            "features, fillet last.",
            retryable=True,
        )
    if "syntaxerror" in l:
        return Diagnosis(
            FailureKind.SYNTAX,
            "Python syntax error. Fix the code structure before anything else.",
            retryable=True,
        )
    if "timeout" in l or "timed out" in l:
        return Diagnosis(
            FailureKind.TIMEOUT,
            "Script timed out. Simplify the geometry or split into smaller operations.",
            retryable=True,
        )
    if any(k in l for k in ("attributeerror", "typeerror: ", "unexpected keyword")):
        return Diagnosis(
            FailureKind.API_MISUSE,
            "CadQuery API misuse. Check the method name and arguments against "
            "the CadQuery docs.",
            retryable=True,
        )
    if any(k in l for k in ("bop", "boolean", "fusion failed", "cut failed", "occ")):
        return Diagnosis(
            FailureKind.GEOMETRY,
            "Geometry operation failed in the OCC kernel. The shapes may not "
            "intersect cleanly, or a boolean produced a non-manifold result. "
            "Check face selections and operation order.",
            retryable=True,
        )
    if "measurement check failed" in l:
        return Diagnosis(
            FailureKind.MEASUREMENT,
            "A dimension has no reference backing. Cite a source or ask the user — "
            "do not invent numbers.",
            retryable=True,
        )
    if "verification failed" in l:
        return Diagnosis(
            FailureKind.VERIFICATION,
            "The STEP measured wrong against spec. The geometry needs rework, "
            "not the measurements.",
            retryable=True,
        )
    if "no grounding" in l:
        return Diagnosis(
            FailureKind.GROUNDING,
            "No reference measurements found. The user must provide dimensions.",
            retryable=False,
        )
    if "preflight failed" in l:
        return Diagnosis(
            FailureKind.RESOURCE,
            "Insufficient RAM/disk/VRAM. Free resources before retrying — "
            "retrying blind will fail the same way.",
            retryable=False,
        )
    return Diagnosis(
        FailureKind.UNKNOWN,
        "Unclassified failure. Read the log carefully before retrying.",
        retryable=True,
    )
