"""Regression tests for the process-wide ORB bot lock."""
import os

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
