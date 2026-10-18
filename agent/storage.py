"""Project storage: completed runs vs temp, STL and STEP separated.

completed runs/
  <slug>/
    host.json       <- the host file: manifest tying both sections together
    stl/
      part.stl      <- printable output
    step/
      part.step     <- CAD master output
    gen.py          <- the script that made it
    prompt.txt      <- what was asked for
    run.log         <- what happened

completed runs temp/
  <slug>/
    ...same layout...  <- work in progress, hasn't passed all gates yet

A run lives in temp until every gate passes. Then it graduates to
completed runs. Nothing half-finished sits next to finished work.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPLETED_DIR = REPO_ROOT / "completed runs"
TEMP_DIR = REPO_ROOT / "completed runs temp"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "part"


@dataclass
class HostFile:
    """The host file: one manifest for both sections."""
    slug: str
    prompt: str
    created: str = ""
    completed: str = ""
    attempts: int = 0
    stl_file: str = "stl/part.stl"
    step_file: str = "step/part.step"
    measurements_used: list[str] = field(default_factory=list)
    gates_passed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Run:
    slug: str
    prompt: str
    temp: bool = True

    @property
    def dir(self) -> Path:
        base = TEMP_DIR if self.temp else COMPLETED_DIR
        return base / self.slug

    @property
    def stl_dir(self) -> Path:
        return self.dir / "stl"

    @property
    def step_dir(self) -> Path:
        return self.dir / "step"

    def setup(self) -> None:
        self.stl_dir.mkdir(parents=True, exist_ok=True)
        self.step_dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "prompt.txt").write_text(self.prompt)

    def save_outputs(self, step_path: Path | None, stl_path: Path | None,
                     script: str, log: str, host: HostFile) -> None:
        if step_path and step_path.exists():
            shutil.copy2(step_path, self.step_dir / "part.step")
        if stl_path and stl_path.exists():
            shutil.copy2(stl_path, self.stl_dir / "part.stl")
        (self.dir / "gen.py").write_text(script)
        (self.dir / "run.log").write_text(log)
        (self.dir / "host.json").write_text(json.dumps(host.to_dict(), indent=2))

    def graduate(self) -> "Run":
        """Move from temp to completed runs. All gates passed."""
        if not self.temp:
            return self
        dest = COMPLETED_DIR / self.slug
        # Avoid collisions in completed runs.
        base, n = self.slug, 2
        while dest.exists():
            dest = COMPLETED_DIR / f"{base}-{n}"
            n += 1
        shutil.move(str(self.dir), str(dest))
        completed = Run(slug=dest.name, prompt=self.prompt, temp=False)
        return completed


def new_run(prompt: str) -> Run:
    slug = slugify(prompt)
    base, n = slug, 2
    while (TEMP_DIR / slug).exists() or (COMPLETED_DIR / slug).exists():
        slug = f"{base}-{n}"
        n += 1
    run = Run(slug=slug, prompt=prompt, temp=True)
    run.setup()
    return run
