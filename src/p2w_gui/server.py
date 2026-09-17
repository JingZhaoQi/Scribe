"""FastAPI backend for the Tauri front-end.

Exposes the p2w conversion pipeline over local HTTP; Tauri launches this as a
sidecar and the web UI calls it via fetch. File dialogs, window controls and
"open file/folder" live in the Tauri front-end (native APIs), not here -- this
service only manages conversion state and runs the pipeline.

Run:  python -m p2w_gui.server [port]   (default 8756)
"""

from __future__ import annotations

import sys
import threading
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from p2w.config import ConvertOptions
from p2w_gui import settings
from p2w.normalize import is_pdf, is_supported
from p2w.pipeline import convert_file

_REASON_HINT = {
    "formula_check": "识别的公式，已转为 Word 原生公式，请对照原卷核对。",
    "low_confidence": "识别置信度较低，请核对。",
    "conversion_failed": "公式转换失败，已降级为可编辑文本，请手动修正。",
    "table_check": "识别的表格，行列与数字最容易看串，请对照原件核对。",
}

# Per-file progress contract the frontend renders:
# queued 5 -> ocr 10 (climbs to ~81 by elapsed time, see _live_progress)
# -> parse 85 -> render 90 -> done 100
_PHASE_STATUS = {
    "check": ("ocr", 10),
    "ocr": ("ocr", 10),
    "parse": ("parse", 85),
    "render": ("gen", 90),
}
# States a file can be in mid-conversion, reset on cancel or error.
_MID_STATUSES = ("queued", "ocr", "parse", "gen", "pending")

# The engine reports no page-level progress, so the ocr stage is estimated from
# elapsed time over expected time. Expected time uses seconds-per-page measured
# from files already converted this session, per engine: cloud runs on remote
# GPUs and is an order of magnitude faster, so the two must never share a value.
_DEFAULT_SPP = {"local": 75.0, "cloud": 6.0}


def _human_size(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _pdf_pages(path: str) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(path).pages)
    except Exception:
        return 0


class ConvertManager:
    """Holds the file list + conversion state; runs the batch on a thread."""

    def __init__(self):
        self._files: dict[int, dict] = {}
        self._id = 0
        self._output_dir = str(Path.home() / "p2w_output")
        self._last_output_dir: str | None = None
        self._lock = threading.Lock()
        self._running = False
        self._cancel = False
        self._durations: list[float] = []   # per-file wall time, for ETA
        self._cur_started: float | None = None
        self._cur_pages = 1                  # page count of the current file
        self._engine = "local"               # engine used by this batch
        self._speed: dict[str, list] = {}    # engine -> [total secs, total pages]
        self._server = None                  # resident MineruServer of the running batch

    def add(self, path: str) -> dict | None:
        p = Path(path)
        if not (p.is_file() and is_supported(p)):
            return None
        if any(r["path"] == str(p) for r in self._files.values()):
            return None
        self._id += 1
        rec = {
            "id": self._id, "name": p.name,
            "type": "pdf" if is_pdf(p) else "img",
            "pages": _pdf_pages(str(p)) if is_pdf(p) else 1,
            "size": _human_size(p.stat().st_size), "path": str(p),
            "status": "pending", "progress": 0,
            "reviewNote": None, "errNote": None,
            "review_items": [], "docx": None, "report": None, "output_dir": None,
        }
        self._files[self._id] = rec
        return rec

    def add_folder(self, folder: str) -> list[dict]:
        out = []
        for f in sorted(Path(folder).rglob("*")):
            if f.is_file() and is_supported(f):
                rec = self.add(str(f))
                if rec:
                    out.append(self.public(rec))
        return out

    def public(self, rec: dict) -> dict:
        out = {k: rec[k] for k in
               ("id", "name", "type", "pages", "size", "status", "progress", "reviewNote", "errNote")}
        # Output type drives the frontend button label (Word vs Markdown).
        out["outExt"] = (rec.get("docx") or "").rsplit(".", 1)[-1] if rec.get("docx") else ""
        return out

    def remove(self, fid: int):
        self._files.pop(int(fid), None)

    def clear(self) -> bool:
        if self._running:
            return False
        self._files.clear()
        return True

    def stop(self) -> bool:
        """Stop now: kill the running subprocess, requeue the remaining files."""
        if not self._running:
            return False
        self._cancel = True
        return True

    def start(self, ids, opts) -> bool:
        if self._running:
            return False
        self._cancel = False
        self._durations = []
        self._cur_started = None
        opts = opts or {}
        # MinerU is end-to-end: language, formulas and quality are not tunable.
        co = ConvertOptions()
        # Only supply the key when cloud is selected, so a stored key never
        # silently uploads files after the user switched back to local.
        cfg = settings.load()
        self._engine = settings.effective_engine(cfg)
        if self._engine == "cloud" and cfg["api_token"]:
            co.api_token = cfg["api_token"]
        co.export_format = cfg.get("export", "docx")
        ids = [int(i) for i in (ids or [])]
        with self._lock:
            for fid in ids:
                rec = self._files.get(fid)
                # Include errors so a failed file can be retried in place.
                if rec and rec["status"] not in ("done", "review"):
                    rec["status"] = "queued"
                    rec["progress"] = 5
                    rec["errNote"] = None
                    rec.pop("_real_prog", None)
        self._running = True
        threading.Thread(target=self._run, args=(ids, co, opts), daemon=True).start()
        return True

    def _resolve_output_dir(self, rec: dict, co: ConvertOptions, opts: dict) -> Path:
        if opts.get("outDir") == "custom":
            return Path(self._output_dir)
        # Name the directory after the source file, so several conversions in
        # one folder stay distinguishable.
        src = Path(rec["path"])
        return src.parent / f"{src.stem}{co.output_subdir}"

    def _run(self, ids, co: ConvertOptions, opts: dict):
        from p2w.mineru_backend import MineruServer

        # Share one resident service across a batch; failure to start degrades
        # to per-file loading rather than failing the batch.
        pending = [i for i in ids if (self._files.get(i) or {}).get("status") not in ("done", "review")]
        server = MineruServer(co) if len(pending) > 1 and not co.use_cloud else None
        self._server = server  # tracked so the parent watchdog can stop it on the way out
        if server:
            co.api_url = server.start()
        try:
            with self._lock:  # first pending file goes straight to "ocr"
                for fid in ids:
                    rec = self._files.get(fid)
                    if rec and rec["status"] not in ("done", "review"):
                        rec["status"] = "ocr"
                        rec["progress"] = 10
                        break
            for fid in ids:
                if self._cancel:  # user stopped: requeue whatever is left
                    with self._lock:
                        for rest in ids:
                            r = self._files.get(rest)
                            if r and r["status"] in _MID_STATUSES:
                                r["status"] = "pending"
                                r["progress"] = 0
                    break
                rec = self._files.get(fid)
                if not rec or rec["status"] in ("done", "review"):
                    continue
                import time as _t
                started = _t.monotonic()
                with self._lock:
                    self._cur_started = started
                    self._cur_pages = max(1, rec["pages"])

                def _on_phase(phase: str, rec=rec) -> None:
                    # "ocr:3/9" is real page progress from parallel mode;
                    # _real_prog stops the time-based estimate from overriding it.
                    if phase.startswith("ocr:"):
                        try:
                            d, t = phase[4:].split("/")
                            pct = min(81, 10 + int(71 * int(d) / max(1, int(t))))
                        except ValueError:
                            return
                        with self._lock:
                            rec["status"], rec["progress"] = "ocr", pct
                            rec["_real_prog"] = True
                        return
                    st = _PHASE_STATUS.get(phase)
                    if st is None:
                        return
                    with self._lock:
                        rec["status"], rec["progress"] = st
                output_dir = self._resolve_output_dir(rec, co, opts)
                output_dir.mkdir(parents=True, exist_ok=True)
                with self._lock:
                    rec["output_dir"] = str(output_dir)
                    self._last_output_dir = str(output_dir)

                res = convert_file(
                    rec["path"], output_dir, co,
                    overwrite=opts.get("dup") == "overwrite",
                    should_cancel=lambda: self._cancel,
                    on_phase=_on_phase,
                )
                with self._lock:
                    dur = _t.monotonic() - started
                    self._durations.append(dur)
                    self._cur_started = None
                    if res.cancelled:
                        rec["status"] = "pending"
                        rec["progress"] = 0
                        continue
                    rec["progress"] = 100
                    if not res.ok:
                        rec["status"] = "error"
                        rec["errNote"] = res.error or "转换失败"
                    else:
                        # Learn seconds-per-page only from files that actually
                        # ran the model: text-layer hits finish in 0.2s and would
                        # drag the estimate to near zero.
                        if not res.used_text_layer:
                            bucket = self._speed.setdefault(self._engine, [0.0, 0])
                            bucket[0] += dur
                            bucket[1] += max(1, rec["pages"])
                        if res.needs_review:
                            rec["status"] = "review"
                            rec["reviewNote"] = f"{len(res.review_items)} 处待核对"
                            rec["review_items"] = res.review_items
                        else:
                            rec["status"] = "done"
                    rec["docx"] = str(res.docx_path) if res.docx_path else None
                    rec["report"] = str(res.report_path) if res.report_path else None
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                for fid in ids:
                    rec = self._files.get(fid)
                    if rec and rec["status"] in _MID_STATUSES:
                        rec["status"] = "error"
                        rec["errNote"] = str(exc)
        finally:
            if server:
                server.stop()
            self._server = None
            self._running = False
            self._cancel = False

    def _per_page(self) -> float:
        """Measured seconds per page for the current engine, falling back to that
        engine's default. Local and cloud differ by an order of magnitude."""
        got = self._speed.get(self._engine)
        if got and got[1] > 0:
            return got[0] / got[1]
        return _DEFAULT_SPP.get(self._engine, 75.0)

    def _live_progress(self, rec: dict) -> int:
        """Time-based progress for the ocr stage: monotonic and capped at 81, so
        the real stages (parse 85 / render 90 / done 100) finish it off. An
        underestimate stalls at 81 rather than going backwards."""
        if rec["status"] != "ocr" or self._cur_started is None:
            return rec["progress"]
        if rec.get("_real_prog"):      # real page progress available; do not override
            return rec["progress"]
        import time as _t
        est = max(1, rec["pages"]) * self._per_page()
        frac = min((_t.monotonic() - self._cur_started) / est, 1.0)
        return max(rec["progress"], min(81, int(10 + 71 * frac)))

    def _eta(self) -> int | None:
        """Seconds remaining, from pages times measured seconds-per-page. Available
        during the first file and self-correcting as more finish."""
        import time as _t
        pp = self._per_page()
        waiting = sum(max(1, r["pages"]) for r in self._files.values()
                      if r["status"] in ("queued", "pending"))
        left = pp * waiting
        if self._cur_started is not None:          # remainder of the current file
            left += max(0.0, pp * self._cur_pages - (_t.monotonic() - self._cur_started))
        return int(left) if left > 1 else None

    def poll(self) -> dict:
        with self._lock:
            for r in self._files.values():
                if r["status"] == "ocr":
                    r["progress"] = self._live_progress(r)
            return {"files": [self.public(r) for r in self._files.values()],
                    "running": self._running, "stopping": self._cancel,
                    "eta": self._eta() if self._running else None}

    def reviews(self) -> list[dict]:
        out = []
        for rec in self._files.values():
            for it in rec.get("review_items", []):
                out.append({
                    "file": rec["name"], "page": it.page,
                    "loc": "位置 " + ", ".join(f"{v:.0f}" for v in it.bbox),
                    "kind": {"formula": "公式", "text": "文字", "image": "图片",
                             "table": "表格"}.get(it.kind, it.kind),
                    # Send recognized content verbatim for side-by-side review.
                    "latex": it.detail if it.kind in ("formula", "table") else "",
                    "hint": _REASON_HINT.get(it.reason, it.reason),
                    "crop": getattr(it, "crop", ""),
                })
        return out

    def file_path(self, fid: int, which: str) -> str | None:
        rec = self._files.get(int(fid))
        if not rec:
            return None
        if which == "output":
            return rec.get("output_dir") or self._last_output_dir or self._output_dir
        return rec.get(which)

    def output_dir(self) -> str:
        return self._last_output_dir or self._output_dir


# Model download state; only one download can run at a time.
_dl = {"running": False, "percent": 0, "error": "", "cancel": False}

mgr = ConvertManager()
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class AddReq(BaseModel):
    paths: list[str]


class FolderReq(BaseModel):
    path: str


class StartReq(BaseModel):
    ids: list[int]
    opts: dict = {}


class IdReq(BaseModel):
    id: int


class OutReq(BaseModel):
    path: str


class OpenReq(BaseModel):
    path: str


@app.get("/ping")
def ping():
    return {"ok": True}


@app.post("/add")
def add(req: AddReq):
    return {"files": [mgr.public(r) for p in req.paths if (r := mgr.add(p))]}


@app.post("/add_folder")
def add_folder(req: FolderReq):
    return {"files": mgr.add_folder(req.path)}


@app.post("/remove")
def remove(req: IdReq):
    mgr.remove(req.id)
    return {"ok": True}


@app.post("/clear")
def clear():
    return {"ok": mgr.clear()}


@app.post("/start")
def start(req: StartReq):
    """Verify the selected recognition path is usable before starting.

    Without this check, choosing local without the model would have MinerU
    silently download 2.2 GB mid-conversion, showing only a stalled progress bar.
    """
    from p2w import models

    cfg = settings.load()
    engine = settings.effective_engine(cfg)
    if engine == "cloud" and not cfg["api_token"]:
        return {"ok": False, "why": "云端识别要先在设置里填 API Key"}
    if engine == "local" and not models.ready():
        return {"ok": False, "why": "本地模型还没下载，请到设置里下载，或改用云端识别"}
    return {"ok": mgr.start(req.ids, req.opts)}


@app.post("/stop")
def stop():
    return {"ok": mgr.stop()}


@app.get("/poll")
def poll():
    return mgr.poll()


@app.get("/reviews")
def reviews():
    return {"items": mgr.reviews()}


@app.get("/output_dir")
def get_output_dir():
    return {"path": mgr.output_dir()}


@app.post("/output_dir")
def set_output_dir(req: OutReq):
    mgr._output_dir = req.path
    return {"path": mgr._output_dir}


@app.get("/file_path")
def file_path(id: int, which: str = "docx"):
    return {"path": mgr.file_path(id, which)}


@app.post("/open_path")
def open_path(req: OpenReq):
    p = Path(req.path)
    if not p.exists():
        return {"ok": False, "error": f"路径不存在: {req.path}"}
    try:
        subprocess.Popen(["open", str(p)])
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


class PasteReq(BaseModel):
    data: str
    ext: str = "png"


@app.post("/paste")
def paste(req: PasteReq):
    import base64, tempfile, time
    from p2w.pipeline import _unique_path
    try:
        raw = base64.b64decode(req.data)
    except Exception:
        return {"files": []}
    ext = (req.ext or "png").lower()
    if ext == "jpeg":
        ext = "jpg"
    d = Path(tempfile.gettempdir()) / "p2w_pastes"
    d.mkdir(parents=True, exist_ok=True)
    # Timestamped names, not uuids: the name propagates to the output document
    # and has to stay recognizable.
    path = _unique_path(d / f"截图 {time.strftime('%Y-%m-%d %H%M')}.{ext}")
    path.write_bytes(raw)
    rec = mgr.add(str(path))
    return {"files": [mgr.public(rec)] if rec else []}


class SettingsReq(BaseModel):
    engine: str | None = None
    api_token: str | None = None
    export: str | None = None


@app.get("/settings")
def get_settings():
    return settings.public()


@app.post("/settings")
def set_settings(req: SettingsReq):
    """Persist settings. Rejected mid-conversion: switching engines would split
    the batch between cloud and local."""
    if mgr._running:
        return {"ok": False, "why": "正在转换，先停下再改设置"}
    return {"ok": True,
            "settings": settings.public(settings.save(req.engine, req.api_token, req.export))}


@app.get("/model/status")
def model_status():
    """Local model availability and download progress; polled by the settings panel."""
    from p2w import models
    st = models.status()
    st["downloading"] = _dl["running"]
    st["error"] = _dl["error"]
    if _dl["running"] and _dl["percent"] > st["percent"]:
        st["percent"] = _dl["percent"]      # 下载线程报的更及时
    return st


@app.post("/model/download")
def model_download():
    """Start the model download; no-op when already running or complete."""
    from p2w import models

    if _dl["running"]:
        return {"ok": True, "already": True}
    if models.ready():
        return {"ok": True, "already": True}

    _dl.update(running=True, percent=0, error="", cancel=False)

    def work():
        try:
            models.download(on_progress=lambda p: _dl.__setitem__("percent", p),
                            should_cancel=lambda: _dl["cancel"])
        except Exception as exc:  # noqa: BLE001 - 失败原因要送到界面上
            _dl["error"] = str(exc)
        finally:
            _dl["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True}


@app.post("/model/cancel")
def model_cancel():
    _dl["cancel"] = True
    return {"ok": _dl["running"]}


@app.post("/settings/check")
def check_token(req: SettingsReq):
    """Validate the key with the cheapest possible call, rather than letting the
    user discover a typo when conversion fails."""
    token = (req.api_token or "").strip() or settings.load()["api_token"]
    if not token:
        return {"ok": False, "why": "还没填 API Key"}
    from p2w.config import ConvertOptions as _CO
    from p2w.mineru_cloud import verify_token
    ok, why = verify_token(_CO(api_token=token))
    return {"ok": ok, "why": why}


def _parent_alive(pid: int) -> bool:
    import os
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _watch_parent() -> None:
    """Exit when the launching shell (Tauri app) is gone.

    The shell is supposed to kill this server on quit, but its exit hook does
    not fire in the packaged build (verified on 0.1.1: Cmd+Q leaves this
    process behind, and macOS reports the app as "running in background").
    An orphan is reparented to PID 1, which cannot be faked, so poll the
    parent and unwind when it vanishes.
    """
    import os
    import time
    try:
        parent = int(os.environ.get("P2W_PARENT_PID") or 0)
    except ValueError:
        parent = 0
    parent = parent or os.getppid()
    if parent <= 1:
        return                      # started detached on purpose; don't watch
    while _parent_alive(parent) and os.getppid() != 1:
        time.sleep(2)
    mgr._cancel = True              # current file's engine subprocess gets killpg'd
    _dl["cancel"] = True
    try:
        if mgr._server:             # resident MinerU service holds the 1.2B model
            mgr._server.stop()
    except Exception:               # noqa: BLE001 - dying anyway
        pass
    for _ in range(40):             # give _run's cancel path up to ~8 s
        if not mgr._running:
            break
        time.sleep(0.2)
    os._exit(0)


def main():
    import uvicorn
    threading.Thread(target=_watch_parent, daemon=True).start()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8756
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
