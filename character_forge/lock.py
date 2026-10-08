"""Machine-wide named locks for a single-GPU queue (and other exclusive slots such as a Unity batch slot).

Port of BBFPS `shared_lock.py` with the safety changes its research review asked for:
  * owner identity = owner name + host + pid; a renewable lease via heartbeats;
  * a stale heartbeat alone never steals a lock whose process is still alive on this host;
  * timeouts are non-destructive: the waiter gives up, the holder is never stopped or deleted.

On-disk format stays compatible: <lock_root>/<name>.lock/owner.json written after an atomic mkdir.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path


def pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: exists but not ours
        try:
            code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class LockTimeout(Exception):
    pass


class NamedLock:
    def __init__(self, root, name, owner, pid=None, stale_seconds=3 * 3600):
        if not name or not owner or any(c in name for c in "/\\:"):
            raise ValueError("Lock name and owner are required; name must not contain path separators")
        self.root = Path(root)
        self.name = name
        self.owner = owner
        self.pid = pid if pid is not None else os.getpid()
        self.host = socket.gethostname()
        self.stale_seconds = stale_seconds

    @property
    def path(self) -> Path:
        return self.root / (self.name + ".lock")

    def info(self):
        try:
            return json.loads((self.path / "owner.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, info):
        temporary = self.path / "owner.json.tmp"
        temporary.write_text(json.dumps(info), encoding="utf-8")
        os.replace(temporary, self.path / "owner.json")

    def reclaimable(self, info):
        """Return a reason string if the existing lock may be reclaimed, else None."""
        if not info:
            # A just-created directory may not have its owner file yet; only reclaim if it is old.
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                return "vanished"
            return "empty lock older than 60 s" if age > 60 else None
        age = time.time() - float(info.get("heartbeat", 0))
        same_host = info.get("host", self.host) == self.host
        pid = int(info.get("pid", 0) or 0)
        if same_host and pid and not pid_alive(pid):
            return "holder process %d is gone" % pid
        if age > self.stale_seconds:
            if same_host and pid and pid_alive(pid):
                return None  # stale heartbeat but live process: never steal
            return "heartbeat %.0f s old on %s" % (age, info.get("host", "?"))
        return None

    def acquire(self, timeout=7200.0, poll=5.0, log=None):
        self.root.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + timeout
        while True:
            try:
                os.mkdir(self.path)
                now = time.time()
                self._write({"owner": self.owner, "host": self.host, "pid": self.pid, "since": now, "heartbeat": now,
                             "lease_seconds": self.stale_seconds})
                return self.path
            except FileExistsError:
                info = self.info()
                if info.get("owner") == self.owner and info.get("host", self.host) == self.host:
                    self.heartbeat()
                    return self.path
                reason = self.reclaimable(info)
                if reason:
                    if log:
                        log("reclaiming lock %s: %s" % (self.name, reason))
                    shutil.rmtree(self.path, ignore_errors=True)
                    continue
                if time.time() >= deadline:
                    raise LockTimeout("Timed out waiting for lock %s (held by %s pid %s); nothing was stopped." % (
                        self.name, info.get("owner"), info.get("pid")))
                time.sleep(poll)

    def heartbeat(self):
        info = self.info()
        if info.get("owner") != self.owner:
            raise PermissionError("Not the owner of lock %s (held by %s)" % (self.name, info.get("owner")))
        info["heartbeat"] = time.time()
        self._write(info)

    def release(self):
        info = self.info()
        if info and info.get("owner") != self.owner:
            raise PermissionError("Not the owner of lock %s (held by %s)" % (self.name, info.get("owner")))
        shutil.rmtree(self.path, ignore_errors=True)


@contextmanager
def held(root, name, owner, timeout=7200.0, heartbeat_every=60.0, log=None):
    """Hold a lock for the duration of a block, renewing the lease from a background thread."""
    lock = NamedLock(root, name, owner)
    lock.acquire(timeout=timeout, log=log)
    stop = threading.Event()

    def beat():
        while not stop.wait(heartbeat_every):
            try:
                lock.heartbeat()
            except (OSError, PermissionError):
                return

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield lock
    finally:
        stop.set()
        thread.join(timeout=5)
        try:
            lock.release()
        except PermissionError:
            pass


def status(root):
    root = Path(root)
    rows = []
    if not root.is_dir():
        return rows
    for entry in sorted(root.glob("*.lock")):
        try:
            info = json.loads((entry / "owner.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        rows.append({"name": entry.name[:-5], "owner": info.get("owner"), "host": info.get("host"), "pid": info.get("pid"),
                     "held_seconds": int(time.time() - float(info.get("since", time.time()))),
                     "heartbeat_age_seconds": int(time.time() - float(info.get("heartbeat", time.time())))})
    return rows
