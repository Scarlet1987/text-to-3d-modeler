"""Data gathering phase: scrape the web for manufacturer diagrams and specs.

This runs BEFORE any build. Its only job is to find and collect data —
datasheets, mechanical drawings, dimensions — and present them for review.
Nothing gets cut until the data is gathered and verified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from grounding.diagrams import parse_diagrams
from grounding.retrieve import _extract_hardware_terms, ground


@dataclass
class GatheredData:
    query: str
    hardware: str = ""
    dimensions: list[str] = field(default_factory=list)
    diagrams: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "hardware": self.hardware,
            "dimensions": self.dimensions,
            "diagrams": self.diagrams,
            "sources": self.sources,
            "notes": self.notes,
        }


def gather(query: str, workdir: Path | None = None) -> GatheredData:
    """Gather all available data for a part or hardware.

    1. Detect named hardware, search for its datasheets.
    2. Find and download manufacturer diagrams.
    3. Extract dimensions from diagrams (OCR + text).
    4. Collect everything for user review.
    """
    data = GatheredData(query=query)
    data.hardware = _extract_hardware_terms(query)

    # Step 1: Web search for specs and dimensions.
    search_terms = data.hardware if data.hardware else query
    for suffix in ["datasheet dimensions", "mechanical drawing specifications"]:
        try:
            r = ground(f"{search_terms} {suffix}")
            for d in r.dimensions:
                if d not in data.dimensions:
                    data.dimensions.append(d)
            for s in r.sources:
                if s not in data.sources:
                    data.sources.append(s)
            for snip in r.snippets[:3]:
                # Pull dimension-like strings from snippets.
                for m in re.finditer(r"\d+(?:\.\d+)?\s*mm", snip):
                    dim = m.group(0)
                    if dim not in data.dimensions:
                        data.dimensions.append(dim)
        except Exception as e:
            data.notes.append(f"search failed for '{suffix}': {e}")

    # Step 2: Manufacturer diagrams — download and parse.
    if workdir:
        try:
            for dd in parse_diagrams(query, workdir, data.dimensions):
                entry = {
                    "url": dd.url if hasattr(dd, "url") else "unknown",
                    "measurements": dd.measurements,
                    "keywords": dd.keywords[:10] if hasattr(dd, "keywords") else [],
                }
                data.diagrams.append(entry)
                for m in dd.measurements:
                    if m not in data.dimensions:
                        data.dimensions.append(m)
        except Exception as e:
            data.notes.append(f"diagram parsing failed: {e}")

    if not data.dimensions and not data.diagrams:
        data.notes.append(
            "No data found. Try a more specific hardware name "
            "(e.g. 'raspberry pi cm5' instead of 'handheld')."
        )

    return data
