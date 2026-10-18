"""Tests for troubleshooting diagnosis and config."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Config
from gates.troubleshoot import FailureKind, diagnose


def test_diagnose_segfault():
    d = diagnose("Segmentation fault (core dumped)", -11)
    assert d.kind == FailureKind.KERNEL_CRASH
    assert d.retryable


def test_diagnose_syntax():
    d = diagnose("SyntaxError: invalid syntax", 1)
    assert d.kind == FailureKind.SYNTAX


def test_diagnose_measurement():
    d = diagnose("MEASUREMENT CHECK FAILED.\nno backing", 1)
    assert d.kind == FailureKind.MEASUREMENT


def test_diagnose_resource_not_retryable():
    d = diagnose("PREFLIGHT FAILED — refusing", 1)
    assert d.kind == FailureKind.RESOURCE
    assert not d.retryable


def test_diagnose_unknown():
    d = diagnose("something weird happened", 1)
    assert d.kind == FailureKind.UNKNOWN


def test_config_defaults():
    c = Config()
    assert c.gates.measurement_tolerance == 0.05
    assert c.loop.max_attempts == 5


def test_config_load_overrides(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"loop": {"max_attempts": 3}}')
    c = Config.load(p)
    assert c.loop.max_attempts == 3
    assert c.gates.measurement_tolerance == 0.05  # untouched


def test_config_bad_file_falls_back_to_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("not json {{{")
    c = Config.load(p)
    assert c.loop.max_attempts == 5
