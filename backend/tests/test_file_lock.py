from __future__ import annotations

import errno
import multiprocessing
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from xraylarch_web import file_lock, integration_storage
from xraylarch_web.integration_storage import IntegrationStorage
from xraylarch_web.storage import WorkspaceStorage


WORKSPACE = "workspace-identifier-1"


def _lock(root: Path, kind: str):
    if kind == "workspace":
        return WorkspaceStorage(root).lock(WORKSPACE)
    if kind == "integration":
        return IntegrationStorage(root, integration_secret="test-secret")._lock("test")
    return file_lock.exclusive_file_lock(root / "test.lock")


def _contend(root, kind, attempted, acquired):
    lock = _lock(root, kind)
    attempted.set()
    with lock:
        acquired.set()


@pytest.mark.parametrize("kind", ["file", "workspace", "integration"])
@pytest.mark.parametrize("worker_kind", ["thread", "process"])
def test_storage_lock_excludes_other_threads_and_processes(tmp_path, kind, worker_kind):
    if kind == "workspace":
        WorkspaceStorage(tmp_path).workspace_dir(WORKSPACE, create=True)
    context = multiprocessing.get_context("spawn") if worker_kind == "process" else threading
    attempted, acquired = context.Event(), context.Event()
    worker_type = context.Process if worker_kind == "process" else context.Thread
    worker = worker_type(target=_contend, args=(tmp_path, kind, attempted, acquired), daemon=True)
    try:
        with _lock(tmp_path, kind):
            worker.start()
            assert attempted.wait(15), "The competing worker did not start."
            assert not acquired.wait(0.2), "The competing worker entered a held lock."
        assert acquired.wait(15), "The competing worker did not acquire the released lock."
        worker.join(15)
        assert not worker.is_alive()
        if worker_kind == "process":
            assert worker.exitcode == 0
    finally:
        if worker_kind == "process" and worker.is_alive():
            worker.terminate()
            worker.join(5)


def test_exception_in_locked_body_releases_lock(tmp_path):
    with pytest.raises(ValueError, match="failed mutation"):
        with file_lock.exclusive_file_lock(tmp_path / "test.lock"):
            raise ValueError("failed mutation")
    attempted, acquired = threading.Event(), threading.Event()
    worker = threading.Thread(target=_contend, args=(tmp_path, "file", attempted, acquired), daemon=True)
    worker.start()
    assert acquired.wait(5)
    worker.join(5)


def test_failed_acquisition_closes_descriptor_without_unlocking(tmp_path, monkeypatch):
    descriptors, releases = [], []

    def fail(descriptor):
        descriptors.append(descriptor)
        raise OSError(errno.EIO, "failed acquisition")

    monkeypatch.setattr(file_lock, "_acquire", fail)
    monkeypatch.setattr(file_lock, "_release", releases.append)
    with pytest.raises(OSError, match="failed acquisition"):
        with file_lock.exclusive_file_lock(tmp_path / "test.lock"):
            pytest.fail("An unacquired lock must not run the mutation.")
    assert releases == []
    with pytest.raises(OSError) as error:
        os.fstat(descriptors[0])
    assert error.value.errno == errno.EBADF


def test_lock_does_not_require_posix_fchmod(tmp_path, monkeypatch):
    portable_os = SimpleNamespace(**{name: getattr(os, name) for name in (
        "name", "open", "close", "O_CREAT", "O_RDWR", "lseek", "SEEK_SET",
    )})
    monkeypatch.setattr(file_lock, "os", portable_os)
    with file_lock.exclusive_file_lock(tmp_path / "test.lock"):
        assert (tmp_path / "test.lock").exists()


def test_windows_lock_waits_past_ten_conflicts_and_unlocks_same_byte(tmp_path, monkeypatch):
    descriptor = os.open(tmp_path / "test.lock", os.O_CREAT | os.O_RDWR, 0o600)
    calls, sleeps = [], []
    os.lseek(descriptor, 7, os.SEEK_SET)

    def locking(fd, mode, length):
        calls.append((mode, length, os.lseek(fd, 0, os.SEEK_CUR)))
        if mode == 1 and len(calls) <= 12:
            raise OSError(errno.EACCES, "held by another process")

    monkeypatch.setattr(file_lock, "os", SimpleNamespace(name="nt", lseek=os.lseek, SEEK_SET=os.SEEK_SET))
    monkeypatch.setattr(file_lock, "msvcrt", SimpleNamespace(locking=locking, LK_NBLCK=1, LK_UNLCK=2), raising=False)
    monkeypatch.setattr(file_lock.time, "sleep", sleeps.append)
    try:
        file_lock._acquire(descriptor)
        os.lseek(descriptor, 9, os.SEEK_SET)
        file_lock._release(descriptor)
    finally:
        os.close(descriptor)
    assert calls == [(1, 1, 0)] * 13 + [(2, 1, 0)]
    assert len(sleeps) == 12


def test_windows_lock_propagates_unexpected_io_failure(tmp_path, monkeypatch):
    descriptor = os.open(tmp_path / "test.lock", os.O_CREAT | os.O_RDWR, 0o600)

    def fail(fd, mode, length):
        raise OSError(errno.EBADF, "invalid descriptor")

    monkeypatch.setattr(file_lock, "os", SimpleNamespace(name="nt", lseek=os.lseek, SEEK_SET=os.SEEK_SET))
    monkeypatch.setattr(file_lock, "msvcrt", SimpleNamespace(locking=fail, LK_NBLCK=1), raising=False)
    try:
        with pytest.raises(OSError, match="invalid descriptor"):
            file_lock._acquire(descriptor)
    finally:
        os.close(descriptor)


def test_windows_directory_sync_does_not_open_directory(tmp_path, monkeypatch):
    # The Windows CRT has no directory descriptor that os.fsync can consume.
    monkeypatch.setattr(integration_storage, "os", SimpleNamespace(name="nt"))
    IntegrationStorage._fsync_directory(tmp_path)
