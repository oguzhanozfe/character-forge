"""Machine-wide named locks: exclusive, re-entrant per owner, never steal a live holder, reclaim dead ones."""
import json
import subprocess
import sys
import time

import pytest

from character_forge import lock


def test_acquire_release_and_reentrancy(tmp_path):
    a = lock.NamedLock(tmp_path, "gpu", "worker-a")
    path = a.acquire(timeout=1)
    assert path.is_dir() and json.loads((path / "owner.json").read_text())["owner"] == "worker-a"
    assert a.acquire(timeout=1) == path                       # same owner, same host: re-entrant
    a.heartbeat()
    a.release()
    assert not path.exists()


def test_second_owner_times_out_without_touching_the_holder(tmp_path):
    a = lock.NamedLock(tmp_path, "gpu", "worker-a")
    a.acquire(timeout=1)
    b = lock.NamedLock(tmp_path, "gpu", "worker-b")
    started = time.monotonic()
    with pytest.raises(lock.LockTimeout):
        b.acquire(timeout=0.3, poll=0.05)
    assert time.monotonic() - started < 5
    assert a.info()["owner"] == "worker-a"                   # holder untouched
    with pytest.raises(PermissionError):
        b.release()
    with pytest.raises(PermissionError):
        b.heartbeat()


def test_dead_holder_is_reclaimed(tmp_path):
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    dead = lock.NamedLock(tmp_path, "gpu", "crashed", pid=child.pid)
    dead.acquire(timeout=1)
    messages = []
    fresh = lock.NamedLock(tmp_path, "gpu", "worker-b")
    fresh.acquire(timeout=2, poll=0.05, log=messages.append)
    assert fresh.info()["owner"] == "worker-b" and "gone" in messages[0]


def test_stale_heartbeat_of_live_process_is_not_stolen(tmp_path):
    holder = lock.NamedLock(tmp_path, "gpu", "slow-but-alive", stale_seconds=1)
    holder.acquire(timeout=1)
    info = holder.info()
    info["heartbeat"] = time.time() - 3600                  # very old heartbeat, but this process is alive
    (holder.path / "owner.json").write_text(json.dumps(info))
    other = lock.NamedLock(tmp_path, "gpu", "impatient", stale_seconds=1)
    assert other.reclaimable(holder.info()) is None
    with pytest.raises(lock.LockTimeout):
        other.acquire(timeout=0.2, poll=0.05)


def test_stale_lock_from_another_host_is_reclaimed(tmp_path):
    holder = lock.NamedLock(tmp_path, "gpu", "remote")
    holder.acquire(timeout=1)
    info = holder.info()
    info.update(host="some-other-machine", heartbeat=time.time() - 10 * 3600)
    (holder.path / "owner.json").write_text(json.dumps(info))
    other = lock.NamedLock(tmp_path, "gpu", "local", stale_seconds=3600)
    other.acquire(timeout=1, poll=0.05)
    assert other.info()["owner"] == "local"


def test_bbfps_style_lock_without_host_is_respected(tmp_path):
    (tmp_path / "gpu.lock").mkdir(parents=True)
    import os
    (tmp_path / "gpu.lock" / "owner.json").write_text(json.dumps({"owner": "W1", "pid": os.getpid(), "since": time.time(),
                                                                    "heartbeat": time.time()}))
    with pytest.raises(lock.LockTimeout):
        lock.NamedLock(tmp_path, "gpu", "forge").acquire(timeout=0.2, poll=0.05)


def test_held_context_and_status(tmp_path):
    with lock.held(tmp_path, "unity-batch", "job", heartbeat_every=0.05) as held:
        time.sleep(0.15)
        rows = lock.status(tmp_path)
        assert rows[0]["name"] == "unity-batch" and rows[0]["owner"] == "job"
        assert held.info()["heartbeat"] >= held.info()["since"]
    assert lock.status(tmp_path) == []


def test_invalid_names(tmp_path):
    with pytest.raises(ValueError):
        lock.NamedLock(tmp_path, "../gpu", "x")
    with pytest.raises(ValueError):
        lock.NamedLock(tmp_path, "gpu", "")


def test_cli_lock_roundtrip(forge):
    assert forge("lock", "acquire", "gpu", "--owner", "me", "--timeout", "1")[0] == 0
    code, out = forge("lock", "status")
    assert "gpu" in out and "owner=me" in out
    assert forge("lock", "acquire", "gpu", "--owner", "someone-else", "--timeout", "0.2")[0] == 3
    assert forge("lock", "release", "gpu", "--owner", "me")[0] == 0
    assert "no locks held" in forge("lock", "status")[1]
