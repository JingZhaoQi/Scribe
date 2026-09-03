"""Persisted settings: recognition mode, cloud API key and export format.

Only these need to reach the backend; theme and similar UI preferences live in
localStorage. The key is a credential, so the file is chmod 0600 and only a
masked form is ever returned to the frontend.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_APP = "抄录"


def _config_dir() -> Path:
    """Per-platform location for the settings file."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / _APP
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / _APP


_DIR = _config_dir()
_FILE = _DIR / "settings.json"

_DEFAULT = {"engine": "local", "api_token": "", "export": "docx"}


def log_file() -> Path:
    """Where the backend records its output.

    A packaged build is started by the desktop shell, which on Windows is a GUI
    subsystem process and hands the child no console at all; without this file a
    startup traceback would go nowhere.
    """
    return _DIR / "backend.log"


def load() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return dict(_DEFAULT)
    out = dict(_DEFAULT)
    if data.get("engine") in ("local", "cloud"):
        out["engine"] = data["engine"]
    if isinstance(data.get("api_token"), str):
        out["api_token"] = data["api_token"].strip()
    if data.get("export") in ("docx", "md"):
        out["export"] = data["export"]
    return out


def save(engine: str | None = None, api_token: str | None = None,
         export: str | None = None) -> dict:
    cur = load()
    if engine in ("local", "cloud"):
        cur["engine"] = engine
    if api_token is not None:
        cur["api_token"] = api_token.strip()
    if export in ("docx", "md"):
        cur["export"] = export
    _DIR.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(_FILE, 0o600)
    except OSError:
        pass
    return cur


def local_available() -> bool:
    """Whether this build bundles a local recognition engine."""
    from p2w.mineru_backend import mineru_cmd
    return mineru_cmd() is not None


def effective_engine(cur: dict | None = None) -> str:
    """Engine actually in effect.

    A build without the local engine falls through to cloud even when the stored
    value is "local", so the default selection is never the unusable one.
    """
    cur = cur or load()
    if cur["engine"] == "local" and not local_available():
        return "cloud"
    return cur["engine"]


def public(cur: dict | None = None) -> dict:
    """Frontend-facing shape: reports whether a key exists, never its value.

    localAvailable tells the UI whether this build bundles a local engine, so
    the "local" option can be greyed out instead of failing at conversion time.
    """
    cur = cur or load()
    token = cur["api_token"]
    return {
        "engine": effective_engine(cur),
        "export": cur["export"],
        "hasToken": bool(token),
        "tokenHint": (token[:4] + "…" + token[-4:]) if len(token) >= 12 else ("已保存" if token else ""),
        "localAvailable": local_available(),
    }
