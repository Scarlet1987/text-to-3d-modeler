"""Web grounding: search the web for measurements, specs, and diagrams.

Feeds the agent real-world dimensions so generated parts measure right,
not just look right.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass, field

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
    resp = requests.post(
        SEARCH_URL,
        data={"q": query},
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
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


def ground_part(part_description: str) -> GroundingResult:
    """Ground a part: search for its dimensions, specs, and reference diagrams."""
    queries = [
        f"{part_description} dimensions specifications",
        f"{part_description} technical drawing measurements",
    ]
    combined = GroundingResult(query=part_description)
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
