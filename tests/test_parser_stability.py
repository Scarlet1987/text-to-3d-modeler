"""Stability test: regex datasheet dimension extraction.

Regression test for the parser. The 1.7B model comparison was removed
2026-10-19 after it failed decisively (0/9 hits, 0% consistency) —
regex is the parser. This test guards against regressions.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

# Ground truth: the mechanical dimensions that actually matter for the CM5.
# From the official datasheet, verified by hand.
EXPECTED = {
    "55": "footprint length",
    "40": "footprint width",
    "4.7": "module height",
    "3.5": "mounting hole inset",
    "2.7": "mounting hole drill",
    "1.24": "PCB thickness",
    "2.2": "SoC height",
    "1.5": "stacking height (low)",
    "4.0": "stacking height (high)",
}


def regex_extract(text: str) -> list[str]:
    """Current approach: regex for mm dimensions."""
    seen = set()
    dims = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*mm\b", text):
        dim = m.group(1)
        if dim not in seen:
            seen.add(dim)
            dims.append(dim)
    return dims


def score(extracted: list[str]) -> dict:
    """Score extraction against ground truth."""
    extracted_set = set(extracted)
    expected_set = set(EXPECTED.keys())
    hits = extracted_set & expected_set
    noise = extracted_set - expected_set
    return {
        "total": len(extracted),
        "hits": len(hits),
        "hit_rate": len(hits) / len(expected_set) if expected_set else 0,
        "noise": len(noise),
        "noise_rate": len(noise) / len(extracted) if extracted else 0,
        "missing": list(expected_set - extracted_set),
    }


def main():
    # Load datasheet text.
    pdf_path = Path.home() / "workspace" / "tmp" / "cm5test" / "cm5-datasheet.pdf"
    if not pdf_path.exists():
        print("datasheet not found, downloading...")
        import requests
        url = "https://datasheets.raspberrypi.com/cm5/cm5-datasheet.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(requests.get(
            url, timeout=120,
            headers={"User-Agent": "Mozilla/5.0"},
        ).content)

    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
    except ImportError:
        import fitz
        doc = fitz.open(str(pdf_path))
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    print(f"datasheet: {len(text)} chars\n")

    # Regex parser (the parser — 1.7B removed 2026-10-19 after failing).
    print("=== REGEX PARSER ===")
    t0 = time.time()
    regex_dims = regex_extract(text)
    t1 = time.time()
    r_score = score(regex_dims)
    print(f"  time: {t1-t0:.1f}s | total: {r_score['total']} | "
          f"hits: {r_score['hits']}/{len(EXPECTED)} ({r_score['hit_rate']:.0%}) | "
          f"noise: {r_score['noise']} ({r_score['noise_rate']:.0%})")
    print(f"  missing: {r_score['missing']}")

    print("\n=== VERDICT ===")
    if r_score["hit_rate"] >= 0.8:
        print(f"PASS — parser holds at {r_score['hit_rate']:.0%} hit rate.")
    else:
        print(f"FAIL — parser dropped below 80% ({r_score['hit_rate']:.0%}).")
    return r_score


if __name__ == "__main__":
    main()
