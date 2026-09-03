"""LaTeX -> Word OMML (Office Math Markup Language).

Strategy: invoke pandoc per formula, parse the produced docx's document.xml,
and extract the <m:oMath>/<m:oMathPara> element so it can be appended directly
into a python-docx paragraph. Results are cached so a repeated formula on the
same exam only forks pandoc once. A failed conversion never aborts the document:
the caller falls back to highlighted raw LaTeX text.
"""

from __future__ import annotations

import functools
import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from lxml import etree

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_OMATH = f"{{{M_NS}}}oMath"
_OMATHPARA = f"{{{M_NS}}}oMathPara"
_W_P = f"{{{W_NS}}}p"


class FormulaConversionError(RuntimeError):
    """Raised when pandoc cannot turn a LaTeX string into OMML."""


@functools.lru_cache(maxsize=1)
def _pandoc() -> str:
    """Locate pandoc: env var > bundled copy > PATH.

    Distributed machines rarely have pandoc installed, so packaging ships the
    official binary under Resources/payload/.
    """
    env = os.environ.get("P2W_PANDOC")
    if env and Path(env).exists():
        return env
    # Sources live at <payload>/src/p2w/omml.py; pandoc sits at <payload>/pandoc
    # (pandoc.exe on Windows -- without the suffix nothing matches and every
    # formula silently degrades to highlighted text).
    payload = Path(__file__).resolve().parents[2]
    for name in ("pandoc", "pandoc.exe"):
        bundled = payload / name
        if bundled.exists():
            return str(bundled)
    return shutil.which("pandoc") or "pandoc"


@functools.lru_cache(maxsize=4096)
def _convert(latex: str, block: bool) -> bytes:
    """Run pandoc on a single formula, return the serialized OMML element."""
    md = f"$$\n{latex}\n$$" if block else f"${latex}$"
    try:
        proc = subprocess.run(
            [_pandoc(), "-f", "markdown", "-t", "docx", "-o", "-"],
            input=md.encode("utf-8"),
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise FormulaConversionError(str(exc)) from exc

    with zipfile.ZipFile(io.BytesIO(proc.stdout)) as zf:
        document = zf.read("word/document.xml")
    root = etree.fromstring(document)

    tag = _OMATHPARA if block else _OMATH
    node = root.find(f".//{tag}")
    if node is None:
        # block formulas are wrapped in oMathPara; inline ones are bare oMath
        node = root.find(f".//{_OMATH}")
    if node is None:
        raise FormulaConversionError(f"no OMML produced for: {latex!r}")
    return etree.tostring(node)


def latex_to_omml(latex: str, block: bool = False):
    """Return a fresh lxml element ready to append into a paragraph's <w:p>.

    Raises FormulaConversionError on failure so the renderer can degrade
    gracefully to highlighted raw text.
    """
    serialized = _convert(latex.strip(), block)
    return etree.fromstring(serialized)


_BATCH_MARK = re.compile(r"P2WBATCHMARK(\d+)")


def batch_latex_to_omml(items: list[tuple[str, bool]]) -> list:
    """Convert many formulas with ONE pandoc run instead of one fork per formula.

    items: [(latex, is_block), ...]. Returns a list aligned with the input: a
    fresh lxml element per slot (same shape latex_to_omml would return), or
    None where that formula produced no OMML — the caller falls back to
    latex_to_omml for those. If the batch pandoc call itself fails, every slot
    is None and the caller degrades to per-formula conversion.

    Alignment uses marker paragraphs: a "P2WBATCHMARK<i>" line precedes each
    formula, so results can be mapped back even when pandoc merges or splits
    paragraphs.
    """
    if not items:
        return []
    parts = []
    for i, (latex, block) in enumerate(items):
        parts.append(f"P2WBATCHMARK{i}")
        parts.append("")
        parts.append(f"$$\n{latex.strip()}\n$$" if block else f"${latex.strip()}$")
        parts.append("")
    md = "\n".join(parts)
    try:
        proc = subprocess.run(
            [_pandoc(), "-f", "markdown", "-t", "docx", "-o", "-"],
            input=md.encode("utf-8"),
            capture_output=True,
            check=True,
        )
        with zipfile.ZipFile(io.BytesIO(proc.stdout)) as zf:
            document = zf.read("word/document.xml")
        root = etree.fromstring(document)
    except (subprocess.CalledProcessError, FileNotFoundError,
            zipfile.BadZipFile, KeyError, etree.XMLSyntaxError):
        return [None] * len(items)

    results: list = [None] * len(items)
    slot = -1
    for p in root.iter(_W_P):
        m = _BATCH_MARK.fullmatch("".join(p.itertext()).strip())
        if m:
            slot = int(m.group(1))
            continue
        if slot < 0 or results[slot] is not None:
            continue
        block = items[slot][1]
        node = p.find(f".//{_OMATHPARA if block else _OMATH}")
        if node is None:  # Unexpected shape: accept whichever math element exists.
            node = p.find(f".//{_OMATH if block else _OMATHPARA}")
        if node is not None:
            results[slot] = node
    return results
