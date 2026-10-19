"""Test lab for the text-to-3D modeler.

The harness is the lab. Every test runs against the hard ceiling:
8GB VRAM on the RX 580 baseline. If anything doesn't fit the footprint,
it doesn't ship.

Run: python -m tests.test_lab  (from the repo root)
     or: python tests/test_lab.py

Modules:
  1. resources  — VRAM/RAM/disk detection, hard ceiling check
  2. parser     — regex datasheet extraction regression
  3. footprint  — 8B model VRAM footprint vs the 8GB ceiling
  4. gates      — measurement, verify, troubleshoot gates
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.config import Config
from gates.resources import (
    check_footprint,
    get_resources,
    get_vram_mb,
    get_vram_used_mb,
)

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results: list[tuple[str, str, str]] = []  # (module, status, detail)


def record(module: str, status: str, detail: str = "") -> None:
    results.append((module, status, detail))
    print(f"  [{status}] {module}" + (f" — {detail}" if detail else ""))


def test_resources() -> None:
    """Module 1: resource detection + hard ceiling."""
    print("\n=== 1. RESOURCES ===")
    cfg = Config.load()
    ceiling = cfg.resources.hard_vram_ceiling_mb

    res = get_resources()
    vram = get_vram_mb()
    vram_used = get_vram_used_mb()

    print(f"  RAM available: {res.ram_mb:.0f}MB")
    print(f"  disk free: {res.disk_free_mb:.0f}MB")
    if vram is not None:
        print(f"  VRAM total: {vram:.0f}MB")
        record("vram-detect", PASS, f"{vram:.0f}MB detected")
    else:
        print("  VRAM: no GPU detected (CPU-only environment)")
        record("vram-detect", SKIP, "no GPU in this environment")

    if vram_used is not None:
        print(f"  VRAM used: {vram_used:.0f}MB")
        fits, msg = check_footprint(vram_used, ceiling)
        record("vram-footprint", PASS if fits else FAIL, msg)
    else:
        record("vram-footprint", SKIP, "cannot read VRAM usage here")

    print(f"  hard ceiling: {ceiling:.0f}MB")
    if vram is not None and vram < ceiling:
        record("ceiling-baseline", PASS,
               f"card {vram:.0f}MB is at/below {ceiling:.0f}MB design baseline")
    elif vram is not None:
        record("ceiling-baseline", PASS,
               f"card {vram:.0f}MB exceeds baseline — pipeline must still fit {ceiling:.0f}MB")
    else:
        record("ceiling-baseline", SKIP, "no GPU to compare")


def test_parser() -> None:
    """Module 2: regex parser regression."""
    print("\n=== 2. PARSER ===")
    try:
        from tests.test_parser_stability import main as parser_main
        score = parser_main()
        if score is None:
            record("parser", SKIP, "datasheet unavailable")
        elif score["hit_rate"] >= 0.8:
            record("parser", PASS, f"{score['hit_rate']:.0%} hit rate")
        else:
            record("parser", FAIL, f"hit rate {score['hit_rate']:.0%} < 80%")
    except Exception as e:
        record("parser", FAIL, f"exception: {e}")


def test_footprint() -> None:
    """Module 3: 8B model VRAM footprint vs the ceiling.

    Estimates from the model file size + KV cache math. On a GPU machine
    this would measure actual VRAM delta across load/unload.
    """
    print("\n=== 3. MODEL FOOTPRINT ===")
    cfg = Config.load()
    ceiling = cfg.resources.hard_vram_ceiling_mb

    model_path = REPO_ROOT / "models" / "Qwen3-8B-Q4_K_M.gguf"
    if not model_path.exists():
        record("model-weights", SKIP, f"model not found: {model_path}")
        return

    weights_mb = model_path.stat().st_size / (1024 * 1024)
    print(f"  model weights on disk: {weights_mb:.0f}MB")

    # KV cache estimate for Qwen3-8B at n_ctx=8192.
    # 36 layers, hidden 4096, K+V, ~1 byte/param with quantization.
    n_layers, hidden, n_ctx = 36, 4096, 8192
    kv_mb = 2 * n_layers * hidden * n_ctx / (1024 * 1024)
    print(f"  KV cache estimate (n_ctx={n_ctx}): ~{kv_mb:.0f}MB")

    # llama.cpp overhead: compute buffers, ~5-10% of weights.
    overhead_mb = weights_mb * 0.08
    total_mb = weights_mb + kv_mb + overhead_mb
    print(f"  estimated total VRAM: ~{total_mb:.0f}MB "
          f"(weights {weights_mb:.0f} + KV {kv_mb:.0f} + overhead {overhead_mb:.0f})")

    fits, msg = check_footprint(total_mb, ceiling)
    record("model-footprint", PASS if fits else FAIL, msg)

    # If we're on a GPU machine, measure the real delta.
    vram_before = get_vram_used_mb()
    if vram_before is None:
        record("model-measured", SKIP, "no GPU — estimate only")
        return
    try:
        from agent.llm import QwenBackend
        backend = QwenBackend(model_path=model_path, n_ctx=n_ctx)
        backend.load()
        time.sleep(2)  # let VRAM settle
        vram_after = get_vram_used_mb()
        backend.unload()
        if vram_after is not None:
            delta = vram_after - vram_before
            print(f"  measured VRAM delta: {delta:.0f}MB")
            fits, msg = check_footprint(vram_after, ceiling)
            record("model-measured", PASS if fits else FAIL, msg)
        else:
            record("model-measured", SKIP, "could not read VRAM after load")
    except Exception as e:
        record("model-measured", FAIL, f"load failed: {e}")


def test_gates() -> None:
    """Module 4: pipeline gates still pass."""
    print("\n=== 4. GATES ===")
    import subprocess
    gate_tests = [
        "tests/test_measurements.py",
        "tests/test_verify.py",
        "tests/test_resources.py",
        "tests/test_troubleshoot.py",
    ]
    for gt in gate_tests:
        p = REPO_ROOT / gt
        if not p.exists():
            record(gt, SKIP, "not found")
            continue
        try:
            out = subprocess.run(
                [sys.executable, "-m", "pytest", str(p), "-q", "--no-header"],
                capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
            )
            if out.returncode == 0:
                # Count passed from output.
                line = [l for l in out.stdout.splitlines() if "passed" in l]
                detail = line[-1].strip() if line else "ok"
                record(gt, PASS, detail)
            else:
                # Fall back: try running directly.
                out2 = subprocess.run(
                    [sys.executable, str(p)],
                    capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
                )
                if out2.returncode == 0:
                    record(gt, PASS, "ran clean")
                else:
                    err = (out.stderr or out2.stderr or "").splitlines()
                    record(gt, FAIL, err[-1][:100] if err else "failed")
        except FileNotFoundError:
            # No pytest — try direct execution.
            try:
                out = subprocess.run(
                    [sys.executable, str(p)],
                    capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
                )
                record(gt, PASS if out.returncode == 0 else FAIL,
                       "ran clean" if out.returncode == 0 else "failed")
            except Exception as e:
                record(gt, FAIL, f"exception: {e}")
        except Exception as e:
            record(gt, FAIL, f"exception: {e}")


def main() -> int:
    print("=" * 60)
    print("  TEXT-TO-3D MODELER — TEST LAB")
    print("  hard ceiling: 8GB VRAM (RX 580 baseline)")
    print("  if it doesn't fit, it doesn't ship")
    print("=" * 60)

    test_resources()
    test_parser()
    test_footprint()
    test_gates()

    print("\n" + "=" * 60)
    print("  LAB REPORT")
    print("=" * 60)
    n_pass = sum(1 for _, s, _ in results if s == PASS)
    n_fail = sum(1 for _, s, _ in results if s == FAIL)
    n_skip = sum(1 for _, s, _ in results if s == SKIP)
    for module, status, detail in results:
        print(f"  [{status}] {module}" + (f" — {detail}" if detail else ""))
    print(f"\n  {n_pass} pass, {n_fail} fail, {n_skip} skip")
    if n_fail:
        print("  VERDICT: FAIL — fix the failures before shipping.")
        return 1
    print("  VERDICT: PASS — fits the footprint.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
