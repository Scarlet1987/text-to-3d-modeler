"""Phase 0: prove the loop.

prompt -> LLM generates CadQuery script -> run headless ->
on error, feed back and self-debug -> valid STEP, no human code edits.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class JobResult:
    ok: bool
    step_path: Path | None = None
    script: str = ""
    attempts: int = 0
    errors: list[str] = field(default_factory=list)


SYSTEM_PROMPT = """You write CadQuery (Python) scripts that generate 3D parts.
Rules:
- Output ONLY valid Python code using `import cadquery as cq`. No markdown, no explanation.
- The script must define `result` as a cadquery Workplane/Solid at the end.
- Use millimeters. Keep it simple and watertight.
- If you get an error message back, fix the script and output the corrected version.
"""


def run_cadquery_script(script: str, workdir: Path) -> tuple[bool, str, Path | None]:
    """Run a CadQuery script headlessly. Returns (ok, log, step_path)."""
    script_path = workdir / "gen.py"
    step_path = workdir / "part.step"
    runner = (
        "import runpy, cadquery as cq, sys\n"
        "ns = runpy.run_path(sys.argv[1])\n"
        "result = ns.get('result')\n"
        "assert result is not None, 'script must define `result`'\n"
        "cq.exporters.export(result, sys.argv[2])\n"
    )
    runner_path = workdir / "_runner.py"
    runner_path.write_text(runner)
    script_path.write_text(script)
    proc = subprocess.run(
        [sys.executable, str(runner_path), str(script_path), str(step_path)],
        capture_output=True, text=True, timeout=300,
    )
    log = proc.stdout + proc.stderr
    ok = proc.returncode == 0 and step_path.exists()
    return ok, log, step_path if ok else None


class Phase0Loop:
    """The generate -> run -> self-debug loop. LLM backend is pluggable."""

    def __init__(self, generate_fn, max_attempts: int = 5):
        # generate_fn(prompt, system, prior_script, error_log) -> script str
        self.generate_fn = generate_fn
        self.max_attempts = max_attempts

    def run(self, prompt: str, workdir: Path) -> JobResult:
        errors: list[str] = []
        script = ""
        for attempt in range(1, self.max_attempts + 1):
            script = self.generate_fn(prompt, SYSTEM_PROMPT, script, "\n".join(errors))
            ok, log, step_path = run_cadquery_script(script, workdir)
            if ok:
                return JobResult(True, step_path, script, attempt, errors)
            errors.append(f"--- attempt {attempt} ---\n{log.strip()[-2000:]}")
        return JobResult(False, None, script, self.max_attempts, errors)
