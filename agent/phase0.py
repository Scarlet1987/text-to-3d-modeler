"""Phase 0: prove the loop.

prompt -> ground (web search for real measurements) ->
LLM generates CadQuery script -> measurement check gate ->
run headless -> on error, feed back and self-debug ->
valid STEP, no human code edits.

The measurement gate is inviolable: no dimension may be altered
without reference backing. Measurements come from reality,
not from making the code compile.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from gates.measurements import check_measurements
from gates.verify import verify_step
from grounding.diagrams import parse_diagrams
from grounding.retrieve import DIMENSION_RE, ground_part


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
    """Run a CadQuery script headlessly. Returns (ok, log, step_path).

    Exports STEP (CAD) and STL (3D printing) — the STEP is the master,
    the STL is what the printer wants.
    """
    script_path = workdir / "gen.py"
    step_path = workdir / "part.step"
    stl_path = workdir / "part.stl"
    runner = (
        "import runpy, cadquery as cq, sys\n"
        "ns = runpy.run_path(sys.argv[1])\n"
        "result = ns.get('result')\n"
        "assert result is not None, 'script must define `result`'\n"
        "cq.exporters.export(result, sys.argv[2])\n"
        "cq.exporters.export(result, sys.argv[3])\n"
    )
    runner_path = workdir / "_runner.py"
    runner_path.write_text(runner)
    script_path.write_text(script)
    proc = subprocess.run(
        [sys.executable, str(runner_path), str(script_path), str(step_path), str(stl_path)],
        capture_output=True, text=True, timeout=300,
    )
    log = proc.stdout + proc.stderr
    ok = proc.returncode == 0 and step_path.exists() and stl_path.exists()
    return ok, log, step_path if ok else None


class Phase0Loop:
    """The generate -> measure-check -> run -> self-debug loop. LLM backend is pluggable."""

    def __init__(self, generate_fn, max_attempts: int = 5):
        # generate_fn(prompt, system, prior_script, error_log, context) -> script str
        self.generate_fn = generate_fn
        self.max_attempts = max_attempts

    def run(self, prompt: str, workdir: Path) -> JobResult:
        # Ground first: real measurements before any generation.
        # Text is cheap; diagrams cost download+OCR, so they run only
        # when text comes up short — and only from trusted, relevant sources.
        # Fallback: dimensions in the user's own prompt are ground truth.
        # If nothing grounds the part, refuse — don't guess.
        grounding = ground_part(prompt)
        reference_dims = list(grounding.dimensions)
        diagram_keywords: list[str] = []
        for dd in parse_diagrams(prompt, workdir, reference_dims):
            reference_dims.extend(dd.measurements)
            diagram_keywords.extend(dd.keywords)
        # User-stated dimensions are authoritative.
        prompt_dims = [d.strip() for d in DIMENSION_RE.findall(prompt) if d.strip()]
        reference_dims.extend(d for d in prompt_dims if d not in reference_dims)
        if not reference_dims:
            return JobResult(
                ok=False, attempts=0,
                errors=["NO GROUNDING: no measurements found on the web, in diagrams, "
                        "or in your prompt. I won't guess dimensions. "
                        "Include measurements in your prompt (e.g. 'make a 40x20x5mm bracket') "
                        "or name a part with published specs."],
            )
        context = grounding.prompt_block()
        if reference_dims != grounding.dimensions:
            context += "\nDiagram-sourced dimensions: " + "; ".join(reference_dims)
        if diagram_keywords:
            seen = list(dict.fromkeys(diagram_keywords))[:25]
            context += "\nDomain terms from manufacturer diagrams: " + ", ".join(seen)

        errors: list[str] = []
        script = ""
        previous_script: str | None = None
        for attempt in range(1, self.max_attempts + 1):
            script = self.generate_fn(prompt, SYSTEM_PROMPT, script, "\n".join(errors), context)

            # MEASUREMENT GATE: check before running, check before altering.
            mcheck = check_measurements(script, previous_script, reference_dims)
            if not mcheck.passed:
                errors.append(
                    "MEASUREMENT CHECK FAILED.\n"
                    + "\n".join(mcheck.notes)
                    + "\nDo not alter measurements to make the code compile. "
                    + "Check each changed dimension against the reference data above, "
                    + "cite your source, or ask the user."
                )
                previous_script = script
                continue

            ok, log, step_path = run_cadquery_script(script, workdir)
            if ok:
                # POST-BUILD GATE: measure the actual geometry against reference.
                v = verify_step(step_path, reference_dims)
                if not v.passed:
                    errors.append(
                        "POST-BUILD VERIFICATION FAILED.\n"
                        + "\n".join(v.failures)
                        + f"\nMeasured: {v.measured}. "
                        + "The part compiled but does not match spec. Fix the geometry."
                    )
                    previous_script = script
                    continue
                return JobResult(True, step_path, script, attempt, errors)
            errors.append(f"--- attempt {attempt} ---\n{log.strip()[-2000:]}")
            previous_script = script
        return JobResult(False, None, script, self.max_attempts, errors)
