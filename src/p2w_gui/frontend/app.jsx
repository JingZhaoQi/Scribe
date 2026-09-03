// app.jsx - the entire UI.
//
// The shape follows the function: this is a converter, not a workbench. Drop
// files, wait, take the Word file away. One linear flow, no navigation.
//
// The window itself is transparent; the frosted material comes from macOS
// NSVisualEffectView (see main.rs), so nothing here paints an opaque backdrop.
(function () {
  const { useState, useEffect, useRef, useCallback } = React;
  const h = React.createElement;
  const { Gear, Folder, Reveal, Retry, Alert, Doc, DropArea, FileList, Settings, Sheet, makeT } = window;

  const API = "http://127.0.0.1:8756";
  const get = (p) => fetch(API + p).then((r) => r.json());
  const post = (p, b) =>
    fetch(API + p, { method: "POST", headers: { "Content-Type": "application/json" },
                     body: JSON.stringify(b || {}) }).then((r) => r.json());
  const TAURI = () => window.__TAURI__;
  const EXTS = ["pdf", "png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp"];

  async function openInSystem(path) {
    if (!path) throw new Error("没有可打开的路径");
    try {
      const t = TAURI();
      if (t && t.shell && t.shell.open) { await t.shell.open(path); return; }
    } catch (e) { /* Tauri 的 shell scope 可能拒绝，退回后端打开 */ }
    const r = await post("/open_path", { path });
    if (!r.ok) throw new Error(r.error || "打开失败");
  }

  const settled = (f) => f.status === "done" || f.status === "review" || f.status === "error";
  const busy = (f) => f.status === "ocr" || f.status === "queued"
                   || f.status === "parse" || f.status === "gen";
  const startable = (f) => f.status === "pending" || f.status === "error";

  function App() {
    const [gate, setGate] = useState(() => localStorage.getItem("pdfw_gate_done") !== "1");
    const [theme, setTheme] = useState(() => localStorage.getItem("pdfw_theme") || "system");
    const [autoOpen, setAutoOpen] = useState(() => localStorage.getItem("pdfw_auto_open") === "1");
    const [lang, setLang] = useState(() => localStorage.getItem("pdfw_lang") || "zh");
    // Memoize t: Row is memoized, and a fresh function identity each render
    // would re-render the whole list on every 500ms poll.
    const t = React.useMemo(() => makeT(lang), [lang]);
    const changeLang = (v) => { localStorage.setItem("pdfw_lang", v); setLang(v); };
    const [files, setFiles] = useState([]);
    const [running, setRunning] = useState(false);
    const [stopping, setStopping] = useState(false);
    const [showSettings, setShowSettings] = useState(false);
    const [toast, setToast] = useState(null); // { msg, kind: "info" | "err" }
    const [over, setOver] = useState(false);
    const [eta, setEta] = useState(null);
    // Engine and API key live in the backend; the frontend only sees a mask.
    const [cfg, setCfg] = useState({ engine: "local", hasToken: false, tokenHint: "" });
    const [keyState, setKeyState] = useState(null);   // { kind: "ok"|"err", text }
    const [model, setModel] = useState({ ready: true, downloading: false, percent: 0, error: "" });

    const say = useCallback((msg, kind) => {
      setToast({ msg, kind: kind || "info" });
      clearTimeout(window.__t);
      window.__t = setTimeout(() => setToast(null), kind === "err" ? 4500 : 2400);
    }, []);

    // ---------- Theme ----------
    const mql = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    const [sysDark, setSysDark] = useState(() => !!(mql && mql.matches));
    useEffect(() => {
      if (!mql) return;
      const fn = (e) => setSysDark(e.matches);
      mql.addEventListener("change", fn);
      return () => mql.removeEventListener("change", fn);
    }, []);
    const dark = theme === "system" ? sysDark : theme === "dark";
    // Sync the theme to the window: both the vibrancy material and the webview's
    // prefers-color-scheme follow NSWindow appearance.
    const applyAppearance = (v) => {
      try { const t = TAURI(); if (t && t.invoke) t.invoke("set_appearance", { theme: v }); }
      catch (e) { /* 非 Tauri 环境（测试/浏览器）没有 invoke，忽略 */ }
    };
    useEffect(() => { applyAppearance(theme); }, [theme]);
    const changeTheme = (v) => { localStorage.setItem("pdfw_theme", v); setTheme(v); };
    const changeAutoOpen = (v) => { localStorage.setItem("pdfw_auto_open", v ? "1" : "0"); setAutoOpen(v); };

    // ---------- Engine / API key ----------
    // Retry until the backend answers: Tauri spawns the Python backend at app
    // launch and it takes a moment to start listening. A one-shot fetch here
    // silently failed and left the UI showing the defaults (local engine, no
    // key) no matter what the user had saved.
    useEffect(() => {
      let stopped = false;
      (async () => {
        for (let i = 0; i < 60 && !stopped; i++) {
          try {
            const r = await get("/settings");
            if (r && r.engine) {
              if (!stopped) {
                setCfg(r);
                // The badge needs model readiness even before Settings opens.
                syncModel();
              }
              return;
            }
          } catch (e) { /* backend not up yet */ }
          await new Promise((res) => setTimeout(res, 1000));
        }
      })();
      return () => { stopped = true; };
    }, []);

    // Returns the fresh settings from the server, or null on failure, so
    // callers can act on server truth instead of stale component state.
    const pushCfg = async (body, okMsg) => {
      setKeyState(null);
      try {
        const r = await post("/settings", body);
        // Validate the shape: an older backend returns {detail:"Not Found"},
        // and storing that would blank the window on the next render.
        if (!r || r.ok === false || !r.settings || !r.settings.engine) {
          say((r && r.why) || t("设置没保存上（后端版本不符？）"), "err");
          return null;
        }
        setCfg(r.settings);
        if (okMsg) say(okMsg);
        return r.settings;
      } catch (e) { say(t("设置没保存上"), "err"); return null; }
    };
    // Switching happens inside Settings. Follow-up hints judge by the server
    // response, not component state -- right after launch the state may still
    // hold defaults while the server already has a saved key.
    const changeEngine = async (v) => {
      const fresh = await pushCfg(
        { engine: v }, v === "cloud" ? t("已切换到云端识别") : t("已切换到本机识别"));
      if (v === "cloud" && fresh && !fresh.hasToken) {
        say(t("云端识别要先填 API Key"), "err");
      } else if (v === "local" && fresh) {
        try {
          const m = await get("/model/status");
          if (m && m.ready === false) say(t("本机识别要先下载模型"), "err");
        } catch (e) { /* backend hiccup: conversion will surface it */ }
      }
    };

    // ---------- Local model download ----------
    // Poll only while Settings is open or a download runs: the status call
    // walks the cache directory and is not free.
    useEffect(() => {
      if (!showSettings && !model.downloading) return;
      const tick = () => get("/model/status")
        .then((m) => { if (m && typeof m.ready === "boolean") setModel(m); })
        .catch(() => {});
      tick();
      const iv = setInterval(tick, model.downloading ? 1000 : 4000);
      return () => clearInterval(iv);
    }, [showSettings, model.downloading]);

    // Refresh right after the request: the backend starts the thread before
    // responding, so the optimistic flag would otherwise flicker back.
    const syncModel = () => get("/model/status")
      .then((m) => { if (m && typeof m.ready === "boolean") setModel(m); })
      .catch(() => {});
    const downloadModel = async () => {
      setModel((m) => Object.assign({}, m, { downloading: true, error: "" }));
      try { await post("/model/download", {}); await syncModel(); }
      catch (e) { say(t("下载没能开始"), "err"); await syncModel(); }
    };
    const cancelModel = async () => {
      try { await post("/model/cancel", {}); } catch (e) { /* 已经停了就算了 */ }
      await syncModel();
    };
    const saveToken = (v) => pushCfg({ api_token: v }, t("API Key 已保存"));
    const checkToken = async () => {
      setKeyState({ kind: "info", text: t("正在测试…") });
      try {
        const r = await post("/settings/check", {});
        setKeyState(r.ok ? { kind: "ok", text: t("可以用") } : { kind: "err", text: r.why || t("不可用") });
      } catch (e) { setKeyState({ kind: "err", text: t("测试失败") }); }
    };

    // ---------- Backend polling ----------
    const autoOpenRef = useRef(autoOpen);
    useEffect(() => { autoOpenRef.current = autoOpen; }, [autoOpen]);
    useEffect(() => {
      if (!running) return;
      const iv = setInterval(async () => {
        let st;
        try { st = await get("/poll"); } catch (e) { return; }
        // Replace the object only when a field actually changed; Row is
        // memoized and skips re-render on identical references.
        setFiles((prev) => prev.map((f) => {
          const r = st.files.find((x) => x.id === f.id);
          if (!r) return f;
          for (const k in r) if (r[k] !== f[k]) return Object.assign({}, f, r);
          return f;
        }));
        setStopping(!!st.stopping);
        setEta(st.eta);
        if (!st.running) {
          setRunning(false); setStopping(false); setEta(null);
          if (autoOpenRef.current) openOut();
        }
      }, 500);
      return () => clearInterval(iv);
    }, [running]);

    // ---------- File intake ----------
    const merge = (picked) => {
      if (!picked || !picked.length) return;
      setFiles((prev) => {
        const have = new Set(prev.map((f) => f.id));
        return prev.concat(picked.filter((f) => !have.has(f.id)));
      });
    };
    // A drop or a pick that adds nothing must still say why -- silence reads
    // as a broken drop zone, and "already in the list" is the common case.
    const SKIP_TEXT = { duplicate: "已经在列表里了", unsupported: "格式不支持",
                        missing: "文件不存在", unknown: "没能添加" };
    const report = (res) => {
      merge(res.files);
      const skipped = res.skipped || [];
      if (res.files && res.files.length) return;
      if (!skipped.length) return;
      const why = skipped[0].why;
      const head = skipped.length > 1 ? `${skipped.length} 个文件` : skipped[0].name;
      say(`${head}：${t(SKIP_TEXT[why] || SKIP_TEXT.unknown)}`, "err");
    };

    const addFiles = async () => {
      try {
        const sel = await TAURI().dialog.open({ multiple: true, filters: [{ name: t("PDF 与图片"), extensions: EXTS }] });
        if (!sel) return;
        report(await post("/add", { paths: Array.isArray(sel) ? sel : [sel] }));
      } catch (e) { say(t("选择文件失败"), "err"); }
    };
    const addFolder = async () => {
      try {
        const sel = await TAURI().dialog.open({ directory: true });
        if (!sel) return;
        merge((await post("/add_folder", { path: sel })).files);
      } catch (e) { say(t("选择文件夹失败"), "err"); }
    };

    // Tauri intercepts HTML5 drop, so real paths come from its own event.
    useEffect(() => {
      // Not named `t`: that is the translator in this scope, and shadowing it
      // made the error branch call the Tauri namespace as a function.
      const tauri = TAURI();
      if (!tauri || !tauri.event) return;
      const uns = [];
      tauri.event.listen("tauri://file-drop", async (ev) => {
        setOver(false);
        const pl = ev.payload;
        const paths = Array.isArray(pl) ? pl : (pl && pl.paths) ? pl.paths : [];
        if (!paths.length) return;
        try { report(await post("/add", { paths })); } catch (e) { say(t("拖入失败"), "err"); }
      }).then((f) => uns.push(f));
      tauri.event.listen("tauri://file-drop-hover", () => setOver(true)).then((f) => uns.push(f));
      tauri.event.listen("tauri://file-drop-cancelled", () => setOver(false)).then((f) => uns.push(f));
      return () => uns.forEach((f) => f && f());
    }, []);

    // Paste screenshots
    useEffect(() => {
      const onPaste = async (e) => {
        const items = (e.clipboardData && e.clipboardData.items) || [];
        for (const it of items) {
          if (!it.type || it.type.indexOf("image/") !== 0) continue;
          const blob = it.getAsFile();
          if (!blob) continue;
          e.preventDefault();
          const b64 = await new Promise((res) => {
            const r = new FileReader();
            r.onload = () => res(String(r.result).split(",")[1]);
            r.readAsDataURL(blob);
          });
          try {
            merge((await post("/paste", { data: b64, ext: (it.type.split("/")[1] || "png") })).files);
            say(t("已粘贴截图"));
          } catch (_) { say(t("粘贴失败"), "err"); }
          break;
        }
      };
      document.addEventListener("paste", onPaste);
      return () => document.removeEventListener("paste", onPaste);
    }, []);

    // ---------- Actions ----------
    // start/retry share one core: optimistically mark queued, roll back
    // entirely if the backend refuses, or rows stall in "queued" forever.
    const launch = async (targets) => {
      if (!targets.length) return;
      const snapshot = files;
      const ids = new Set(targets.map((f) => f.id));
      setFiles((fs) => fs.map((f) => (ids.has(f.id) ? Object.assign({}, f, { status: "queued", progress: 5 }) : f)));
      try {
        const r = await post("/start", { ids: Array.from(ids), opts: { outDir: "same", dup: "rename" } });
        if (r && r.ok === false) {
          setFiles(snapshot);
          say(r.why || t("上一批还在转，请稍候"), "err");
          return;
        }
        setRunning(true);
      } catch (e) { setFiles(snapshot); say(t("启动失败"), "err"); }
    };
    const start = () => launch(files.filter(startable));
    const retryOne = (f) => launch([f]);
    const retryFailed = () => launch(files.filter((f) => f.status === "error"));

    const stop = async () => {
      setStopping(true);
      try { await post("/stop"); } catch (e) { say(t("停止失败"), "err"); setStopping(false); }
    };
    const removeOne = async (id) => {
      setFiles((fs) => fs.filter((f) => f.id !== id));
      try { await post("/remove", { id }); } catch (e) { say(t("移除失败"), "err"); }
    };
    const clearAll = async () => {
      setFiles([]);
      try { await post("/clear"); } catch (e) { say(t("清空失败"), "err"); }
    };
    const openOut = async () => {
      try { await openInSystem((await get("/output_dir")).path); }
      catch (e) { say(e.message || "打开失败", "err"); }
    };
    const openFile = async (f, which) => {
      try { await openInSystem((await get("/file_path?id=" + f.id + "&which=" + which)).path); }
      catch (e) { say(e.message || "打开失败", "err"); }
    };

    // ---------- Keyboard ----------
    const has = files.length > 0;
    const allDone = has && files.every(settled);
    useEffect(() => {
      const onKey = (e) => {
        if (e.key === "Escape" && showSettings) { setShowSettings(false); return; }
        if (e.key !== "Enter" || showSettings || running || !has || allDone) return;
        const ae = document.activeElement;
        if (ae && ae !== document.body && /^(BUTTON|A|INPUT|SELECT|TEXTAREA)$/.test(ae.tagName)) return;
        e.preventDefault();
        start();
      };
      document.addEventListener("keydown", onKey);
      return () => document.removeEventListener("keydown", onKey);
    });

    // ---------- Derived state ----------
    const nOk = files.filter((f) => f.status === "done").length;
    const nWarn = files.filter((f) => f.status === "review").length;
    const nErr = files.filter((f) => f.status === "error").length;
    const cur = files.find(busy);
    const doneCount = files.filter(settled).length;
    // Batch progress = finished files plus the current file's backend progress.
    const overall = has
      ? Math.min(99, Math.round(((doneCount + (cur ? (cur.progress || 0) / 100 : 0)) * 100) / files.length))
      : 0;
    const multi = files.length > 1;
    const nToStart = files.filter(startable).length;
    const fmtEta = (sec) => {
      if (sec == null || sec < 0) return null;
      if (sec < 60) return t("约还需 {n} 秒").replace("{n}", Math.max(1, Math.round(sec / 10) * 10));
      const m = Math.round(sec / 60);
      return m < 60 ? t("约还需 {n} 分钟").replace("{n}", m)
                    : t("约还需 {h} 小时 {m} 分").replace("{h}", Math.floor(m / 60)).replace("{m}", m % 60);
    };
    const PHASE_LABEL = { queued: "排队中", ocr: "识别文字与公式", parse: "解析版面", gen: "生成 Word" };  // passed through t() at render time

    if (gate) {
      return h("div", { className: "app-root" + (dark ? " theme-dark" : ""), "data-animate": true },
        h("div", { className: "titlebar", "data-tauri-drag-region": true }),
        h("div", { className: "body" },
          h(Sheet, { t, onPick: async (engine) => {
            localStorage.setItem("pdfw_gate_done", "1");
            setGate(false);
            await pushCfg({ engine });
            setShowSettings(true);   // put the download button / key field in reach
          } })));
    }

    return h("div", { className: "app-root" + (dark ? " theme-dark" : ""), "data-animate": true },

      // Title bar: brand plus gear; the whole strip drags the window.
      h("div", { className: "titlebar", "data-tauri-drag-region": true },
        h("div", { className: "brand" },
          h("div", { className: "brand-icon" }, h(Doc, { width: 18, height: 18 })),
          h("div", { className: "brand-text" },
            h("span", { className: "title-name" }, "抄录 · Scribe"),
            h("span", { className: "title-tag" }, t("把 PDF 变成可编辑的 Word")))),
        running && h("span", { className: "title-sub" },
          stopping ? t("正在停止…") : t("第 {a} / {b}").replace("{a}", Math.min(doneCount + 1, files.length)).replace("{b}", files.length)),
        h("span", { className: "title-spacer" }),
        has && !running && h("button", { className: "link", title: t("移除全部文件"), onClick: clearAll }, t("清空列表")),
        h("button", { className: "icon-btn", title: t("设置"), onClick: () => setShowSettings(true) }, h(Gear))),

      // Mode indicator only -- switching lives in Settings. It stays visible
      // because whether files get uploaded is a privacy matter; clicking it
      // opens Settings where the actual switch is.
      h("div", { className: "engine-bar" },
        (() => {
          // Lit only when the active mode can actually convert: cloud needs a
          // saved key, local needs the downloaded model.
          const ready = cfg.engine === "cloud" ? cfg.hasToken : model.ready !== false;
          return h("button", {
            className: "engine-badge " + (cfg.engine === "cloud" ? "cloud" : "local")
              + (ready ? "" : " off"),
            title: ready ? t("识别方式在设置中切换")
              : (cfg.engine === "cloud" ? t("云端识别要先填 API Key") : t("本机识别要先下载模型")),
            onClick: () => setShowSettings(true),
          },
            h("span", { className: "engine-dot" }),
            cfg.engine === "cloud" ? t("云端识别") : t("本机识别"));
        })()),

      // Body: drop zone when empty, file list otherwise.
      h("div", { className: "body" },
        has
          ? h(FileList, {
              files, running, t, onRemove: removeOne, onRetry: retryOne,
              onOpen: (f) => openFile(f, "docx"),
              onReveal: (f) => openFile(f, "output"),
              onReport: (f) => openFile(f, "report"),
            })
          : h(DropArea, { over, setOver, onAdd: addFiles, onAddFolder: addFolder, t }),

        // Action bar: exactly one primary action at any time.
        has && h("div", { className: "actionbar" },
          allDone
            ? h(React.Fragment, null,
                h("div", { className: "summary" },
                  h("b", { className: "n-ok" }, nOk), t("完成"),
                  nWarn > 0 && h("b", { className: "n-warn" }, nWarn),
                  nWarn > 0 && t("待核对"),
                  nErr > 0 && h("b", { className: "n-err" }, nErr),
                  nErr > 0 && t("失败")),
                h("span", { className: "spacer" }),
                nErr > 0 && h("button", { className: "btn btn-quiet btn-sm", onClick: retryFailed },
                  h(Retry), t("重试失败")),
                nWarn > 0 && h("button", { className: "btn btn-quiet btn-sm", onClick: () => {
                  const f = files.find((x) => x.status === "review");
                  if (f) openFile(f, "report");
                } }, h(Reveal), t("查看复核报告")),
                h("button", { className: "btn btn-quiet btn-sm", onClick: clearAll }, t("再转一批")),
                h("button", { className: "btn btn-main btn-fit", onClick: openOut },
                  h(Folder), t("打开输出文件夹")))
            : running
            ? h(React.Fragment, null,
                h("div", { className: "run-box" },
                  h("div", { className: "run-top" },
                    h("span", { className: "row-name run-name" },
                      stopping ? t("正在停止…") : (cur ? cur.name : t("准备中…"))),
                    !stopping && h("span", { className: "pct" }, overall + "%")),
                  h("div", { className: "track" },
                    stopping
                      ? h("div", { className: "bar indet" })
                      : h("div", { className: "bar", style: { transform: "scaleX(" + overall / 100 + ")" } })),
                  h("div", { className: "row-sub run-sub" },
                    stopping ? t("正在掐断识别进程") :
                    [(multi ? t("{n} 份已完成").replace("{n}", doneCount + " / " + files.length) : null),
                     cur && PHASE_LABEL[cur.status] ? t(PHASE_LABEL[cur.status]) + t("中…") : null,
                     fmtEta(eta)].filter(Boolean).join(" · "))),
                h("button", { className: "btn btn-danger", onClick: stop, disabled: stopping },
                  stopping ? t("停止中") : t("停止")))
            : h(React.Fragment, null,
                h("span", { className: "row-sub idle-sub" },
                  t("{n} 页待转换").replace("{n}", files.reduce((n, f) => n + (f.pages || 1), 0)),
                  nErr > 0 ? t("（含 {n} 个待重试）").replace("{n}", nErr) : ""),
                h("span", { className: "spacer" }),
                h("button", { className: "btn btn-main btn-fit", onClick: start },
                  t("转换 {n} 个文件").replace("{n}", nToStart) + (lang === "en" ? t("个文件") : ""))))),

      showSettings && h(Settings, {
        theme, onTheme: changeTheme,
        autoOpen, onAutoOpen: changeAutoOpen,
        engine: cfg.engine, tokenHint: cfg.tokenHint, keyState,
        exportFmt: cfg.export || "docx",
        onExport: (v) => pushCfg({ export: v }, v === "md" ? t("之后导出 Markdown") : t("之后导出 Word")),
        localAvailable: cfg.localAvailable,
        model, onModelDownload: downloadModel, onModelCancel: cancelModel,
        onEngine: changeEngine, onToken: saveToken, onCheck: checkToken,
        t, lang, onLang: changeLang,
        onClose: () => setShowSettings(false),
      }),

      toast && h("div", { className: "toast fade" + (toast.kind === "err" ? " err" : "") },
        toast.kind === "err" && h(Alert), toast.msg)
    );
  }

  // Never let a render failure blank the window: a white screen tells the user
  // nothing and offers no way out.
  class Guard extends React.Component {
    constructor(props) { super(props); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    render() {
      if (!this.state.err) return this.props.children;
      return h("div", { className: "crash" },
        h("b", null, "界面出错了"),
        h("div", { className: "crash-msg" }, String((this.state.err && this.state.err.message) || this.state.err)),
        h("button", { className: "btn btn-main", onClick: () => location.reload() }, "重新加载"));
    }
  }

  ReactDOM.createRoot(document.getElementById("root"))
    .render(React.createElement(Guard, null, React.createElement(App)));
})();
