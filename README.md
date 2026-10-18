# Text-to-3D Modeler

**JARVIS on 8GB VRAM — an AI engineer that designs with heavy user insight and control.**

A text-to-3D system that beats current tools on accuracy by doing its homework: it gathers reference information from the internet, asks only the questions that matter, and drives real CAD software through scripting APIs to produce models that **measure right** — not sculpted meshes that merely look right.

Low VRAM budget, high accuracy. Powerful without being power-hungry. Stable. Flexible enough to build anything.

## Architecture

**Agentic harness driving scriptable CAD through APIs.** The agent is the hands; the CAD software is the tool. No GUI automation, no Loftsmith remake — scripting APIs are reliable, headless, and Linux-friendly.

- **Agent core:** Qwen3 8B (coder variant), Q4 ≈ 5GB VRAM — conversational interface, question filter, planning, tool calls. Hybrid escalation to larger remote models for the hardest steps.
- **Web grounding:** per job, pulls reference images, specs, and dimensions from the internet. This is the accuracy edge.
- **Question filter:** broad strokes first, targeted questions only for what matters. Progressive detail, user-controlled.
- **CAD backends:** CadQuery (first) → OpenSCAD → FreeCAD / build123d.
- **Inspection gates:** spec confirmed → script compiles → geometry checks pass → user sign-off. When a gate passes, failed attempts are composted and VRAM rebalances to the live working set.
- **Resource manager:** VRAM budget enforcement, conservative headroom. Stability first — queue, never drop.

## Phases

- **Phase 0 — Prove the loop.** Qwen3 8B + CadQuery, headless. One simple part. *Exit: prompt → valid STEP with no human code edits.*
- **Phase 1 — Question filter + web grounding.** Conversational spec refinement; retrieval module.
- **Phase 2 — Inspection gates + VRAM rebalancing.** Gated pipeline, context pruning, resource manager.
- **Phase 3 — More backends + hybrid escalation.** OpenSCAD, FreeCAD; remote-model escalation.
- **Phase 4 — Product surface.** GUI, presets, export pipeline (STEP/STL/3MF), project library.

## Layout

```
agent/        agent core, question filter, planning
backends/     CAD backends (cadquery/, openscad/, freecad/)
grounding/    web retrieval for reference specs/dimensions
gates/        inspection gates + resource manager
tests/        per-phase exit criteria as tests
docs/         design notes, research
```

## First job

This modeler exists to design real parts. Its first commission: the 3D-printed components for a Pi CM5 handheld thin client — skeleton frame, gaskets, button mounts, shell.

## License

TBD
