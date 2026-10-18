"""Diagram parsing: download technical diagrams/schematics, OCR them,
extract measurements and keywords/phrases for accuracy.

Runs BEFORE the build (to ground generation) and the extracted data
is kept for the AFTER-build verification gate.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import requests

from grounding.retrieve import DIMENSION_RE, HEADERS

# Stopwords for keyword extraction — keep domain terms, drop glue words.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "be", "by", "as", "at", "from", "this", "that", "it",
}


@dataclass
class DiagramData:
    source_url: str
    measurements: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    raw_text: str = ""


def _find_diagram_urls(query: str, max_images: int = 4) -> list[str]:
    """Find direct image URLs of diagrams/schematics via DDG image search."""
    urls: list[str] = []
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query + " diagram schematic technical drawing", "iax": "images", "ia": "images"},
            headers=HEADERS, timeout=30,
        )
        # DDG html endpoint returns web results; image URLs often appear as direct links
        for m in re.finditer(r'"image":"([^"]+)"', resp.text):
            u = m.group(1)
            if u.startswith("http"):
                urls.append(u)
            if len(urls) >= max_images:
                break
    except Exception:
        pass
    # Fallback: pull image URLs from regular results pages
    if not urls:
        try:
            resp = requests.get(
                "https://duckduckgo.com/",
                params={"q": query + " technical drawing dimensions", "iax": "images", "ia": "images"},
                headers=HEADERS, timeout=30,
            )
            for m in re.finditer(r'https?://[^"\s<>]+\.(?:png|jpe?g|svg|webp|gif)', resp.text, re.I):
                urls.append(m.group(0))
                if len(urls) >= max_images:
                    break
        except Exception:
            pass
    return urls[:max_images]


def _download(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        if len(r.content) < 1024:
            return False
        dest.write_bytes(r.content)
        return True
    except Exception:
        return False


def _ocr(image_path: Path) -> str:
    try:
        proc = subprocess.run(
            ["tesseract", str(image_path), "stdout", "--psm", "6"],
            capture_output=True, text=True, timeout=120,
        )
        return proc.stdout if proc.returncode == 0 else ""
    except Exception:
        return ""


def _extract_keywords(text: str, max_keywords: int = 30) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-/]{2,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in _STOPWORDS and not w.isdigit():
            freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:max_keywords]]


def parse_diagrams(query: str, workdir: Path, max_images: int = 3) -> list[DiagramData]:
    """Download diagrams for a part, OCR them, extract measurements + keywords."""
    results: list[DiagramData] = []
    for i, url in enumerate(_find_diagram_urls(query, max_images)):
        img_path = workdir / f"diagram_{i}.img"
        if not _download(url, img_path):
            continue
        time.sleep(1)
        text = _ocr(img_path)
        if not text.strip():
            continue
        measurements = list(dict.fromkeys(d.strip() for d in DIMENSION_RE.findall(text) if d.strip()))
        keywords = _extract_keywords(text)
        results.append(DiagramData(
            source_url=url,
            measurements=measurements,
            keywords=keywords,
            raw_text=text[:2000],
        ))
    return results
