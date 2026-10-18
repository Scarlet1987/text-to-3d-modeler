"""Known boards database: exact datasheet dimensions for common hardware.

When the user names a board, the parser matches it here first —
no web search, no guessing, just the manufacturer's numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

from grounding.retrieve import GroundingResult

KNOWN_BOARDS = {
    "raspberry pi cm5": {
        "full_name": "Raspberry Pi Compute Module 5",
        "footprint_mm": {"length": 55, "width": 40, "height": 4.7},
        "mounting_holes": {
            "count": 4, "thread": "M2.5", "corner_inset_mm": 3.5,
            "positions_from_lower_left_mm": [[3.5, 3.5], [51.5, 3.5], [3.5, 36.5], [51.5, 36.5]],
            "drill_mm": 2.7, "pad_mm": 5.8,
        },
        "pcb_thickness_mm": 1.24,
        "soc_height_mm": 2.2,
        "stacking_height_mm": {"low": 1.5, "high": 4.0},
        "source": "Raspberry Pi CM5 datasheet",
    },
    "raspberry pi cm4": {
        "full_name": "Raspberry Pi Compute Module 4",
        "footprint_mm": {"length": 55, "width": 40, "height": 4.7},
        "mounting_holes": {
            "count": 4, "thread": "M2.5", "corner_inset_mm": 3.5,
            "positions_from_lower_left_mm": [[3.5, 3.5], [51.5, 3.5], [3.5, 36.5], [51.5, 36.5]],
            "drill_mm": 2.7, "pad_mm": 5.8,
        },
        "pcb_thickness_mm": 1.24,
        "source": "Raspberry Pi CM4 datasheet",
    },
    "raspberry pi 5": {
        "full_name": "Raspberry Pi 5",
        "footprint_mm": {"length": 85, "width": 56},
        "mounting_holes": {
            "count": 4, "thread": "M2.5",
            "positions_from_lower_left_mm": [[3.5, 3.5], [81.5, 3.5], [3.5, 52.5], [81.5, 52.5]],
            "corner_inset_mm": 3.5,
        },
        "source": "Raspberry Pi 5 specifications",
    },
}


def match_known_board(prompt: str) -> GroundingResult | None:
    """If the prompt names a known board, return its exact dimensions."""
    prompt_lower = prompt.lower()
    for key, specs in KNOWN_BOARDS.items():
        if key in prompt_lower:
            result = GroundingResult(query=prompt)
            fp = specs["footprint_mm"]
            dims = [f"{fp['length']}x{fp['width']}mm footprint"]
            if "height" in fp:
                dims.append(f"{fp['height']}mm height")
            mh = specs.get("mounting_holes", {})
            if mh:
                dims.append(f"{mh['count']}x {mh['thread']} mounting holes, {mh['corner_inset_mm']}mm inset")
                for pos in mh.get("positions_from_lower_left_mm", []):
                    dims.append(f"hole at {pos[0]}x{pos[1]}mm from corner")
            if "pcb_thickness_mm" in specs:
                dims.append(f"{specs['pcb_thickness_mm']}mm PCB thickness")
            if "soc_height_mm" in specs:
                dims.append(f"{specs['soc_height_mm']}mm SoC height")
            result.dimensions = dims
            result.sources = [f"known-boards:{specs['source']}"]
            result.snippets = [f"Exact datasheet specs for {specs['full_name']}: {json.dumps(specs)}"]
            return result
    return None


def save_known_boards(path: Path | None = None) -> None:
    """Persist the database to references/known-boards.json for inspection."""
    path = path or Path(__file__).resolve().parent.parent / "references" / "known-boards.json"
    path.write_text(json.dumps(KNOWN_BOARDS, indent=2))
