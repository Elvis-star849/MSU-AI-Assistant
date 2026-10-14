"""
Single-writer lock: knowledge_base/.lock, created exclusively (O_CREAT | O_EXCL).

A lock left by a process that no longer exists on this host is stale and is released automatically (and reported).
A lock held by a live process, or by another host, raises LockedError; `kb unlock --force` (kb_admin) removes it.
"""
import json
import os
import socket
import sys
from pathlib import Path
from typing import Optional

from src.kb.errors import LockedError


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5      # access denied: the process exists
        try:
            code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)                              # POSIX only: signal 0 checks existence
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock(path: Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValueError, OSError):
        return {"pid": -1, "host": "?", "unreadable": True}


class WriterLock:
    def __init__(self, path: Path, operation: str, actor: str, now: str):
        self.path = Path(path)
        self.info = {"pid": os.getpid(), "host": socket.gethostname(), "operation": operation, "actor": actor,
                     "since": now}
        self.released_stale: Optional[dict] = None

    def acquire(self) -> "WriterLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                holder = read_lock(self.path)
                if holder is None:
                    continue
                same_host = holder.get("host") == self.info["host"]
                if same_host and not holder.get("unreadable") and not pid_alive(int(holder.get("pid", -1))):
                    self.released_stale = holder
                    os.remove(self.path)
                    continue
                raise LockedError(f"knowledge base is locked by {holder}")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.info, f)
                f.flush()
                os.fsync(f.fileno())
            return self
        raise LockedError("could not acquire the knowledge-base lock")

    def release(self) -> None:
        holder = read_lock(self.path)
        if holder and holder.get("pid") == self.info["pid"] and holder.get("host") == self.info["host"]:
            os.remove(self.path)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


def force_unlock(path: Path) -> Optional[dict]:
    holder = read_lock(path)
    if holder is not None:
        os.remove(path)
    return holder
