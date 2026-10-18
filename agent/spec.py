"""Spec builder: turns prompt + answers into a verified build spec.

The spec is the contract between the info-gathering side and the CAD writer.
The writer NEVER sees unverified dimensions — only what's in the spec.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Dimension:
    value_mm: float
    label: str = ""
    source: str = ""  # where this number came from
    verified: bool = False


@dataclass
class BuildSpec:
    part_name: str = ""
    dimensions: list[Dimension] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw_prompt: str = ""

    def to_dict(self) -> dict:
        return {
            "part_name": self.part_name,
            "dimensions": [
                {"value_mm": d.value_mm, "label": d.label,
                 "source": d.source, "verified": d.verified}
                for d in self.dimensions
            ],
            "notes": self.notes,
        }

    def verified_dimensions(self) -> list[Dimension]:
        return [d for d in self.dimensions if d.verified]

    def prompt_block(self) -> str:
        """Render verified spec as context for the CAD writer.

        ONLY verified dimensions appear here. Unverified ones don't exist
        as far as the writer is concerned.
        """
        lines = [f"Part: {self.part_name}", "", "VERIFIED DIMENSIONS (use exactly):"]
        for d in self.verified_dimensions():
            lines.append(f"  - {d.label}: {d.value_mm}mm (source: {d.source})")
        if self.notes:
            lines.append("")
            lines.append("Notes:")
            for n in self.notes:
                lines.append(f"  - {n}")
        return "\n".join(lines)


# Matches "40mm", "40 x 20", "M2.5", etc. in user text.
DIM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*mm\b|\bM(\d+(?:\.\d+)?)\b", re.IGNORECASE
)


def build_spec(prompt: str, answers: list[str], grounded_dims: list[str]) -> BuildSpec:
    """Build a spec from prompt + user answers + grounded dimensions.

    Dimensions from the user's own text are treated as authoritative (they
    measured it or specified it). Grounded dimensions provide verification.
    A dimension is verified if it appears in grounded data or user answers
    with an explicit measurement.
    """
    spec = BuildSpec(raw_prompt=prompt)
    spec.part_name = _extract_part_name(prompt)

    # Collect all candidate dimensions with their sources.
    candidates: dict[float, Dimension] = {}

    # From user answers and prompt: authoritative.
    for text, source in [(prompt, "user prompt")] + [(a, "user answer") for a in answers]:
        for m in DIM_RE.finditer(text):
            val = float(m.group(1) or m.group(2))
            label = _label_for(val, text)
            if val not in candidates:
                candidates[val] = Dimension(value_mm=val, label=label, source=source, verified=True)
            # User-stated dimensions are verified by definition — they said it.

    # From grounded data: verify against candidates, add new ones.
    for g in grounded_dims:
        m = DIM_RE.search(g)
        if m:
            val = float(m.group(1) or m.group(2))
            if val in candidates:
                candidates[val].verified = True
                if not candidates[val].source.startswith("user"):
                    candidates[val].source = f"verified: {g[:60]}"
            else:
                # Grounded but not user-stated — include as verified reference.
                candidates[val] = Dimension(
                    value_mm=val, label=_label_for(val, g),
                    source=f"datasheet: {g[:60]}", verified=True,
                )

    spec.dimensions = sorted(candidates.values(), key=lambda d: d.value_mm)
    return spec


def _extract_part_name(prompt: str) -> str:
    # "make a mounting tray for raspberry pi cm5" -> "mounting tray"
    m = re.search(r"make an? (.+?)(?: for |:|$)", prompt, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return prompt[:50]


def _label_for(value: float, context: str) -> str:
    ctx = context.lower()
    # Simple heuristics based on surrounding words.
    if "thick" in ctx:
        return "thickness"
    if "hole" in ctx or "diameter" in ctx:
        return "hole diameter"
    if "wall" in ctx:
        return "wall height"
    if "inset" in ctx:
        return "inset"
    return "dimension"
