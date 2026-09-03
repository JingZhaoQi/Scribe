"""Conversion pipeline: input -> recognition -> DocModel -> docx/markdown.

Three routes, chosen by textlayer.probe():
- text layer: digital PDFs without formulas, milliseconds per page
- hybrid: digital PDFs with formulas -- body from the text layer, formulas from
  the model
- full-page model: scans and everything else

Each file is isolated; one failure never affects the rest of the batch.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .config import ConvertOptions
from .mineru_backend import Cancelled
from . import hybrid, textlayer
from .normalize import check_readable, is_supported
from .render_docx import ReviewItem, render
from .review import write_report
from .winpath import exists as _exists, long_path, make_dirs


@dataclass
class ConversionResult:
    source: Path
    docx_path: Optional[Path] = None
    report_path: Optional[Path] = None
    review_items: list[ReviewItem] = field(default_factory=list)
    ok: bool = False
    error: str = ""
    cancelled: bool = False
    used_text_layer: bool = False   # took the text-layer fast path
    used_hybrid: bool = False       # took the hybrid path
    fallback_reason: str = ""       # why the fast path was rejected
    hybrid_error: str = ""          # why the hybrid path fell back

    @property
    def needs_review(self) -> bool:
        return bool(self.review_items)


def _unique_path(path: Path) -> Path:
    # winpath.exists, not Path.exists: a >260-character path answers False on
    # Windows whether or not the file is there, which would silently overwrite.
    if not _exists(path):
        return path
    for i in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not _exists(candidate):
            return candidate
    raise FileExistsError(f"too many duplicate outputs for {path.name}")


def convert_file(input_path: str | Path, output_dir: str | Path,
                 opts: ConvertOptions | None = None,
                 overwrite: bool = True,
                 should_cancel: Callable[[], bool] | None = None,
                 on_phase: Callable[[str], None] | None = None) -> ConversionResult:
    from .images import attach_formula_crops
    from .parse_mineru import parse_content_list

    def _phase(name: str) -> None:
        if on_phase:
            on_phase(name)

    opts = opts or ConvertOptions()
    input_path = Path(input_path)
    output_dir = make_dirs(output_dir)
    result = ConversionResult(source=input_path)

    _phase("check")
    bad = check_readable(input_path)
    if bad:  # reject broken files before the engine wastes a run on them
        result.error = bad
        return result

    try:
        ext = ".md" if opts.export_format == "md" else ".docx"
        out_docx = output_dir / (input_path.stem + ext)
        if not overwrite:
            out_docx = _unique_path(out_docx)
        with tempfile.TemporaryDirectory(prefix="p2w_") as work:
            skip = None if opts.fast_text_layer else "已关闭快速路径"
            if skip is None:
                skip = textlayer.probe(input_path)

            if skip is None:
                # Digital PDF: text and rules are already in the file.
                _phase("text")
                result.used_text_layer = True
                doc_model = textlayer.extract(input_path, Path(work) / "img")
            else:
                result.fallback_reason = skip
                doc_model = None
                if opts.fast_text_layer and skip.startswith(textlayer.MATH_REASON):
                    # Rejected only for formulas: body text still comes from
                    # the text layer, and the model only sees the formulas.
                    try:
                        doc_model, image_dir = hybrid.convert(
                            input_path, Path(work) / "hyb", opts, should_cancel, _phase)
                        result.used_hybrid = True
                    except Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001 - fall back to full page
                        result.hybrid_error = str(exc)

                if doc_model is None:
                    _phase("ocr")  # the expensive stage
                    content, image_dir = _recognize(input_path, Path(work), opts,
                                                    should_cancel, _phase)
                    _phase("parse")
                    doc_model = parse_content_list(content, image_dir,
                                                   source_file=str(input_path))
                attach_formula_crops(input_path, doc_model)  # crops for the review report
            _phase("render")
            if opts.export_format == "md":
                # Markdown keeps LaTeX verbatim, so no review report is produced.
                from .render_md import render_md
                render_md(doc_model, long_path(out_docx))
                review = []
            else:
                review = render(doc_model, long_path(out_docx),
                                flag_formulas=opts.review_all_formulas)

        result.docx_path = out_docx
        result.review_items = review
        if review:
            report = out_docx.with_name(out_docx.stem + ".复核报告.html")
            if not overwrite:
                report = _unique_path(report)
            write_report(review, long_path(report), source_file=str(input_path))
            result.report_path = report
        result.ok = True
    except Cancelled:
        result.cancelled = True   # user-initiated, not a failure
    except Exception as exc:  # noqa: BLE001 - per-file isolation
        result.error = str(exc)
        result.ok = False
        _write_error_detail(output_dir, input_path, exc)
    return result


def _page_count(path: Path) -> int:
    if path.suffix.lower() != ".pdf":
        return 1
    try:
        import pymupdf
        with pymupdf.open(str(path)) as d:
            return d.page_count
    except Exception:
        return 1


def _recognize(input_path: Path, work: Path, opts: ConvertOptions,
               should_cancel, phase) -> tuple[list, Path]:
    """Run the model; split pages across workers when it pays off."""
    from .mineru_backend import load_content_list, run_mineru
    from .parallel import ServicePool, plan_workers, run_parallel

    pages = _page_count(input_path)
    workers = plan_workers(pages, opts)
    # No splitting for cloud: the service parallelizes server-side.
    if workers > 1 and not opts.api_url and not opts.use_cloud:
        pool = ServicePool(opts, workers)
        urls = pool.start()
        if len(urls) > 1:
            try:
                # Parallel mode has real page progress, better than time estimates.
                return run_parallel(input_path, work / "par", opts, urls,
                                    should_cancel=should_cancel,
                                    on_page_done=lambda d, t: phase(f"ocr:{d}/{t}"))
            finally:
                pool.stop()
        pool.stop()   # only one worker came up: run single-threaded

    json_path, image_dir = run_mineru(input_path, work / "mineru", opts,
                                      should_cancel=should_cancel)
    return load_content_list(json_path), image_dir


def _write_error_detail(output_dir: Path, source: Path, exc: Exception) -> None:
    """Write the engine's raw error next to the output.

    The UI shows one line; packaged builds have no log file (backend stdout is
    inherited by Tauri and discarded), so the raw text has to land somewhere the
    user can find and send along. Pre-flight errors carry no detail and are skipped.
    """
    detail = getattr(exc, "detail", "")
    if not detail:
        return
    import time
    try:
        note = Path(long_path(output_dir / f"{source.stem}.错误详情.txt"))
        note.write_text(
            f"文件：{source}\n"
            f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"说明：{exc}\n"
            f"\n--- 识别引擎的原始输出（排查用）---\n{detail}\n",
            encoding="utf-8")
    except Exception:
        pass  # never let a logging failure mask the real error


def collect_inputs(paths: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out.extend(sorted(f for f in p.rglob("*") if f.is_file() and is_supported(f)))
        elif p.is_file() and is_supported(p):
            out.append(p)
    return out


def convert_batch(paths: list[str | Path], output_dir: str | Path,
                  opts: ConvertOptions | None = None,
                  on_progress: Callable[[int, int, ConversionResult], None] | None = None
                  ) -> list[ConversionResult]:
    """Convert a batch, sharing one resident service across files."""
    from .mineru_backend import MineruServer

    opts = opts or ConvertOptions()
    inputs = collect_inputs(paths)
    results: list[ConversionResult] = []

    server = MineruServer(opts) if len(inputs) > 1 and not opts.use_cloud else None
    if server:
        opts.api_url = server.start()  # None on failure: per-file loading
    try:
        for i, src in enumerate(inputs, 1):
            res = convert_file(src, output_dir, opts)
            results.append(res)
            if on_progress:
                on_progress(i, len(inputs), res)
    finally:
        if server:
            server.stop()
    return results
