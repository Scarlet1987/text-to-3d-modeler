"""Local web GUI server for the text-to-3D modeler.

Run:  python -m server.app
Then: open http://localhost:8000 in your browser.

One command, no config. The server runs the agent loop in the background
and streams progress to the UI over SSE.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent.cli import _real_generate_fn, _stub_generate
from agent.phase0 import Phase0Loop
from agent.progress import Progress
from agent.storage import COMPLETED_DIR, HostFile, new_run
from gates.resources import Budget, preflight

REPO_ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Text-to-3D Modeler")

# The one active run. One at a time — this is a local tool, not a server farm.
_state: dict = {"status": "idle", "run": None, "log": []}
_events: "queue.Queue[str]" = queue.Queue()


def _emit(event: str, data: dict) -> None:
    _events.put(f"event: {event}\ndata: {json.dumps(data)}\n\n")


class GuiProgress(Progress):
    def report(self, stage: str, detail: str = "") -> None:
        entry = {"stage": stage, "detail": detail}
        _state["log"].append(entry)
        _emit("progress", entry)


def _run_loop(prompt: str, spec_id: str | None = None) -> None:
    try:
        _state["status"] = "running"
        _emit("status", {"status": "running"})

        result = preflight(Budget())
        if not result.ok:
            raise RuntimeError("; ".join(result.problems))
        _emit("progress", {"stage": "preflight", "detail": "ok"})

        # Use the original user prompt for the run slug, not the spec block.
        slug_prompt = prompt
        if spec_id and spec_id in _specs:
            slug_prompt = _specs[spec_id]["prompt"]
        run = new_run(slug_prompt)
        _state["run"] = run
        _emit("progress", {"stage": "run", "detail": run.slug})

        try:
            generate_fn = _real_generate_fn()
        except Exception:
            generate_fn = _stub_generate

        loop = Phase0Loop(generate_fn=generate_fn)
        # prompt here is the verified spec block — the ONLY context the writer sees.
        result = loop.run(prompt, run.dir, on_stage=lambda s, d="": _emit(
            "progress", {"stage": s, "detail": d}))

        if result.ok:
            host = HostFile(
                slug=run.slug, prompt=prompt, attempts=result.attempts,
                gates_passed=["measurement", "compile", "verification"],
            )
            run.save_outputs(run.dir / "part.step", run.dir / "part.stl",
                             result.script, "\n\n".join(result.errors), host)
            done = run.graduate()
            _state["run"] = done
            _state["status"] = "done"
            _emit("done", {
                "slug": done.slug,
                "attempts": result.attempts,
                "stl": f"/runs/{done.slug}/stl/part.stl",
                "step": f"/runs/{done.slug}/step/part.step",
                "measured": result.measured,
            })
        else:
            _state["status"] = "failed"
            _emit("failed", {"errors": result.errors[-3:]})
    except Exception as e:
        _state["status"] = "failed"
        _emit("failed", {"errors": [str(e)]})


@app.post("/api/clarify")
def clarify(body: dict):
    """Ask the LLM what it needs to know before building.

    Returns 2-4 targeted questions. The user answers, answers get folded
    into the build prompt. This is the 'filter of questions' — the software
    asks before it cuts, never guesses.
    """
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return {"questions": []}
    try:
        from agent.llm import QwenBackend
        backend = QwenBackend()
        backend.load()
        q_prompt = (
            f"The user wants to 3D model this part: \"{prompt}\"\n\n"
            "What specific information do you need from the user to model this "
            "accurately? Think about: exact hardware model numbers, dimensions "
            "you can't look up, material/thickness choices, mounting details.\n\n"
            "Return ONLY a JSON list of 2-4 questions, like:\n"
            '["What is the exact carrier board model?", "What thickness should the base plate be?"]\n'
            "If you have enough to proceed, return an empty list: []"
        )
        raw = backend.generate(
            "You ask clarifying questions before 3D modeling. Return only JSON.",
            q_prompt,
        )
        backend.unload()
        # Extract the JSON list.
        import re
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            questions = json.loads(m.group(0))
            if isinstance(questions, list):
                return {"questions": [str(q) for q in questions[:4]]}
    except Exception as e:
        print(f"clarify failed: {e}")
    return {"questions": []}


# Specs awaiting user verification, keyed by id.
_specs: dict[str, dict] = {}
_spec_counter = [0]


@app.post("/api/gather")
def gather_endpoint(body: dict):
    """Gather data only — scrape web, find manufacturer diagrams, return what was found.

    This is Phase 1. Nothing gets built. The user reviews the gathered data,
    then proceeds to spec/build with verified dimensions.
    """
    import shutil
    import tempfile
    from grounding.gather import gather

    query = (body.get("query") or "").strip()
    if not query:
        return {"error": "empty query"}

    tmpdir = Path(tempfile.mkdtemp(prefix="gather_"))
    try:
        data = gather(query, tmpdir)
        return {"data": data.to_dict()}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.get("/api/spec-visual/{spec_id}")
def spec_visual(spec_id: str):
    """Return an SVG technical drawing of the verified spec."""
    from agent.visual import spec_to_svg
    from fastapi.responses import Response
    if spec_id not in _specs:
        return {"error": "spec not found"}
    svg = spec_to_svg(_specs[spec_id]["spec"])
    return Response(content=svg, media_type="image/svg+xml")


@app.post("/api/spec")
def build_spec_endpoint(body: dict):
    """Build a verified spec from prompt + answers.

    Returns the spec for user review. The CAD writer only sees the spec
    after the user confirms it — never raw unverified dimensions.
    """
    from agent.spec import build_spec
    from grounding.retrieve import ground_part

    prompt = (body.get("prompt") or "").strip()
    answers = body.get("answers") or []
    if not prompt:
        return {"error": "empty prompt"}

    # Ground to get reference dimensions for verification.
    grounding = ground_part(prompt)
    spec = build_spec(prompt, answers, grounding.dimensions)

    _spec_counter[0] += 1
    spec_id = f"spec_{_spec_counter[0]}"
    _specs[spec_id] = {"spec": spec, "prompt": prompt, "answers": answers}

    return {"spec_id": spec_id, "spec": spec.to_dict()}


@app.post("/api/update")
def update_server():
    """Pull latest code and restart. The run.sh wrapper handles the restart."""
    def do_update():
        time.sleep(0.5)  # let the response go back first
        try:
            subprocess.run(["git", "pull"], cwd=REPO_ROOT, capture_output=True, timeout=60)
        except Exception:
            pass
        # Exit 42 tells run.sh to restart us with the new code.
        os._exit(42)
    t = threading.Thread(target=do_update, daemon=True)
    t.start()
    return {"updating": True}


@app.get("/api/events")
def events():
    def stream():
        while True:
            try:
                yield _events.get(timeout=30)
            except queue.Empty:
                yield ": keepalive\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/run")
def start_run(body: dict):
    spec_id = body.get("spec_id")
    if not spec_id or spec_id not in _specs:
        return {"error": "no verified spec — build a spec first"}
    if _state["status"] == "running":
        return {"error": "a run is already in progress"}
    entry = _specs[spec_id]
    spec = entry["spec"]
    # The writer gets ONLY the verified spec. Nothing else.
    prompt = spec.prompt_block()
    _state["log"] = []
    _state["status"] = "running"
    _state["spec_id"] = spec_id
    t = threading.Thread(target=_run_loop, args=(prompt, spec_id), daemon=True)
    t.start()
    return {"started": True, "spec_id": spec_id}


@app.get("/api/status")
def status():
    return {"status": _state["status"], "log": _state["log"][-50:]}


@app.get("/api/runs")
def list_runs():
    runs = []
    if COMPLETED_DIR.exists():
        for d in sorted(COMPLETED_DIR.iterdir()):
            host = d / "host.json"
            if host.exists():
                try:
                    meta = json.loads(host.read_text())
                except Exception:
                    meta = {}
                runs.append({
                    "slug": d.name,
                    "prompt": meta.get("prompt", d.name),
                    "attempts": meta.get("attempts", 0),
                    "stl": f"/runs/{d.name}/stl/part.stl",
                    "step": f"/runs/{d.name}/step/part.step",
                })
    return {"runs": runs}


@app.get("/runs/{slug}/stl/part.stl")
def download_stl(slug: str):
    p = COMPLETED_DIR / slug / "stl" / "part.stl"
    return FileResponse(p, media_type="model/stl", filename="part.stl")


@app.get("/runs/{slug}/step/part.step")
def download_step(slug: str):
    p = COMPLETED_DIR / slug / "step" / "part.step"
    return FileResponse(p, media_type="application/step", filename="part.step")


app.mount("/", StaticFiles(directory=REPO_ROOT / "server" / "static", html=True),
            name="static")


def main() -> None:
    import uvicorn
    print("Text-to-3D Modeler GUI")
    print("Open http://localhost:8000 in your browser")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
