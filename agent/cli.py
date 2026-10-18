#!/usr/bin/env python3
"""text-to-3d: prompt in, part out.

Usage:
    python -m agent.cli "make a 40x20x5mm bracket with a 6mm hole"

Pipeline: ground (web) -> generate (LLM) -> measure-check -> run ->
verify -> STEP + STL. Stable, reliable, efficient on local hardware.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Allow running from the repo root: python -m agent.cli "..."
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.phase0 import Phase0Loop
from agent.storage import new_project
from gates.resources import Budget, preflight


def _stub_generate(prompt, system, prior_script, error_log, context):
    raise RuntimeError(
        "No LLM backend wired yet. "
        "Qwen3 8B is downloading; the generate_fn slot is ready for it."
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    prompt = " ".join(argv[1:])

    # Pre-flight: refuse what won't fit. Stable on small hardware.
    pf = preflight(Budget(min_ram_mb=512, min_disk_mb=256))
    if not pf.ok:
        print("PREFLIGHT FAILED — refusing to start:")
        for p in pf.problems:
            print(f"  - {p}")
        return 1
    print(f"preflight ok: {pf.resources.ram_mb:.0f}MB RAM, {pf.resources.disk_free_mb:.0f}MB disk free")

    # Personal project dir — your work lives here, separate from references.
    proj = new_project(prompt)
    workdir = proj.dir
    loop = Phase0Loop(generate_fn=_stub_generate)
    print(f"project: {proj.dir}")
    print(f"prompt: {prompt}")
    print("grounding + generating...")
    try:
        result = loop.run(prompt, workdir)
    except RuntimeError as e:
        print(f"NOT READY: {e}")
        return 3

    if result.ok:
        stl = workdir / "part.stl"
        proj.attempts = result.attempts
        proj.save_outputs(result.step_path, stl, result.script,
                          "\n\n".join(result.errors))
        proj.save_prompt()  # update meta with attempt count
        print(f"DONE in {result.attempts} attempt(s)")
        print(f"  project: {proj.dir}")
        print(f"  STEP: {proj.dir / 'part.step'}")
        print(f"  STL:  {proj.dir / 'part.stl'}")
        return 0
    print(f"FAILED after {result.attempts} attempt(s):")
    for e in result.errors[-3:]:
        print(e[:800])
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
