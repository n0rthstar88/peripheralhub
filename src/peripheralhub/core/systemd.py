"""Tiny helpers for the peripheralhub user service."""
from __future__ import annotations

import subprocess

SERVICE = "peripheralhub"


def service_active(run=subprocess.run) -> bool:
    try:
        r = run(["systemctl", "--user", "is-active", "--quiet", SERVICE], timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0
