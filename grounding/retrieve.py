"""Web grounding: search the web for measurements, specs, and diagrams.

Feeds the agent real-world dimensions so generated parts measure right,
not just look right.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import requests

SEARCH_URL = "https://html.duckduckgo.com/html/"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}

# Patterns that look like dimensions: 42mm, 3.5", 10 x 20 x 5, M3, etc.
DIMENSION_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mm|cm|m|in|inch|inches|\"|')\b"
    r"|\b\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?(?:\s*[x×]\s*\d+(?:\.\d+)?)?\s*(?:mm|cm|in)?\b"
    r"|\bM\d+(?:\.\d+)?\b",
    re.IGNORECASE,
)


@dataclass
class GroundingResult:
    query: str
    snippets: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def prompt_block(self) -> str:
        """Render as context for the generating LLM."""
        lines = [f"Reference data for: {self.query}"]
        if self.dimensions:
            lines.append("Known dimensions: " + "; ".join(list(dict.fromkeys(self.dimensions))[:20]))
        for s in self.snippets[:5]:
            lines.append(f"- {s[:300]}")
        if self.sources:
            lines.append("Sources: " + ", ".join(self.sources[:5]))
        return "\n".join(lines)


def _search(query: str, max_results: int = 8) -> list[dict]:
    import time
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.post(
                SEARCH_URL,
                data={"q": query},
                headers=HEADERS,
                timeout=30,
            )
            # 202 or CAPTCHA page = blocked, not empty results.
            if resp.status_code == 202 or "captcha" in resp.text.lower()[:2000]:
                last_error = "search engine blocked the request (rate limit)"
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            last_error = str(e)
            time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError(f"web search failed after 3 attempts: {last_error}")
    results = []
    links = re.findall(r'result__a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.DOTALL)
    snippets = re.findall(r'result__snippet[^>]*>(.*?)</a>', resp.text, re.DOTALL)
    for i, (url, title) in enumerate(links):
        # DDG wraps urls in a redirect; unwrap
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        real_url = qs.get("uddg", [url])[0]
        title = re.sub(r"<[^>]+>", "", title or "").strip()
        snippet = re.sub(r"<[^>]+>", "", snippets[i] if i < len(snippets) else "").strip()
        results.append({"url": real_url, "title": title, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def ground(query: str, max_results: int = 8) -> GroundingResult:
    """Search the web for measurements/specs/diagrams about a part."""
    result = GroundingResult(query=query)
    for r in _search(query, max_results):
        text = f"{r['title']}. {r['snippet']}".strip(". ")
        if text:
            result.snippets.append(text)
        result.sources.append(r["url"])
        for d in DIMENSION_RE.findall(text):
            d = d.strip()
            if d:
                result.dimensions.append(d)
    return result


def _extract_hardware_terms(part_description: str) -> str:
    """Pull out named hardware from a prompt for targeted datasheet search.

    'make a tray for raspberry pi cm5' -> 'raspberry pi cm5'
    'bracket for arduino uno' -> 'arduino uno'
    Returns empty string if no hardware is named.
    """
    import re
    desc = part_description.lower()
    # Common board/part patterns: brand + model
    patterns = [
        r"raspb?erry pi\s+(?:compute module\s*)?(?:cm)?\d+[a-z]*",
        r"arduino\s+\w+",
        r"esp32[-\w]*",
        r"teensy\s*[\d.]+",
        r"nvidia\s+jetson\s+\w+",
        r"beaglebone\s+\w+",
    ]
    for pat in patterns:
        m = re.search(pat, desc)
        if m:
            return m.group(0).strip()
    return ""


def _load_local_references(part_description: str) -> GroundingResult:
    """Check references/ for locally-saved ground truth matching this part.

    Reference files are JSON with dimensions, specs, and measurements the
    user has confirmed. They outrank web search — local truth beats the internet.
    """
    result = GroundingResult(query=part_description)
    ref_dir = Path(__file__).resolve().parent.parent / "references"
    if not ref_dir.exists():
        return result
    desc_lower = part_description.lower()
    for ref_file in ref_dir.glob("*.json"):
        try:
            data = json.loads(ref_file.read_text())
        except Exception:
            continue
        # Match if the reference project name or any key appears in the prompt.
        project = str(data.get("project", "")).lower()
        if project and project.replace("-", " ") in desc_lower:
            _extract_ref_dimensions(data, result, ref_file.name)
        elif "handheld" in desc_lower and "handheld" in project:
            _extract_ref_dimensions(data, result, ref_file.name)
    return result


def _extract_ref_dimensions(data: dict, result: GroundingResult, source: str) -> None:
    """Pull every millimeter value out of a reference JSON."""
    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, path)
        elif isinstance(obj, (int, float)) and "mm" in path.lower():
            result.dimensions.append(f"{obj}mm ({path})")
            result.sources.append(f"local:{source}")
    walk(data)
    result.snippets.append(f"Local reference {source}: {json.dumps(data)[:500]}")


def ground_part(part_description: str) -> GroundingResult:
    """Ground a part: search for exact specs, never guess.

    The invariant: when the user names hardware, the parser MUST find its
    exact datasheet dimensions. It retains the principle (always find exact
    specs), not a library of data. Nothing is stored, nothing goes stale.
    """
    # Local truth first — the user's own confirmed measurements.
    combined = _load_local_references(part_description)

    # Detect named hardware: if the prompt names a specific board or part,
    # target datasheets and mechanical drawings, not generic dimensions.
    hardware_terms = _extract_hardware_terms(part_description)
    if hardware_terms:
        queries = [
            f"{hardware_terms} datasheet dimensions",
            f"{hardware_terms} mechanical drawing mounting holes",
        ]
    else:
        queries = [
            f"{part_description} dimensions specifications",
            f"{part_description} technical drawing measurements",
        ]
    for qi, q in enumerate(queries):
        for attempt in range(3):
            r = ground(q)
            if r.snippets:
                break
            time.sleep(2 * (attempt + 1))  # back off on rate-limit empties
        combined.snippets.extend(r.snippets)
        combined.dimensions.extend(r.dimensions)
        combined.sources.extend(r.sources)
        if qi < len(queries) - 1:
            time.sleep(1.5)  # be polite between queries
    return combined
