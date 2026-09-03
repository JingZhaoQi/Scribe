"""Long-path support for Windows.

Windows rejects any path over 260 characters unless the caller opts in with the
``\\\\?\\`` extended-length prefix. Output directories are named after the source
file, so a book whose filename is already 140 characters pushes the .docx past
the limit and the write fails with a bare ``FileNotFoundError`` — the directory
gets created, nothing lands in it. Every path handed to open()/save()/mkdir()
goes through :func:`long_path` first.

On macOS and Linux these functions are pass-throughs.
"""

from __future__ import annotations

import os
from pathlib import Path

_WIN = os.name == "nt"
_PREFIX = "\\\\?\\"


def long_path(path: str | Path) -> str:
    """Path string that Win32 accepts regardless of length."""
    s = str(path)
    if not _WIN or s.startswith(_PREFIX):
        return s
    # The prefix disables all path normalization, so the path must already be
    # absolute and backslash-separated.
    s = os.path.abspath(s)
    if s.startswith("\\\\"):        # UNC share: \\host\share -> \\?\UNC\host\share
        return _PREFIX + "UNC" + s[1:]
    return _PREFIX + s


def make_dirs(path: str | Path) -> Path:
    """``mkdir -p`` that survives long paths; returns the unprefixed Path."""
    p = Path(path)
    os.makedirs(long_path(p), exist_ok=True)
    return p


def exists(path: str | Path) -> bool:
    """Existence check that does not silently answer False on a long path."""
    return os.path.exists(long_path(path))
