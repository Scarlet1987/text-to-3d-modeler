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


def _try_manufacturer_urls(hardware: str) -> GatheredData | None:
    """Try known manufacturer documentation URL patterns.

    Not a library of data — just knowledge of where manufacturers publish.
    If the URL exists, parse it. If not, move on.
    """
    # Manufacturer -> URL pattern templates for datasheets.
    # These are locations, not data. The data comes from the live document.
    # Add new manufacturers here as they're encountered.
    patterns = {
        "raspberry pi": [
            "https://datasheets.raspberrypi.com/{model}/{model}-datasheet.pdf",
            "https://pip-assets.raspberrypi.com/categories/944-raspberry-pi-compute-module-5/documents/RP-008180-DS-7-cm5-datasheet.pdf",
        ],
        "arduino": [
            "https://docs.arduino.cc/resources/datasheets/{model}-datasheet.pdf",
        ],
        "esp32": [
            "https://www.espressif.com/sites/default/files/documentation/{model}_datasheet_en.pdf",
        ],
        "teensy": [
            "https://www.pjrc.com/teensy/{model}.pdf",
        ],
        "jetson": [
            "https://developer.nvidia.com/downloads/{model}-datasheet",
        ],
    }
    hw = hardware.lower()
    for brand, urls in patterns.items():
        if brand in hw:
            model = hw.replace(brand, "").strip().replace(" ", "-")
            tried = []
            for template in urls:
                url = template.format(model=model)
                tried.append(url)
                try:
                    result = gather_from_url(url)
                    if result.dimensions:
                        return result
                except Exception:
                    continue
            # None of the URLs worked — report what was tried.
            data = GatheredData(query=hardware)
            data.notes.append(f"tried manufacturer URLs: {', '.join(tried[:2])} — none returned data")
            return data
    return None


def gather_from_url(url: str) -> GatheredData:
    """Gather data directly from a datasheet URL.

    Downloads the PDF, extracts text, pulls every dimension.
    No search, no guessing — straight from the manufacturer's document.
    """
    import re
    import tempfile
    from pathlib import Path as P

    import requests

    data = GatheredData(query=url)
    data.sources.append(url)

    # Download.
    resp = requests.get(url, timeout=60,
                        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/128.0"})
    resp.raise_for_status()

    tmp = P(tempfile.mkdtemp(prefix="datasheet_"))
    pdf_path = tmp / "datasheet.pdf"
    pdf_path.write_bytes(resp.content)

    try:
        # Try PyMuPDF for text extraction.
        try:
            import pymupdf
            doc = pymupdf.open(str(pdf_path))
        except ImportError:
            import fitz
            doc = fitz.open(str(pdf_path))

        full_text = ""
        for page in doc:
            text = page.get_text()
            full_text += text + "\n"
            # Look for mechanical/dimension sections.
            if "mechanical" in text.lower():
                data.notes.append(f"found mechanical section ({len(text)} chars)")

        # Extract all millimeter dimensions.
        seen = set()
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*mm\b", full_text):
            dim = m.group(0).strip()
            # Get surrounding context for labeling.
            start = max(0, m.start() - 60)
            ctx = full_text[start:m.end() + 20].replace("\n", " ").strip()
            key = dim.lower()
            if key not in seen:
                seen.add(key)
                data.dimensions.append(f"{dim} — {ctx[:80]}")

        # Also catch "55 x 40" style patterns.
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:mm)?", full_text):
            dim = f"{m.group(1)}x{m.group(2)}mm"
            if dim.lower() not in seen:
                seen.add(dim.lower())
                data.dimensions.append(dim)

        data.notes.append(f"extracted from {len(doc)}-page PDF")
        doc.close()
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    # Detect hardware from URL or content.
    if "cm5" in url.lower():
        data.hardware = "raspberry pi cm5"
    elif "cm4" in url.lower():
        data.hardware = "raspberry pi cm4"

    return data


def gather(query: str, workdir: Path | None = None) -> GatheredData:
    """Gather all available data for a part or hardware.

    1. Detect named hardware, search for its datasheets.
    2. Find and download manufacturer diagrams.
    3. Extract dimensions from diagrams (OCR + text).
    4. Collect everything for user review.
    """
    data = GatheredData(query=query)
    data.hardware = _extract_hardware_terms(query)

    # Step 1: Manufacturer URLs first — direct fetch, never blocked.
    # If we know the hardware, go straight to the source.
    if data.hardware:
        mfr_data = _try_manufacturer_urls(data.hardware)
        if mfr_data:
            # Always merge notes so the user sees what was tried.
            data.notes.extend(mfr_data.notes)
            if mfr_data.dimensions or mfr_data.diagrams:
                for d in mfr_data.dimensions:
                    if d not in data.dimensions:
                        data.dimensions.append(d)
                for s in mfr_data.sources:
                    if s not in data.sources:
                        data.sources.append(s)
                data.diagrams.extend(mfr_data.diagrams)
            # Got manufacturer data — web search is now just a supplement.
    search_terms = data.hardware if data.hardware else query
    search_ok = bool(data.dimensions)
    # Step 1b: Web search supplements manufacturer data (best effort).
    # Only runs if manufacturer fetch didn't already succeed.
    # DuckDuckGo intermittently blocks automated searches, so this is
    # opportunistic, not required.
    if not search_ok:
        for suffix in ["datasheet dimensions", "mechanical drawing specifications"]:
            try:
                r = ground(f"{search_terms} {suffix}")
                if r.dimensions or r.snippets:
                    search_ok = True
                for d in r.dimensions:
                    if d not in data.dimensions:
                        data.dimensions.append(d)
                for s in r.sources:
                    if s not in data.sources:
                        data.sources.append(s)
                for snip in r.snippets[:3]:
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
