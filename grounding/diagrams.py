"""Disciplined diagram grounding.

Not random images — targeted technical references, validated before use.

Rules:
1. Text grounding runs first. Diagrams are fetched ONLY if text came up
   short on measurements. Don't pay the download+OCR cost for nothing.
2. Source priority: manufacturer datasheets and official docs outrank
   random blog images. A wrong diagram is worse than no diagram.
3. Relevance check: the OCR text must mention the part (or its key terms).
   An irrelevant diagram's measurements never enter the reference set.
4. Cap at 2 diagrams. More is noise, not signal.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from grounding.retrieve import DIMENSION_RE, HEADERS

# Domains that publish authoritative technical data.
TRUSTED_DOMAINS = (
    "raspberrypi.com",
    "pip.raspberrypi.com",
    "datasheet",
    "mouser.com",
    "digikey.com",
    "ti.com",
    "analog.com",
    "nxp.com",
    "st.com",
    "infineon.com",
    "wikipedia.org",
    "githubusercontent.com",  # CAD repos with drawings
)


def _source_score(url: str) -> int:
    url_l = url.lower()
    if any(d in url_l for d in TRUSTED_DOMAINS):
        return 2
    if url_l.endswith(".pdf"):
        return 1  # datasheets, even from mirrors
    return 0


@dataclass
class DiagramData:
    source_url: str
    measurements: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    trusted: bool = False


def _find_candidates(query: str, max_candidates: int = 6) -> list[str]:
    """Find candidate diagram/datasheet URLs, ranked by source trust."""
    found: list[str] = []
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": f"{query} datasheet OR technical drawing dimensions"},
            headers=HEADERS, timeout=30,
        )
        for m in re.finditer(r'result__a[^>]*href="([^"]+)"', resp.text):
            url = m.group(1)
            if url.startswith("http") and url not in found:
                found.append(url)
            if len(found) >= max_candidates:
                break
    except Exception:
        pass
    # Most trusted first.
    found.sort(key=_source_score, reverse=True)
    return found


def _extract_keywords(text: str, max_keywords: int = 20) -> list[str]:
    """Pull domain-relevant keywords/phrases from OCR'd diagram text."""
    stopwords = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
        "is", "are", "be", "by", "as", "at", "from", "this", "that", "it",
        "all", "dimensions", "unless", "otherwise", "specified", "tolerance",
        "drawing", "sheet", "scale", "title", "date", "drawn", "checked",
    }
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-/]{2,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in stopwords and not w.isdigit():
            freq[w] = freq.get(w, 0) + 1
    # Phrases: consecutive capitalized words in the original text (e.g. "Mounting Hole")
    phrases = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text)
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    keywords = [w for w, _ in ranked[:max_keywords]]
    for p in dict.fromkeys(phrases):
        if p.lower() not in keywords:
            keywords.append(p)
        if len(keywords) >= max_keywords + 5:
            break
    return keywords


def _download(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        if len(r.content) < 2048:
            return False
        dest.write_bytes(r.content)
        return True
    except Exception:
        return False


def _ocr(path: Path) -> str:
    try:
        proc = subprocess.run(
            ["tesseract", str(path), "stdout", "--psm", "6"],
            capture_output=True, text=True, timeout=120,
        )
        return proc.stdout if proc.returncode == 0 else ""
    except Exception:
        return ""


def _is_relevant(text: str, query_terms: list[str]) -> bool:
    """The diagram must mention the part. Otherwise its numbers are noise."""
    text_l = text.lower()
    hits = sum(1 for t in query_terms if t in text_l)
    return hits >= max(1, len(query_terms) // 2)


def parse_diagrams(
    query: str,
    workdir: Path,
    text_measurements: list[str],
    max_diagrams: int = 2,
) -> list[DiagramData]:
    """Fetch and parse diagrams — but only if text grounding came up short,
    only from the most trusted sources, and only if relevant.

    Returns validated DiagramData. Empty list means: text was enough,
    or nothing trustworthy was found. Both are fine.
    """
    # Discipline rule 1: don't pay for diagrams when text already delivered.
    if len(text_measurements) >= 5:
        return []

    query_terms = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
    results: list[DiagramData] = []
    for i, url in enumerate(_find_candidates(query)):
        if len(results) >= max_diagrams:
            break
        # Skip non-image, non-PDF URLs (can't OCR a webpage usefully here).
        if not re.search(r"\.(pdf|png|jpe?g|webp)(\?|$)", url, re.I):
            # Allow datasheet PDFs discovered via redirect URLs too.
            if "datasheet" not in url.lower() and ".pdf" not in url.lower():
                continue
        dest = workdir / f"ref_{i}.bin"
        if not _download(url, dest):
            continue
        time.sleep(1)
        text = _ocr(dest)
        dest.unlink(missing_ok=True)  # don't hoard downloads
        if not text.strip():
            continue
        # Discipline rule 3: relevance check before trusting any number.
        if not _is_relevant(text, query_terms):
            continue
        measurements = list(dict.fromkeys(
            d.strip() for d in DIMENSION_RE.findall(text) if d.strip()
        ))
        keywords = _extract_keywords(text)
        trusted = _source_score(url) >= 2
        results.append(DiagramData(url, measurements, keywords, trusted))
    return results
