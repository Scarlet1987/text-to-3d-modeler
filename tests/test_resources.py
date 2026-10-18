"""Tests for the resource manager: refuse what won't fit."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gates.resources import Budget, ModelLifecycle, preflight


def test_preflight_passes_with_headroom():
    pf = preflight(Budget(min_ram_mb=1, min_disk_mb=1))
    assert pf.ok, pf.problems


def test_preflight_refuses_impossible():
    pf = preflight(Budget(min_ram_mb=10**12, min_disk_mb=10**12))
    assert not pf.ok
    assert len(pf.problems) == 2


def test_lifecycle_loads_and_unloads():
    calls = []

    def loader():
        calls.append("load")

    def unloader():
        calls.append("unload")

    lc = ModelLifecycle(loader, unloader)
    with lc:
        with lc:  # nested acquire is a no-op
            pass
    assert calls == ["load", "unload"]
