"""Blocking, process-shared locks for local filesystem storage."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time
from typing import Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def _acquire(descriptor: int) -> None:
    if os.name != "nt":
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return

    # LK_LOCK stops retrying after ten seconds. Use nonblocking attempts so a
    # long mutation retains the same indefinite waiting semantics as flock.
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            time.sleep(0.05)


def _release(descriptor: int) -> None:
    if os.name == "nt":
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Serialize threads and processes opening the same persistent lock file.

    Locks are not reentrant: callers must use different files for independently
    nested locks. Never delete the lock file while other callers may use it.
    POSIX file permissions are kept at 0600; Windows uses the parent's ACL.
    """
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        _acquire(descriptor)
        acquired = True
        yield
    finally:
        try:
            if acquired:
                _release(descriptor)
        finally:
            os.close(descriptor)
