"""Local web GUI server for the text-to-3D modeler.

Run:  python -m server.app
Then: open http://localhost:8000 in your browser.

One command, no config. The server runs the agent loop in the background
and streams progress to the UI over SSE.
"""

from __future__ import annotations

import json
import queue
import threading
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


def _run_loop(prompt: str) -> None:
    try:
        _state["status"] = "running"
        _emit("status", {"status": "running"})

        ok, msg = preflight(Budget())
        if not ok:
            raise RuntimeError(msg)
        _emit("progress", {"stage": "preflight", "detail": "ok"})

        run = new_run(prompt)
        _state["run"] = run
        _emit("progress", {"stage": "run", "detail": run.slug})

        try:
            generate_fn = _real_generate_fn()
        except Exception:
            generate_fn = _stub_generate

        loop = Phase0Loop(generate_fn=generate_fn)
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
            })
        else:
            _state["status"] = "failed"
            _emit("failed", {"errors": result.errors[-3:]})
    except Exception as e:
        _state["status"] = "failed"
        _emit("failed", {"errors": [str(e)]})


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
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return {"error": "empty prompt"}
    if _state["status"] == "running":
        return {"error": "a run is already in progress"}
    _state["log"] = []
    _state["status"] = "running"
    t = threading.Thread(target=_run_loop, args=(prompt,), daemon=True)
    t.start()
    return {"started": True}


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
