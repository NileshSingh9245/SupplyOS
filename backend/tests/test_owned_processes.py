"""Verification process ownership, including deadlines and abrupt parent exit."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.local_postgres import LocalPostgresError, OwnedProcessGroup

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job ownership")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
BLOCKED_CHILD = "import threading; threading.Event().wait()"


def test_owned_context_stops_blocked_child():
    with OwnedProcessGroup() as processes:
        child = processes.launch(
            [sys.executable, "-B", "-c", BLOCKED_CHILD], environment=dict(os.environ),
            output=subprocess.DEVNULL, cwd=BACKEND_ROOT,
        )
        assert child.poll() is None
    assert child.wait(timeout=10) != 0


def test_deadline_terminates_verification_children():
    with OwnedProcessGroup() as processes:
        with pytest.raises(LocalPostgresError, match="exceeded its deadline"):
            processes.run(
                [sys.executable, "-B", "-c", BLOCKED_CHILD], environment=dict(os.environ),
                output=subprocess.DEVNULL, cwd=BACKEND_ROOT, timeout=0.5,
            )


def test_abrupt_parent_exit_closes_child_job(tmp_path):
    marker = tmp_path / "owned-child.pid"
    script = "\n".join([
        "import os, subprocess, sys",
        "from pathlib import Path",
        "from tools.local_postgres import OwnedProcessGroup",
        "with OwnedProcessGroup() as processes:",
        "    child = processes.launch([sys.executable, '-B', '-c', " + repr(BLOCKED_CHILD) +
        "], environment=dict(os.environ), output=subprocess.DEVNULL)",
        "    Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')",
        "    os._exit(0)",
    ])
    subprocess.run(
        [sys.executable, "-B", "-c", script, str(marker)], cwd=BACKEND_ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=20,
    )
    pid = int(marker.read_text(encoding="utf-8"))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 10000) == 0
        finally:
            kernel.CloseHandle(handle)
