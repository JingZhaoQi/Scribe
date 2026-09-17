"""Progress and ETA estimation (pure unit tests, no service, no recognition).

The engine reports no page-level progress, so the ocr stage is derived from
elapsed over expected time. These tests pin the contract: dynamic, monotonic,
capped at 81 so the real stages finish it off.

Run: python3 tests/test_progress.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from p2w_gui.server import _DEFAULT_SPP, ConvertManager

PASS, FAIL = [], []
def ck(name, cond):
    (PASS if cond else FAIL).append(name)
    print("✅" if cond else "❌", name)


def mgr_with_file(pages=4, status="ocr", progress=10):
    m = ConvertManager()
    rec = {
        "id": 1, "name": "x.pdf", "type": "pdf", "pages": pages,
        "size": "1 MB", "path": "/x.pdf",
        "status": status, "progress": progress,
        "reviewNote": None, "errNote": None,
        "review_items": [], "docx": None, "report": None, "output_dir": None,
    }
    m._files[1] = rec
    return m, rec


# --- _per_page: engine default until measured, then measured; local and cloud separate ---
m = ConvertManager()
ck("无实测→本机默认秒/页", m._per_page() == _DEFAULT_SPP["local"])
m._speed["local"] = [300.0, 5]
ck("有实测→实测秒/页", m._per_page() == 60.0)
m._engine = "cloud"
ck("切云端→用云端默认，不沾本机的实测", m._per_page() == _DEFAULT_SPP["cloud"])
m._speed["cloud"] = [20.0, 4]
ck("云端也按自己的实测修正", m._per_page() == 5.0)
ck("云端默认比本机快一个数量级", _DEFAULT_SPP["cloud"] * 10 <= _DEFAULT_SPP["local"])
m._engine = "local"

# --- _live_progress climbs with elapsed time ---
m, rec = mgr_with_file(pages=4)          # est = 4 × 75 = 300s
m._cur_started = time.monotonic() - 150  # 已过一半
p = m._live_progress(rec)
ck("耗时一半→进度约半程(45~46)", 45 <= p <= 46)

m._cur_started = time.monotonic() - 100000  # 远超估计
ck("超时也不爆→封顶 81", m._live_progress(rec) == 81)

# --- Monotonic: a corrected estimate never moves progress backwards ---
m, rec = mgr_with_file(pages=4, progress=70)
m._cur_started = time.monotonic()        # 刚开始，按算是 10
ck("单调：不往后退", m._live_progress(rec) == 70)

# --- Non-ocr stage or no current file: returned unchanged ---
m, rec = mgr_with_file(status="parse", progress=85)
m._cur_started = time.monotonic() - 10
ck("parse 阶段不动态推", m._live_progress(rec) == 85)
m, rec = mgr_with_file()
ck("无当前文件→原样", m._live_progress(rec) == 10)

# --- poll persists the computed progress onto the record ---
m, rec = mgr_with_file(pages=4)
m._running = True
m._cur_started = time.monotonic() - 150
out = m.poll()
f = [x for x in out["files"] if x["id"] == 1][0]
ck("poll 返回动态进度", 45 <= f["progress"] <= 46)
ck("poll 顺手持久化（下次不会退）", rec["progress"] == f["progress"])

# --- ETA is available during the first file and self-corrects ---
m, rec = mgr_with_file(pages=4)
m._running = True
m._cur_started = time.monotonic()
m._cur_pages = 4
eta = m._eta()
ck("首份也有 ETA（约 4×75=300s）", eta is not None and 280 <= eta <= 300)
m._speed["local"] = [600.0, 10]          # 实测 60s/页
eta2 = m._eta()
ck("ETA 随实测修正（约 4×60=240s）", eta2 is not None and 220 <= eta2 <= 240)

# --- Learning happens in _run; this pins the accumulator semantics ---
m = ConvertManager()
ck("累加器初始为空", m._speed == {} and m._engine == "local")

# --- _parent_alive: orphan watchdog probe (dead parent -> backend exits) ---
import os
from p2w_gui.server import _parent_alive
ck("看门狗：当前进程判活", _parent_alive(os.getpid()))
ck("看门狗：不存在的 pid 判死", not _parent_alive(1 << 30))

print(f"\n=== 进度推算: {len(PASS)} 通过, {len(FAIL)} 失败 ===")
sys.exit(1 if FAIL else 0)
