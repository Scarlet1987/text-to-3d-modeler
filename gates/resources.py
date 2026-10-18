"""Resource manager: keep the pipeline stable, reliable, and efficient
on constrained local hardware.

- Pre-flight checks: VRAM, RAM, disk — refuse to start what won't fit.
- Model lifecycle: load on demand, unload when idle (never sit on VRAM).
- Disk guard: the pipeline generates files; never fill the disk.
- Stability: budgets are enforced, not suggested.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass
class Resources:
    vram_mb: float | None   # None = no GPU / unknown
    ram_mb: float
    disk_free_mb: float


def _read_meminfo() -> dict[str, int]:
    info: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0].endswith(":"):
                    info[parts[0][:-1]] = int(parts[1])  # kB
    except OSError:
        pass
    return info


def get_vram_mb() -> float | None:
    """Best-effort VRAM reading via nvidia-smi. None if unavailable."""
    import subprocess
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return float(out.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


def get_resources(path: str = "/") -> Resources:
    mem = _read_meminfo()
    ram_mb = mem.get("MemAvailable", mem.get("MemTotal", 0)) / 1024
    disk_free_mb = shutil.disk_usage(path).free / (1024 * 1024)
    return Resources(vram_mb=get_vram_mb(), ram_mb=ram_mb, disk_free_mb=disk_free_mb)


@dataclass
class Budget:
    min_ram_mb: float = 1024
    min_disk_mb: float = 512
    min_vram_mb: float | None = None  # set when a GPU model is required


@dataclass
class PreflightResult:
    ok: bool
    problems: list[str]
    resources: Resources


def preflight(budget: Budget, path: str = "/") -> PreflightResult:
    """Check resources before starting work. Refuse what won't fit."""
    res = get_resources(path)
    problems: list[str] = []
    if res.ram_mb < budget.min_ram_mb:
        problems.append(f"RAM {res.ram_mb:.0f}MB < required {budget.min_ram_mb:.0f}MB")
    if res.disk_free_mb < budget.min_disk_mb:
        problems.append(f"disk {res.disk_free_mb:.0f}MB free < required {budget.min_disk_mb:.0f}MB")
    if budget.min_vram_mb is not None:
        if res.vram_mb is None:
            problems.append("no GPU detected but VRAM required")
        elif res.vram_mb < budget.min_vram_mb:
            problems.append(f"VRAM {res.vram_mb:.0f}MB < required {budget.min_vram_mb:.0f}MB")
    return PreflightResult(ok=not problems, problems=problems, resources=res)


class ModelLifecycle:
    """Load the model on demand, unload when idle. Never sit on VRAM."""

    def __init__(self, loader, unloader):
        self._loader = loader
        self._unloader = unloader
        self._loaded = False

    def acquire(self):
        if not self._loaded:
            self._loader()
            self._loaded = True
        return self

    def release(self):
        if self._loaded:
            try:
                self._unloader()
            finally:
                self._loaded = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
