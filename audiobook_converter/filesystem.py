"""Filesystem helpers for locks, filenames, and disk-space errors."""
from __future__ import annotations

import errno
import logging
import os
import re
from pathlib import Path

from .constants import INVALID_FILENAME_CHARS
from .errors import DiskSpaceError, LockError

WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{number}" for number in range(1, 10)), *(f"LPT{number}" for number in range(1, 10))}

class LockFile:
    """Small cross-platform lock file based on exclusive file creation."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._fd: int | None = None

    def acquire(self) -> None:
        """Create the lock file or raise LockError if it already exists."""

        try:
            self._fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._fd, f"pid={os.getpid()}\n".encode("utf-8"))
        except FileExistsError as exc:
            raise LockError(f"Another instance appears to be running: {self.lock_path}") from exc

    def release(self) -> None:
        """Close and remove the lock file, ignoring cleanup failures."""

        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            logging.exception("Failed to remove lock file: %s", self.lock_path)

    def __enter__(self) -> "LockFile":
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.release()

def is_disk_space_error(exc_or_message: BaseException | str) -> bool:
    """Return True when an exception or command output indicates disk exhaustion."""

    if isinstance(exc_or_message, OSError) and exc_or_message.errno == errno.ENOSPC:
        return True

    message = str(exc_or_message).casefold()
    disk_space_markers = (
        "no space left on device",
        "disk full",
        "not enough space",
        "insufficient disk space",
        "enospc",
        "write error",
    )
    return any(marker in message for marker in disk_space_markers)

def sanitize_filename(value: str) -> str:
    """Remove characters that are invalid or troublesome on Windows/Linux."""

    cleaned = "".join(" " if char in INVALID_FILENAME_CHARS else char for char in value)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if not cleaned:
        cleaned = "Untitled"
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned[:180]
