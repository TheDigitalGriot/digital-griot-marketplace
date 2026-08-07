#!/usr/bin/env python3
"""Self-bootstrapping launcher for the cinopsis MCP server.

Builds (once) and reuses a virtual-env in ``${CLAUDE_PLUGIN_DATA}/venv``,
installs ``requirements.txt`` into it, then hands off to a target script using
that venv's Python. This needs ZERO terminal action — it is how dependencies
land on Claude Cowork, which has no Bash tool, no terminal, and no hook
lifecycle to run ``pip`` from.

Design notes:
- All bootstrap progress and subprocess output is routed to **stderr**. The
  launcher's **stdout** must stay a clean MCP JSON-RPC channel.
- The target is run via ``subprocess`` with inherited stdio (not ``os.execv``,
  which is unreliable for stdio servers on Windows). The child inherits the
  exact stdin/stdout the parent (Claude) opened, so MCP I/O flows directly.

Usage:
    python mcp_launcher.py <target_script.py> [args...]
    python mcp_launcher.py --selfcheck
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent))


def plugin_data_dir() -> Path:
    """Resolve the persisted data dir (survives plugin updates)."""
    env = os.environ.get("CLAUDE_PLUGIN_DATA")
    if env:
        return Path(env)
    return Path.home() / ".claude" / "plugins" / "data" / "cinopsis-cinopsis"


def venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _requirements_file() -> Path:
    req = PLUGIN_ROOT / "requirements.txt"
    if req.exists():
        return req
    return Path(__file__).resolve().parent.parent / "requirements.txt"


def _req_hash(req_file: Path) -> str:
    return hashlib.sha256(req_file.read_bytes()).hexdigest() if req_file.exists() else ""


def _run(cmd) -> None:
    """Run a bootstrap subprocess, routing its stdout to stderr to keep fd 1 clean."""
    subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr, check=True)


def ensure_venv() -> Path:
    """Create/reuse the venv and install requirements when they change.

    Returns the path to the venv's Python interpreter.
    """
    data_dir = plugin_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = data_dir / "venv"
    py = venv_python(venv_dir)

    if not py.exists():
        print(f"[cinopsis] creating venv at {venv_dir} (one time) ...", file=sys.stderr, flush=True)
        _run([sys.executable, "-m", "venv", str(venv_dir)])

    req_file = _requirements_file()
    marker = venv_dir / ".req-hash"
    want = _req_hash(req_file)
    have = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""

    if want and want != have:
        print("[cinopsis] installing dependencies into venv (one time, ~30s) ...", file=sys.stderr, flush=True)
        _run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"])
        _run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(req_file)])
        marker.write_text(want, encoding="utf-8")

    return py


_JOB_HANDLE = None  # module-level so the job stays open for the launcher's life


def _bind_kill_on_close(child_pid):
    """Assign the server child to a Windows Job Object with KILL_ON_JOB_CLOSE.

    When the host terminates this launcher, closing our handles closes the job
    and the OS kills the server child instead of orphaning it. Best-effort: any
    failure leaves the prior plain-wait behaviour untouched. No-op off Windows.
    """
    global _JOB_HANDLE
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        class _BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IO(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_uint64),
                        ("WriteOperationCount", ctypes.c_uint64),
                        ("OtherOperationCount", ctypes.c_uint64),
                        ("ReadTransferCount", ctypes.c_uint64),
                        ("WriteTransferCount", ctypes.c_uint64),
                        ("OtherTransferCount", ctypes.c_uint64)]

        class _EXT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BASIC),
                        ("IoInfo", _IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        hJob = k32.CreateJobObjectW(None, None)
        if not hJob:
            return
        info = _EXT()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(hJob, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(hJob)
            return
        hProc = k32.OpenProcess(0x0100 | 0x0001, False, int(child_pid))  # SET_QUOTA | TERMINATE
        if not hProc:
            k32.CloseHandle(hJob)
            return
        try:
            if not k32.AssignProcessToJobObject(hJob, hProc):
                k32.CloseHandle(hJob)
                return
        finally:
            k32.CloseHandle(hProc)
        _JOB_HANDLE = hJob
    except Exception as e:
        print("[cinopsis] job-object bind skipped: %s" % e, file=sys.stderr, flush=True)


def _start_parent_watchdog(proc):
    """Backstop to the Job Object: if our parent (Claude) vanishes, reap the
    server child even when stdin-EOF did not propagate (e.g. a server that
    ignores stdin close). A daemon thread polls the parent PID; on two
    consecutive misses it terminates the child and exits, which also closes
    the job handle (KILL_ON_JOB_CLOSE). Best-effort, Windows-only, non-fatal."""
    if sys.platform != "win32":
        return
    import threading, time, ctypes
    parent_pid = os.getppid()
    if not parent_pid or parent_pid <= 0:
        return
    def _alive(pid):
        try:
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            try:
                code = ctypes.c_ulong()
                if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return True  # query error -> assume alive, do not reap
                return code.value == 259  # STILL_ACTIVE
            finally:
                k32.CloseHandle(h)
        except Exception:
            return True
    def _watch():
        misses = 0
        while True:
            time.sleep(5)
            if _alive(parent_pid):
                misses = 0
            else:
                misses += 1
                if misses >= 2:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    os._exit(0)
    threading.Thread(target=_watch, daemon=True).start()


def main(argv) -> int:
    if "--selfcheck" in argv:
        py = ensure_venv()
        print(str(py))  # selfcheck intentionally prints the venv python to stdout
        return 0

    if not argv:
        print("usage: mcp_launcher.py <target_script.py> [args...]", file=sys.stderr)
        return 2

    target, *rest = argv
    try:
        py = ensure_venv()
    except subprocess.CalledProcessError as e:
        print(f"[cinopsis] dependency bootstrap failed: {e}", file=sys.stderr, flush=True)
        return 1

    # Hand off: child inherits our stdin/stdout/stderr so MCP I/O is direct.
    if sys.platform == "win32":
        proc = subprocess.Popen([str(py), str(target), *rest])
        _bind_kill_on_close(proc.pid)
        _start_parent_watchdog(proc)
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            return 130
    proc = subprocess.run([str(py), str(target), *rest])
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
