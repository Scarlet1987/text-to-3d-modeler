"""Progress reporting: the user always knows what the machine is doing.

A silent pipeline is an untrustworthy pipeline. Every stage announces
itself; every failure says what happened and what's next.
"""

from __future__ import annotations

import sys
from datetime import datetime


class Progress:
    def __init__(self, out=None):
        self.out = out or sys.stdout

    def _say(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", file=self.out, flush=True)

    def stage(self, name: str) -> None:
        self._say(f"—— {name} ——")

    def info(self, msg: str) -> None:
        self._say(f"  {msg}")

    def attempt(self, n: int, total: int) -> None:
        self._say(f"  attempt {n}/{total}")

    def diagnosis(self, kind: str, advice: str, retryable: bool) -> None:
        flag = "retrying" if retryable else "STOPPED — needs you"
        self._say(f"  ! {kind}: {flag}")
        self._say(f"    {advice[:200]}")

    def done(self, msg: str) -> None:
        self._say(f"✓ {msg}")

    def failed(self, msg: str) -> None:
        self._say(f"✗ {msg}")
