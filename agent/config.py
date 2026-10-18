"""Configuration: no hardcoded magic numbers.

All tolerances, timeouts, budgets, and limits live here — one place,
documented, tunable. Discipline means knowing your numbers.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class GateConfig:
    # Measurement gate: dimension within this fraction of a reference counts as backed.
    measurement_tolerance: float = 0.05
    # Post-build: axis within this fraction of nearest ref before flagging.
    verification_tolerance: float = 0.5
    # Plausible part size range in mm (filters out indices, counts).
    min_dim_mm: float = 0.1
    max_dim_mm: float = 2000.0


@dataclass
class LoopConfig:
    max_attempts: int = 5
    script_timeout_s: int = 300
    # LLM generation timeout — don't hang forever waiting for the model.
    llm_timeout_s: int = 180


@dataclass
class GroundingConfig:
    text_results: int = 8
    max_diagrams: int = 2
    # Skip diagrams entirely if text found this many measurements.
    text_sufficient_threshold: int = 5
    request_delay_s: float = 1.5


@dataclass
class ResourceConfig:
    min_ram_mb: float = 512
    min_disk_mb: float = 256
    min_vram_mb: float | None = None  # set when GPU model required


@dataclass
class Config:
    gates: GateConfig = None
    loop: LoopConfig = None
    grounding: GroundingConfig = None
    resources: ResourceConfig = None

    def __post_init__(self):
        self.gates = self.gates or GateConfig()
        self.loop = self.loop or LoopConfig()
        self.grounding = self.grounding or GroundingConfig()
        self.resources = self.resources or ResourceConfig()

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        cfg = cls()
        p = path or Path("config.json")
        if p.exists():
            try:
                d = json.loads(p.read_text())
                for section, vals in d.items():
                    target = getattr(cfg, section, None)
                    if target is not None and isinstance(vals, dict):
                        for k, v in vals.items():
                            if hasattr(target, k):
                                setattr(target, k, v)
            except Exception:
                pass  # bad config = defaults, never crash on config
        return cfg

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))
