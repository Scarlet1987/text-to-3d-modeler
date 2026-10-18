"""Project storage: personal files and reference files live apart.

projects/<slug>/    YOUR work — prompts, generated scripts, STEP/STL outputs, logs.
                    Never mixed with reference material. Never committed.
references/<slug>/  MANUFACTURER diagrams, datasheets, OCR text, grounded
                    measurements. Cached here so we don't re-download.
                    Never mixed with your work. Never committed.

Nothing gets buried. You always know where your stuff is vs where
the reference material is.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = REPO_ROOT / "projects"
REFERENCES_DIR = REPO_ROOT / "references"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "part"


@dataclass
class Project:
    slug: str
    prompt: str
    created: str = ""
    attempts: int = 0

    @property
    def dir(self) -> Path:
        return PROJECTS_DIR / self.slug

    def save_prompt(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "prompt.txt").write_text(self.prompt)
        meta = {"slug": self.slug, "prompt": self.prompt,
                "created": self.created or datetime.now(timezone.utc).isoformat(),
                "attempts": self.attempts}
        (self.dir / "meta.json").write_text(json.dumps(meta, indent=2))

    def save_outputs(self, step_path: Path, stl_path: Path, script: str, log: str) -> None:
        import shutil
        if step_path and step_path.exists():
            shutil.copy2(step_path, self.dir / "part.step")
        if stl_path and stl_path.exists():
            shutil.copy2(stl_path, self.dir / "part.stl")
        (self.dir / "gen.py").write_text(script)
        (self.dir / "run.log").write_text(log)


@dataclass
class ReferenceCache:
    slug: str
    measurements: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    diagram_urls: list[str] = field(default_factory=list)

    @property
    def dir(self) -> Path:
        return REFERENCES_DIR / self.slug

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "reference.json").write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, slug: str) -> "ReferenceCache | None":
        p = REFERENCES_DIR / slug / "reference.json"
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        return cls(**d)


def new_project(prompt: str) -> Project:
    slug = slugify(prompt)
    # Avoid collisions: bracket-40x20x5, bracket-40x20x5-2, ...
    base, n = slug, 2
    while (PROJECTS_DIR / slug).exists():
        slug = f"{base}-{n}"
        n += 1
    proj = Project(slug=slug, prompt=prompt)
    proj.save_prompt()
    return proj
