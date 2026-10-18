#!/usr/bin/env python3
"""text-to-3d: prompt in, part out.

Usage:
    python -m agent.cli "make a 40x20x5mm bracket with a 6mm hole"

Pipeline: ground (web) -> generate (LLM) -> measure-check -> run ->
verify -> STEP + STL. Stable, reliable, efficient on local hardware.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from the repo root: python -m agent.cli "..."
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm import QwenBackend, make_generate_fn
from agent.phase0 import Phase0Loop
from agent.storage import HostFile, new_run
from gates.resources import Budget, preflight


def _stub_generate(prompt, system, prior_script, error_log, context):
    raise RuntimeError(
        "No LLM backend wired yet. "
        "Qwen3 8B is downloading; the generate_fn slot is ready for it."
    )


def _real_generate_fn():
    backend = QwenBackend()
    return make_generate_fn(backend)


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

    # Run starts in temp. Graduates to completed runs only if all gates pass.
    run = new_run(prompt)
    workdir = run.dir
    try:
        generate_fn = _real_generate_fn()
        print("llm backend: Qwen3 8B wired in")
    except Exception as e:
        print(f"llm backend failed ({e}); using stub")
        generate_fn = _stub_generate
    loop = Phase0Loop(generate_fn=generate_fn)
    print(f"run: {run.dir} (temp)")
    print(f"prompt: {prompt}")
    print("grounding + generating...")
    try:
        result = loop.run(prompt, workdir)
    except RuntimeError as e:
        print(f"NOT READY: {e}")
        return 3

    if result.ok:
        host = HostFile(
            slug=run.slug, prompt=prompt, attempts=result.attempts,
            completed=datetime.now(timezone.utc).isoformat(),
            gates_passed=["measurement", "compile", "verification"],
        )
        # Note: loop.run wrote part.step/part.stl into workdir; move them in.
        run.save_outputs(workdir / "part.step", workdir / "part.stl",
                         result.script, "\n\n".join(result.errors), host)
        done = run.graduate()
        print(f"DONE in {result.attempts} attempt(s)")
        print(f"  completed: {done.dir}")
        print(f"  STEP: {done.dir / 'step' / 'part.step'}")
        print(f"  STL:  {done.dir / 'stl' / 'part.stl'}")
        print(f"  host: {done.dir / 'host.json'}")
        return 0
    print(f"FAILED after {result.attempts} attempt(s):")
    for e in result.errors[-3:]:
        print(e[:800])
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
