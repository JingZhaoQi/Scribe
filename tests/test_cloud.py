"""Both recognition modes: cloud API routing and on-demand model download.

Offline only -- real API calls need a key and are verified through the Test
button in the UI. These tests cover what must not be uploaded or leaked.

Run: python3 tests/test_cloud.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from p2w import mineru_backend, mineru_cloud, models
from p2w.config import ConvertOptions
from p2w.mineru_backend import OCRBackendError
from p2w_gui import settings


def main() -> int:
    # ---- The presence of a key selects the route ----
    assert ConvertOptions().use_cloud is False
    assert ConvertOptions(api_token="k").use_cloud is True
    assert ConvertOptions(api_token="  ").use_cloud is True   # 空白也算填了，交给服务端判

    # ---- run_mineru must route by key: with one set, never touch the local engine ----
    called = {}
    real = mineru_cloud.run_cloud
    mineru_cloud.run_cloud = lambda *a, **k: called.setdefault("cloud", True) or ("j", "d")
    try:
        mineru_backend.run_mineru("x.pdf", "/tmp", ConvertOptions(api_token="k"))
        assert called.get("cloud"), "填了 Key 却没走云端"
    finally:
        mineru_cloud.run_cloud = real

    # ---- Automatic chunking: by page count, by size, and images error out ----
    with tempfile.TemporaryDirectory() as tmp:
        import pymupdf
        many = Path(tmp) / "many.pdf"
        d = pymupdf.open()
        for _ in range(5):
            d.new_page()
        d.save(str(many)); d.close()

        # 5 pages at 2 per chunk -> three chunks, inclusive page ranges
        orig_p = mineru_cloud._MAX_PAGES
        mineru_cloud._MAX_PAGES = 2
        try:
            ranges = mineru_cloud.plan_chunks(many)
            assert ranges == [(0, 1), (2, 3), (4, 4)], ranges
            chunks = mineru_cloud._split(many, ranges, Path(tmp) / "w")
            assert [start for _, start in chunks] == [0, 2, 4]
            with pymupdf.open(str(chunks[2][0])) as one:
                assert one.page_count == 1      # 尾段只有第 5 页
        finally:
            mineru_cloud._MAX_PAGES = orig_p

        # Within limits: no chunking
        assert mineru_cloud.plan_chunks(many) == []

        # Size-driven: page count fits but bytes do not
        orig_m = mineru_cloud._MAX_MB
        mineru_cloud._MAX_MB = many.stat().st_size / 1024 ** 2 / 2   # 限到一半大
        try:
            ranges = mineru_cloud.plan_chunks(many)
            assert len(ranges) >= 2, ranges
        finally:
            mineru_cloud._MAX_MB = orig_m

        # Images cannot be split, so oversized ones must raise
        img = Path(tmp) / "big.png"
        img.write_bytes(b"0" * 2048)
        orig_m = mineru_cloud._MAX_MB
        mineru_cloud._MAX_MB = 0.001
        try:
            _expect(lambda: mineru_cloud.plan_chunks(img), "超过云端上限")
        finally:
            mineru_cloud._MAX_MB = orig_m

    # ---- Reassembly: each chunk's page_idx must be offset to its real page ----
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        fake_lists = [
            [{"type": "text", "page_idx": 0, "text": "第一段"},
             {"type": "image", "page_idx": 1, "img_path": "images/a.jpg"}],
            [{"type": "text", "page_idx": 0, "text": "第二段"}],
        ]

        def fake_fetch(url, dest_dir):
            idx = int(url)
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "images").mkdir(exist_ok=True)
            (dest_dir / "images" / "a.jpg").write_bytes(b"jpg")
            (dest_dir / "content_list.json").write_text(
                __import__("json").dumps(fake_lists[idx]), encoding="utf-8")

        orig_fetch = mineru_cloud._fetch_zip
        mineru_cloud._fetch_zip = fake_fetch
        try:
            jp, img_dir = mineru_cloud._assemble(
                [(Path("x.part01.pdf"), 0), (Path("x.part02.pdf"), 200)], ["0", "1"], out)
            blocks = __import__("json").loads(jp.read_text(encoding="utf-8"))
            assert [b["page_idx"] for b in blocks] == [0, 1, 200], blocks
            # Images merged into one directory, references updated, file present
            pic = next(b for b in blocks if b["type"] == "image")
            assert pic["img_path"] == "images/c0_a.jpg", pic
            assert (img_dir / pic["img_path"]).exists()
        finally:
            mineru_cloud._fetch_zip = orig_fetch

    # ---- Cloud call without a key: a readable message, not a KeyError ----
    _expect(lambda: mineru_cloud.run_cloud("x.pdf", "/tmp", ConvertOptions()), "没有填 API Key")

    # ---- HTTP errors become sentences rather than raw status codes ----
    assert "无效" in mineru_cloud._explain_http(401, "")
    assert "额度" in mineru_cloud._explain_http(429, "")
    assert "服务端" in mineru_cloud._explain_http(503, "")

    # ---- A build without mineru must not claim a local engine ----
    import os
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "python" / "bin"
        fake.mkdir(parents=True)
        (fake / "python3.12").write_text("#!/bin/sh\n")
        site = Path(tmp) / "python" / "lib" / "python3.12" / "site-packages"
        site.mkdir(parents=True)
        os.environ["P2W_MINERU_PYTHON"] = str(fake / "python3.12")
        try:
            assert mineru_backend.mineru_cmd() is None, "云端版不该报告有本地引擎"
            (site / "mineru").mkdir()
            cmd = mineru_backend.mineru_cmd()
            assert cmd and cmd[1:] == ["-m", "mineru.cli.client"], cmd
        finally:
            os.environ.pop("P2W_MINERU_PYTHON", None)

    # ---- Key storage: readable back from disk, masked toward the frontend ----
    with tempfile.TemporaryDirectory() as tmp:
        settings._DIR = Path(tmp)
        settings._FILE = Path(tmp) / "settings.json"
        assert settings.load() == {"engine": "local", "api_token": "", "export": "docx"}

        cur = settings.save(engine="cloud", api_token="  sk-abcdefgh1234  ")
        assert cur == {"engine": "cloud", "api_token": "sk-abcdefgh1234", "export": "docx"}, cur
        assert settings.load()["api_token"] == "sk-abcdefgh1234"
        # NTFS has no POSIX mode bits, so chmod(0600) is a no-op there; the
        # file inherits the per-user ACL of %APPDATA% instead.
        if os.name != "nt":
            assert oct(settings._FILE.stat().st_mode)[-3:] == "600", "Key 文件权限该收到 0600"

        pub = settings.public()
        assert pub["hasToken"] is True and pub["engine"] == "cloud"
        assert "sk-abcdefgh1234" not in str(pub), f"掩码里漏了 Key 原文：{pub}"
        assert pub["tokenHint"] == "sk-a…1234", pub["tokenHint"]

        # A stored 'local' must report as cloud when no local engine exists.
        real = settings.local_available
        settings.local_available = lambda: False
        try:
            settings.save(engine="local")
            assert settings.effective_engine() == "cloud"
            assert settings.public()["engine"] == "cloud"
        finally:
            settings.local_available = real

        # Export format: round-trips, ignores junk values, defaults to docx
        assert settings.load()["export"] == "docx"
        settings.save(export="md")
        assert settings.load()["export"] == "md" and settings.public()["export"] == "md"
        settings.save(export="pdf")          # 不认识的值不写入
        assert settings.load()["export"] == "md"
        settings.save(export="docx")

        # Changing the engine must not clear the key
        settings.save(engine="local")
        assert settings.load()["api_token"] == "sk-abcdefgh1234"
        # Unknown engine values are ignored rather than corrupting the config
        settings.save(engine="乱写")
        assert settings.load()["engine"] == "local"

    # ---- Size accounting: symlinks must not be double-counted ----
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "hub"
        # Mirror the HuggingFace cache shape: real files in blobs, symlinks in snapshots
        real = root / "models--opendatalab--MinerU2.5-Pro-2605-1.2B"
        (real / "blobs").mkdir(parents=True)
        (real / "snapshots" / "abc").mkdir(parents=True)
        (real / "blobs" / "weight.bin").write_bytes(b"x" * 5000)
        (real / "snapshots" / "abc" / "weight.bin").symlink_to(real / "blobs" / "weight.bin")
        # The .locks directory shares the name and must not count
        (root / ".locks" / "models--opendatalab--MinerU2.5-Pro-2605-1.2B").mkdir(parents=True)
        (root / ".locks" / "models--opendatalab--MinerU2.5-Pro-2605-1.2B" / "a.lock").write_bytes(b"y" * 9999)

        orig_roots = models._CACHE_ROOTS
        models._CACHE_ROOTS = (str(root),)
        try:
            dirs = models.model_dirs()
            assert len(dirs) == 1, [str(d) for d in dirs]      # .locks 那个要被排除
            got = models.downloaded_bytes()
            assert got == 5000, f"符号链接被数了两遍：{got}"
            assert models.ready() is False                      # 5 KB 远不够，不能当就绪
            st = models.status()
            assert st["percent"] == 0 and st["ready"] is False, st
        finally:
            models._CACHE_ROOTS = orig_roots

    # ---- Source hint: an unreachable mirror should suggest the other one ----
    assert "huggingface" in models._explain("Connection refused", "modelscope")
    assert "modelscope" in models._explain("connection timed out", "huggingface")
    assert "2.2 GB" in models._explain("OSError: [Errno 28] No space left", "modelscope")

    print("OK  云端分流、预检、错误话术、Key 存取与掩码、模型体积统计")
    return 0


def _expect(fn, snippet: str) -> None:
    try:
        fn()
    except OCRBackendError as e:
        assert snippet in str(e), f"错误话术里没有「{snippet}」：{e}"
        return
    raise AssertionError(f"该抛 OCRBackendError（含「{snippet}」）却没抛")


if __name__ == "__main__":
    sys.exit(main())
