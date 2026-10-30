"""Regression tests for the process-wide ORB bot lock."""
import os
import subprocess
import sys

import bot


def test_lock_blocks_second_instance_and_releases_after_owner_closes(tmp_path, monkeypatch):
    lock_path = tmp_path / "orb-test.lock"
    monkeypatch.setenv("ORB_LOCK_FILE", str(lock_path))
    monkeypatch.setattr(bot, "_INSTANCE_LOCK_FD", None)

    assert bot.acquire_instance_lock() is True
    owner_fd = bot._INSTANCE_LOCK_FD
    assert owner_fd is not None

    # A second open file description in the same process must still be blocked.
    assert bot.acquire_instance_lock() is False
    assert bot._INSTANCE_LOCK_FD == owner_fd

    # Simulate process exit by closing the descriptor that owns the flock.
    os.close(owner_fd)
    monkeypatch.setattr(bot, "_INSTANCE_LOCK_FD", None)

    # The lock file may remain; the kernel lock must be released.
    assert lock_path.exists()
    assert bot.acquire_instance_lock() is True

    replacement_fd = bot._INSTANCE_LOCK_FD
    assert replacement_fd is not None
    os.close(replacement_fd)
    monkeypatch.setattr(bot, "_INSTANCE_LOCK_FD", None)



def test_lock_excludes_a_real_second_process_and_releases_on_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "_INSTANCE_LOCK_FD", None)
    lock_path = tmp_path / "orb-subprocess.lock"
    env = os.environ.copy()
    env["ORB_LOCK_FILE"] = str(lock_path)
    script = (
        "import time, bot; "
        "assert bot.acquire_instance_lock(); "
        "print('LOCKED', flush=True); "
        "time.sleep(30)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        monkeypatch.setenv("ORB_LOCK_FILE", str(lock_path))
        assert bot.acquire_instance_lock() is False
    finally:
        child.terminate()
        child.wait(timeout=5)

    # The OS releases flock automatically when the owning process exits.
    assert bot.acquire_instance_lock() is True
    os.close(bot._INSTANCE_LOCK_FD)
    bot._INSTANCE_LOCK_FD = None
