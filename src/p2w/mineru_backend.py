"""Drive MinerU to produce content_list.json plus extracted images.

MinerU is an end-to-end document-parsing VLM: layout, CJK OCR, formula LaTeX and
table HTML in one pass.

In development it lives in .venv-mineru at the project root (its own torch stack,
isolated from the main environment); packaged builds share Resources/payload/python.
Either way it runs as a subprocess, with the command prefix from mineru_cmd().
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Callable

from .config import ConvertOptions

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# Process groups: POSIX uses setsid so killpg reaches grandchildren; Windows
# uses CREATE_NEW_PROCESS_GROUP plus taskkill /T for the same effect.
_POSIX = os.name == "posix"


def group_kwargs() -> dict:
    """Popen kwargs that put the child in its own process group."""
    if _POSIX:
        return {"start_new_session": True}
    return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}


def kill_tree(proc) -> None:
    """Kill the whole tree; killing only the parent orphans GPU-holding children."""
    try:
        if _POSIX:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class Cancelled(RuntimeError):
    """User pressed stop."""


class OCRBackendError(RuntimeError):
    """Recognition failed. `detail` keeps the raw engine output for the error
    log; str(exc) is the human-readable line shown in the UI."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


def find_mineru() -> str | None:
    """Locate the mineru executable: env var > project venv > PATH."""
    venv = _PROJECT_ROOT / ".venv-mineru"
    for c in (os.environ.get("P2W_MINERU"),
              str(venv / "bin" / "mineru"),
              str(venv / "Scripts" / "mineru.exe"),   # Windows venv layout
              shutil.which("mineru")):
        if c and Path(c).exists():
            return c
    return None


def _bundled_python() -> str | None:
    """Bundled interpreter, passed by the shell as P2W_MINERU_PYTHON."""
    py = os.environ.get("P2W_MINERU_PYTHON")
    return py if py and Path(py).exists() else None


def _bundled_has_mineru(py: str) -> bool:
    """Whether the bundled environment actually contains mineru.

    Checking the interpreter alone would report a local engine that is not there
    and let the UI offer local recognition. Probing site-packages is far cheaper
    than spawning `python -c "import mineru"`.
    """
    # POSIX interpreters sit in <root>/bin, Windows ones directly in <root>,
    # and the two lay site-packages out differently. Probing only the POSIX
    # shape reported "no local engine" on Windows even with mineru bundled.
    exe_dir = Path(py).resolve().parent
    root = exe_dir.parent if exe_dir.name.lower() in ("bin", "scripts") else exe_dir
    return (any(root.glob("lib/python*/site-packages/mineru"))
            or (root / "Lib" / "site-packages" / "mineru").is_dir())


def mineru_cmd(module: str = "mineru.cli.client") -> list[str] | None:
    """Command prefix for invoking MinerU.

    With a bundled interpreter use `python -m mineru.cli.*`: pip-generated
    console scripts hard-code the build machine's path in their shebang and
    break on other machines. Otherwise fall back to the dev executable.
    """
    py = _bundled_python()
    if py:
        return [py, "-m", module] if _bundled_has_mineru(py) else None
    exe = find_mineru()
    if not exe:
        return None
    # Dev environment uses the venv scripts: client -> mineru, fast_api -> mineru-api
    script = Path(exe).with_name("mineru" if module.endswith("client") else "mineru-api")
    return [str(script)] if script.exists() else None


class MineruServer:
    """Resident mineru-api service shared across a batch.

    Without it the CLI spawns a throwaway service and reloads the 1.2B model for
    every file, wasting ~12s each. Failure to start degrades to per-file loading.
    """

    def __init__(self, opts: ConvertOptions):
        self.opts = opts
        self.proc: subprocess.Popen | None = None
        self.workdir: str | None = None
        self.url = opts.api_url or f"http://{opts.api_host}:{opts.api_port}"

    def _ready(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/docs", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def start(self, timeout: int = 180) -> str | None:
        """Return a usable api_url, or None so the caller can degrade."""
        if self.opts.api_url or self._ready():
            return self.url  # external service already running

        cmd = mineru_cmd("mineru.cli.fast_api")
        if not cmd:
            return None

        # mineru copies every request's input into <cwd>/output/<uuid>/uploads/
        # and never cleans up, so give it a private temp directory.
        self.workdir = tempfile.mkdtemp(prefix="p2w_mineru_")
        self.proc = subprocess.Popen(
            cmd + ["--host", self.opts.api_host, "--port", str(self.opts.api_port),
                   "--enable-vlm-preload", "true"],
            env=dict(os.environ, MINERU_DEVICE_MODE=self.opts.device),
            cwd=self.workdir,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._ready():
                return self.url
            if self.proc.poll() is not None:  # process died, stop waiting
                self.proc = None
                return None
            time.sleep(2)
        self.stop()
        return None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        if self.workdir:
            shutil.rmtree(self.workdir, ignore_errors=True)
            self.workdir = None

    def __enter__(self) -> str | None:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def run_mineru(input_path: str | Path, output_dir: str | Path,
               opts: ConvertOptions | None = None,
               should_cancel: Callable[[], bool] | None = None) -> tuple[Path, Path]:
    """Recognize one file (PDF or image); returns (content_list.json, image dir).

    should_cancel() returning True kills the subprocess immediately.

    No intra-file progress is reported: the engine's output is full of "1/1" and
    "batch 1/1" pairs that are not page counters, so scraping them yields bogus
    percentages. Progress is only meaningful per file.
    """
    opts = opts or ConvertOptions()
    if opts.use_cloud:
        # Routing lives here rather than in callers: the hybrid path, parallel
        # split and batch conversion all funnel through this function.
        from .mineru_cloud import run_cloud
        return run_cloud(input_path, output_dir, opts, should_cancel)

    base = mineru_cmd()
    if not base:
        raise OCRBackendError(
            "找不到 mineru，请先安装：uv venv .venv-mineru && "
            "VIRTUAL_ENV=.venv-mineru uv pip install 'mineru[core]'")

    # Absolute paths required: cwd is set below, so relative paths would resolve there.
    input_path = Path(input_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ, MINERU_DEVICE_MODE=opts.device)
    cmd = base + ["-p", str(input_path), "-o", str(output_dir), "-b", opts.mineru_backend]
    if opts.api_url:  # reuse the resident service instead of reloading the model
        cmd += ["--api-url", opts.api_url]
    # cwd points at output_dir so mineru's scratch files stay out of the user's cwd.
    code, tail = _run_streaming(cmd, env, opts.timeout_sec, cwd=str(output_dir),
                                should_cancel=should_cancel)
    if code != 0:
        # No filename prefix: both CLI and GUI already display it alongside.
        raise OCRBackendError(_explain_failure(tail), detail="\n".join(tail))

    hits = sorted(output_dir.rglob("*_content_list.json"))
    if not hits:
        raise OCRBackendError(f"mineru 没有产出 content_list.json：{input_path.name}")
    return hits[0], hits[0].parent


# MinerU failures come as a traceback plus JSON, which is meaningless to an end
# user. Condense to one line and keep the raw text in the error log.
_ERR_JSON = re.compile(r'"error"\s*:\s*"([^"]+)"')
_ERR_LINE = re.compile(r"^(?:Error|RuntimeError|ValueError|OSError):\s*(.+)$")
_ERR_HINTS = (
    ("Truncated File Read", "文件不完整，可能没下载完或已损坏"),
    ("Data format error", "文件格式有问题，打不开"),
    ("password", "文件已加密，需要密码"),
    ("No supported documents", "这个文件识别引擎不认，可能是空文件或格式不对"),
    ("out of memory", "内存不够，试试关掉其他程序或分批转换"),
    ("Connection refused", "识别服务没连上，请重试"),
)


def _explain_failure(tail: list[str]) -> str:
    blob = "\n".join(tail)
    for needle, human in _ERR_HINTS:
        if needle.lower() in blob.lower():
            return human
    for line in reversed(tail):  # no hint matched: use the engine's own last error
        m = _ERR_JSON.search(line) or _ERR_LINE.match(line.strip())
        if m:
            return m.group(1).strip()[:160]
    return "识别失败，请检查文件是否完整"


def _run_streaming(cmd: list[str], env: dict, timeout: int,
                   cwd: str | None = None,
                   should_cancel: Callable[[], bool] | None = None) -> tuple[int, list[str]]:
    """跑子进程，边跑边收尾部输出；返回 (退出码, 最后若干行) 供报错用。

    tqdm 走 stderr 且用 \\r 刷新，所以按 \\r/\\n 都切行读。
    """
    deadline = time.monotonic() + timeout
    # Own process group so cancellation reaches the engine's children.
    proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1, errors="replace",
                            **group_kwargs())
    tail: deque[str] = deque(maxlen=12)
    assert proc.stdout is not None
    for chunk in iter(proc.stdout.readline, ""):
        for line in re.split(r"[\r\n]", chunk):
            line = line.strip()
            if not line:
                continue
            tail.append(line)
        if should_cancel and should_cancel():
            _kill_group(proc)
            raise Cancelled("已停止")
        if time.monotonic() > deadline:
            _kill_group(proc)
            raise OCRBackendError(f"mineru 超时（>{timeout}s）")
    proc.wait()
    return proc.returncode, list(tail)


def _kill_group(proc: subprocess.Popen) -> None:
    """连同子进程拉起的孙子进程一起杀——识别引擎会自己 spawn 服务进程，
    只 kill 父进程的话它们会变孤儿继续占着显存。

    Windows has no killpg; kill_tree() shells out to `taskkill /T` instead."""
    kill_tree(proc)
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def load_content_list(json_path: str | Path) -> list:
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)
