// parts.jsx - UI pieces: icons, drop zone, file list, settings, first-run sheet.
//
// Icons are hand-drawn: the whole UI needs only a handful of shapes, and drawing
// them keeps stroke width and style consistent (1.7px, round caps and joins).
(function () {
  const h = React.createElement;

  // ---------------- UI language ----------------
  // The Chinese source string is the key: a missing English entry falls back to
  // it, so the UI never shows a blank or a raw key. Backend-generated content
  // (error text, review counts) is not translated yet.
  const EN = {
    "抄录": "Scribe",
    "把 PDF 变成可编辑的 Word": "Turn PDFs into editable Word",
    "把 PDF 拖进来": "Drop PDFs here",
    "松手即添加": "Release to add",
    "论文、扫描件、截图都行。公式转成 Word 原生公式，打开就能改。":
      "Papers, scans, screenshots — formulas become native Word equations you can edit.",
    "选择文件": "Choose Files",
    "选择文件夹": "Choose Folder",
    "粘贴截图": "paste screenshot",
    "支持 PDF / PNG / JPG / TIFF": "PDF / PNG / JPG / TIFF",
    "排队中": "Queued",
    "正在识别文字与公式…": "Recognizing text & formulas…",
    "正在解析版面…": "Parsing layout…",
    "正在生成 Word…": "Generating Word…",
    "转换失败": "Conversion failed",
    "{size} · {pages} 页": "{size} · {pages} pages",
    "重新转换这个文件": "Convert this file again",
    "重试": "Retry",
    "移除": "Remove",
    "对照原件核对识别出的公式": "Check recognized formulas against the original",
    "复核": "Review",
    "打开 Word": "Open Word",
    "打开 Markdown": "Open Markdown",
    "在访达中显示": "Show in Finder",
    "设置": "Settings",
    "关闭 (Esc)": "Close (Esc)",
    "识别方式": "Recognition",
    "这个版本没有内置本地模型，只能用云端识别": "This build has no local model — cloud only",
    "文件会上传到 mineru.net 识别": "Files are uploaded to mineru.net",
    "模型在本机运行，文件不上传": "Runs on-device; files never leave this Mac",
    "本机识别": "Local",
    "识别方式在设置中切换": "Switch recognition mode in Settings",
    "云端识别": "Cloud",
    "这个版本未包含本地模型": "This build has no local model",
    "识别模型": "Model",
    "已就绪，可以离线使用": "Ready — works offline",
    "正在下载… ": "Downloading… ",
    "还没下载，约 2.2 GB": "Not downloaded yet (~2.2 GB)",
    "下载模型": "Download Model",
    "取消下载": "Cancel Download",
    "API Key": "API Key",
    "已保存": "Saved",
    "还没填，转换会失败": "Not set — conversion will fail",
    "粘贴 mineru.net 的 API Key": "Paste your mineru.net API key",
    "保存": "Save",
    "测试": "Test",
    "去 mineru.net 申请 →": "Get a key at mineru.net →",
    "官方额度每天 ": "Official quota: ",
    "1000 页": "1,000 pages/day",
    "，用完当天要排队或直接失败；": " — beyond that, jobs queue or fail; ",
    "超过 200 页的文件会自动分段上传，不用自己切。量大的时候改用本机识别，没有额度限制。":
      "files over 200 pages are split and uploaded automatically. For heavy use, switch to local — no quota.",
    "Key 的有效期为 ": "Keys expire after ",
    "90 天": "90 days",
    "，到期不支持续期，需去官网重新创建并在这里换新。":
      " and cannot be renewed — create a new one on the site and paste it here.",
    "导出格式": "Export Format",
    "Markdown 文件，公式保留 LaTeX 原文": "Markdown file; formulas stay as LaTeX",
    "Word 文档，公式为可编辑的原生公式": "Word document with editable native equations",
    "外观": "Appearance",
    "跟随系统": "System",
    "浅色": "Light",
    "深色": "Dark",
    "界面语言": "Language",
    "转换完打开文件夹": "Open folder when done",
    "整批转完自动弹出结果目录": "Reveal the results folder after each batch",
    "云端识别会把文件上传到 mineru.net。涉密或未发表的稿子请切回本机识别。":
      "Cloud mode uploads your files to mineru.net. Switch to local for confidential or unpublished work. ",
    "文件只在这台电脑上处理，不上传。": "Files are processed on this Mac only — nothing is uploaded. ",
    "识别准确率取决于扫描清晰度——": "Accuracy depends on scan quality — ",
    "转换完的 Word 旁边会附一份复核报告，列出无法自动确认的内容，请对照原件过一遍。":
      "each conversion ships with a review report listing anything that could not be verified automatically.",
    "先挑一种识别方式": "Choose how to recognize",
    "随时可以在设置里更换。": "You can change this anytime in Settings.",
    "下载 2.2 GB 的模型，之后文件不出这台电脑，没有额度限制。适合涉密或大批量。":
      "Download a 2.2 GB model; files never leave this Mac and there is no quota. Best for confidential or bulk work.",
    "填一个 mineru.net 的 API Key，不用下模型、不占算力。文件会上传，每天 1000 页额度。":
      "Paste a mineru.net API key — no model download, no local compute. Files are uploaded; 1,000 pages/day quota.",
    "转换完的 Word 旁会附一份复核报告，列出无法自动确认的内容——请对照原件过一遍再用。":
      "Each conversion ships with a review report listing anything that could not be verified automatically.",
    "清空列表": "Clear List",
    "移除全部文件": "Remove all files",
    "正在停止…": "Stopping…",
    "第 {a} / {b}": "{a} of {b}",
    "完成": "done",
    "待核对": "to review",
    "失败": "failed",
    "重试失败": "Retry Failed",
    "查看复核报告": "Review Report",
    "再转一批": "Convert More",
    "打开输出文件夹": "Open Output Folder",
    "准备中…": "Preparing…",
    "正在掐断识别进程": "Killing the recognition process",
    "识别文字与公式": "Recognizing text & formulas",
    "解析版面": "Parsing layout",
    "生成 Word": "Generating output",
    "中…": "…",
    "{n} 份已完成": "{n} done",
    "停止中": "Stopping",
    "停止": "Stop",
    "{n} 页待转换": "{n} pages to convert",
    "（含 {n} 个待重试）": " (incl. {n} to retry)",
    "转换 {n} 个文件": "Convert {n} " ,
    "个文件": "file(s)",
    "界面出错了": "Something went wrong",
    "重新加载": "Reload",
    "约还需 {n} 秒": "about {n}s left",
    "约还需 {n} 分钟": "about {n} min left",
    "约还需 {h} 小时 {m} 分": "about {h}h {m}m left",
    "已切换到云端识别": "Switched to cloud recognition",
    "已切换到本机识别": "Switched to local recognition",
    "云端识别要先填 API Key": "Cloud mode needs an API key first",
    "本机识别要先下载模型": "Local mode needs the model downloaded first",
    "设置没保存上（后端版本不符？）": "Settings not saved (backend mismatch?)",
    "设置没保存上": "Settings not saved",
    "API Key 已保存": "API key saved",
    "正在测试…": "Testing…",
    "可以用": "Works",
    "不可用": "Not working",
    "测试失败": "Test failed",
    "下载没能开始": "Download failed to start",
    "之后导出 Markdown": "Will export Markdown from now on",
    "之后导出 Word": "Will export Word from now on",
    "选择文件失败": "Couldn't pick files",
    "已经在列表里了": "already in the list",
    "格式不支持": "unsupported format",
    "文件不存在": "file not found",
    "没能添加": "couldn't be added",
    "选择文件夹失败": "Couldn't pick a folder",
    "拖入失败": "Drop failed",
    "已粘贴截图": "Screenshot pasted",
    "粘贴失败": "Paste failed",
    "上一批还在转，请稍候": "Previous batch is still running",
    "启动失败": "Failed to start",
    "停止失败": "Failed to stop",
    "移除失败": "Failed to remove",
    "清空失败": "Failed to clear",
    "打开失败": "Failed to open",
    "没有可打开的路径": "Nothing to open",
    "PDF 与图片": "PDF & images",
  };
  function makeT(lang) {
    if (lang !== "en") return (s) => s;
    return (s) => (Object.prototype.hasOwnProperty.call(EN, s) ? EN[s] : s);
  }

  const svg = (d, extra) => (props) =>
    h("svg", Object.assign({
      width: 16, height: 16, viewBox: "0 0 24 24", fill: "none",
      stroke: "currentColor", strokeWidth: 1.7,
      strokeLinecap: "round", strokeLinejoin: "round",
    }, extra, props), d.map((p, i) => h("path", { key: i, d: p })));

  const Gear = svg([
    "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z",
    "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6h.09A1.65 1.65 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09A1.65 1.65 0 0 0 15 4.6a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9v.09A1.65 1.65 0 0 0 20.91 10H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z",
  ]);
  const Folder = svg(["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"]);
  const Reveal = svg(["M14 3h7v7", "M21 3l-9 9", "M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"]);
  const X = svg(["M18 6 6 18", "M6 6l12 12"], { width: 14, height: 14 });
  const Check = svg(["M9 11l3 3L22 4", "M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"]);
  const Retry = svg(["M3 12a9 9 0 1 0 2.6-6.3", "M3 4v5h5"]);
  const Alert = svg(["M12 9v4", "M12 17h.01", "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"]);
  const Doc = svg([
    "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z",
    "M14 2v6h6", "M9 13h6", "M9 17h4",
  ], { width: 30, height: 30 });

  // ================= Drop zone (empty state) =================
  // Blank space is not clickable: only the tray glyph and the two buttons open
  // a dialog. Drag-and-drop still covers the whole area.
  function DropArea({ over, setOver, onAdd, onAddFolder, t }) {
    t = t || ((x) => x);
    return h("div", {
      className: "drop" + (over ? " over" : ""),
      onDragOver: (e) => { e.preventDefault(); setOver(true); },
      onDragLeave: (e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOver(false); },
      onDrop: (e) => { e.preventDefault(); setOver(false); },
    },
      h("div", {
        className: "drop-glyph rise", role: "button", tabIndex: 0, title: t("选择文件"),
        onClick: onAdd,
        onKeyDown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onAdd(); } },
      },
        h("div", { className: "tray" })),
      h("div", { className: "drop-title rise" }, over ? t("松手即添加") : t("把 PDF 拖进来")),
      h("div", { className: "drop-hint rise" },
        t("论文、扫描件、截图都行。公式转成 Word 原生公式，打开就能改。")),
      h("div", { className: "drop-actions rise" },
        h("button", { className: "btn btn-main", onClick: (e) => { e.stopPropagation(); onAdd(); } }, t("选择文件")),
        h("button", { className: "btn btn-quiet", onClick: (e) => { e.stopPropagation(); onAddFolder(); } },
          h(Folder), t("选择文件夹"))),
      h("div", { className: "drop-tips rise" },
        h("span", { className: "tip" }, h("kbd", null, "⌘V"), " " + t("粘贴截图")),
        h("span", { className: "tip-sep" }, "·"),
        h("span", { className: "tip" }, t("支持 PDF / PNG / JPG / TIFF")))
    );
  }

  // ================= File list =================
  const SUB = {
    queued: "排队中",
    ocr: "正在识别文字与公式…",
    parse: "正在解析版面…",
    gen: "正在生成 Word…",
  };
  const BUSY = { queued: 1, ocr: 1, parse: 1, gen: 1 };

  const Row = React.memo(function Row({ file, running, onRemove, onOpen, onReveal, onReport, onRetry, t }) {
    t = t || ((x) => x);
    const busy = !!BUSY[file.status];
    const done = file.status === "done" || file.status === "review";
    const failed = file.status === "error";
    const ext = (file.name.split(".").pop() || "").toUpperCase().slice(0, 4);

    const sub = failed ? (file.errNote || t("转换失败"))
      : file.status === "review" ? file.reviewNote
      : busy ? t(SUB[file.status])
      : t("{size} · {pages} 页").replace("{size}", file.size).replace("{pages}", file.pages);

    // ocr progress is time-estimated (10-81); parse/render are real stages.
    // Only the queued state uses an indeterminate bar.
    const bar = busy && h("div", { className: "track" },
      file.status === "queued"
        ? h("div", { className: "bar indet" })
        : h("div", { className: "bar", style: { transform: "scaleX(" + (file.progress || 0) / 100 + ")" } }));

    return h("div", { className: "row rise" + (failed ? " failed" : "") },
      h("div", { className: "ftype " + (file.type === "pdf" ? "pdf" : "img") }, ext),
      h("div", { className: "row-main" },
        h("div", { className: "row-name", title: file.name }, file.name),
        h("div", {
          className: "row-sub" + (failed ? " err" : file.status === "review" ? " warn" : ""),
          title: failed ? file.errNote : undefined,
        }, sub),
        bar),
      h("span", { className: "dot " + (busy ? "run" : file.status === "done" ? "ok"
                                       : file.status === "review" ? "warn" : failed ? "err" : "") }),
      failed
        ? h(React.Fragment, null,
            h("button", { className: "btn btn-quiet btn-sm", title: t("重新转换这个文件"),
                          onClick: () => onRetry(file) }, h(Retry), t("重试")),
            !running && h("button", { className: "icon-btn", title: t("移除"), onClick: () => onRemove(file.id) }, h(X)))
        : done
        ? h(React.Fragment, null,
            file.status === "review" && h("button", {
              className: "btn btn-quiet btn-sm", title: t("对照原件核对识别出的公式"),
              onClick: () => onReport(file),
            }, h(Check), t("复核")),
            h("button", { className: "btn btn-quiet btn-sm", onClick: () => onOpen(file) },
              file.outExt === "md" ? t("打开 Markdown") : t("打开 Word")),
            h("button", { className: "icon-btn", title: t("在访达中显示"), onClick: () => onReveal(file) }, h(Reveal)))
        : !busy && !running
        ? h("button", { className: "icon-btn", title: t("移除"), onClick: () => onRemove(file.id) }, h(X))
        : null
    );
  });

  function FileList(props) {
    return h("div", { className: "list" },
      props.files.map((f) => h(Row, Object.assign({ key: f.id, file: f }, props))));
  }

  // ================= Settings =================
  const THEMES = [["system", "跟随系统"], ["light", "浅色"], ["dark", "深色"]];

  const ENGINES = [["local", "本机识别"], ["cloud", "云端识别"]];
  const APPLY_URL = "https://mineru.net/apiManage/token";

  function Settings({ theme, onTheme, autoOpen, onAutoOpen, onClose,
                      engine, tokenHint, onEngine, onToken, onCheck, keyState, localAvailable,
                      model, onModelDownload, onModelCancel, exportFmt, onExport,
                      t, lang, onLang }) {
    t = t || ((x) => x);
    const [key, setKey] = React.useState("");
    const cloud = engine === "cloud";
    const noLocal = localAvailable === false;   // build without a local engine
    model = model || { ready: false, downloading: false, percent: 0, error: "" };
    return h("div", { className: "sheet-mask fade", onClick: onClose },
      h("div", { className: "sheet rise", role: "dialog", "aria-label": "设置",
                 onClick: (e) => e.stopPropagation() },
        h("div", { className: "sheet-head" },
          h("h2", null, t("设置")),
          h("button", { className: "icon-btn", title: t("关闭 (Esc)"), onClick: onClose }, h(X))),

        h("div", { className: "sheet-row" },
          h("div", { className: "lbl" },
            h("b", null, t("识别方式")),
            h("span", null,
              noLocal ? t("这个版本没有内置本地模型，只能用云端识别")
                : cloud ? t("文件会上传到 mineru.net 识别")
                : t("模型在本机运行，文件不上传"))),
          h("div", { className: "seg" },
            ENGINES.map(([v, label]) =>
              h("button", { key: v, className: engine === v ? "on" : "",
                            disabled: v === "local" && noLocal,
                            title: v === "local" && noLocal ? t("这个版本未包含本地模型") : undefined,
                            onClick: () => onEngine(v) }, t(label))))),

        !cloud && h("div", { className: "sheet-row col" },
          h("div", { className: "lbl" },
            h("b", null, t("识别模型")),
            h("span", null,
              model.ready ? t("已就绪，可以离线使用")
                : model.downloading ? t("正在下载… ") + model.percent + "%"
                : t("还没下载，约 2.2 GB"))),
          model.downloading && h("div", { className: "track dl" },
            h("div", { className: "bar", style: { transform: "scaleX(" + model.percent / 100 + ")" } })),
          !model.ready && h("div", { className: "key-foot" },
            model.downloading
              ? h("button", { className: "btn btn-quiet btn-sm", onClick: onModelCancel }, t("取消下载"))
              : h("button", { className: "btn btn-main btn-sm", onClick: onModelDownload }, t("下载模型")),
            model.error && h("span", { className: "key-state err" }, model.error))),

        cloud && h("div", { className: "sheet-row col" },
          h("div", { className: "lbl" },
            h("b", null, "API Key"),
            tokenHint
              ? h("span", { className: "key-saved" }, h(Check, { width: 13, height: 13 }),
                  t("已保存"), h("code", null, tokenHint))
              : h("span", null, t("还没填，转换会失败"))),
          h("div", { className: "key-line" },
            h("input", { className: "key-input", type: "password", placeholder: t("粘贴 mineru.net 的 API Key"),
                         value: key, onChange: (e) => setKey(e.target.value),
                         onKeyDown: (e) => { if (e.key === "Enter" && key.trim()) { onToken(key.trim()); setKey(""); } } }),
            h("button", { className: "btn btn-quiet btn-sm", disabled: !key.trim(),
                          onClick: () => { onToken(key.trim()); setKey(""); } }, t("保存")),
            h("button", { className: "btn btn-quiet btn-sm", onClick: onCheck }, t("测试"))),
          h("div", { className: "key-foot" },
            h("button", { className: "link", onClick: () => openExternal(APPLY_URL) }, t("去 mineru.net 申请 →")),
            keyState && h("span", { className: "key-state " + keyState.kind }, keyState.text)),
          // State the quota up front rather than surfacing a 429 mid-batch.
          h("div", { className: "key-note" },
            t("官方额度每天 "), h("b", null, t("1000 页")), t("，用完当天要排队或直接失败；"),
            t("超过 200 页的文件会自动分段上传，不用自己切。量大的时候改用本机识别，没有额度限制。"),
            h("br"),
            t("Key 的有效期为 "), h("b", null, t("90 天")), t("，到期不支持续期，需去官网重新创建并在这里换新。"))),

        h("div", { className: "sheet-row" },
          h("div", { className: "lbl" },
            h("b", null, t("导出格式")),
            h("span", null, exportFmt === "md"
              ? t("Markdown 文件，公式保留 LaTeX 原文")
              : t("Word 文档，公式为可编辑的原生公式"))),
          h("div", { className: "seg" },
            [["docx", "Word"], ["md", "Markdown"]].map(([v, label]) =>
              h("button", { key: v, className: exportFmt === v ? "on" : "",
                            onClick: () => onExport(v) }, label)))),

        h("div", { className: "sheet-row" },
          h("div", { className: "lbl" }, h("b", null, t("界面语言"))),
          h("div", { className: "seg" },
            [["zh", "中文"], ["en", "English"]].map(([v, label]) =>
              h("button", { key: v, className: lang === v ? "on" : "", onClick: () => onLang(v) }, label)))),

        h("div", { className: "sheet-row" },
          h("div", { className: "lbl" }, h("b", null, t("外观"))),
          h("div", { className: "seg" },
            THEMES.map(([v, label]) =>
              h("button", { key: v, className: theme === v ? "on" : "", onClick: () => onTheme(v) }, t(label))))),
        h("div", { className: "sheet-row" },
          h("div", { className: "lbl" },
            h("b", null, t("转换完打开文件夹")),
            h("span", null, t("整批转完自动弹出结果目录"))),
          h("button", { className: "toggle" + (autoOpen ? " on" : ""), role: "switch",
                        "aria-checked": autoOpen, onClick: () => onAutoOpen(!autoOpen) },
            h("span"))),
        h("div", { className: "sheet-note" },
          cloud
            ? t("云端识别会把文件上传到 mineru.net。涉密或未发表的稿子请切回本机识别。")
            : t("文件只在这台电脑上处理，不上传。"),
          t("识别准确率取决于扫描清晰度——"),
          t("转换完的 Word 旁边会附一份复核报告，列出无法自动确认的内容，请对照原件过一遍。"))));
  }

  function openExternal(url) {
    const t = window.__TAURI__;
    if (t && t.shell) t.shell.open(url);
    else window.open(url, "_blank");
  }

  // ================= First run: pick an engine =================
  // The first launch forces an explicit choice; otherwise the first conversion
  // just fails on a missing model or key. Picking one opens Settings directly.
  function Sheet({ onPick, t }) {
    t = t || ((x) => x);
    return h("div", { className: "drop gate" },
      h("div", { className: "drop-glyph rise" }, h("div", { className: "tray" })),
      h("div", { className: "drop-title rise" }, t("先挑一种识别方式")),
      h("div", { className: "drop-hint rise" }, t("随时可以在设置里更换。")),
      h("div", { className: "gate-cards rise" },
        h("button", { className: "gate-card", onClick: () => onPick("local") },
          h("b", null, t("本机识别")),
          h("span", null, t("下载 2.2 GB 的模型，之后文件不出这台电脑，没有额度限制。适合涉密或大批量。"))),
        h("button", { className: "gate-card", onClick: () => onPick("cloud") },
          h("b", null, t("云端识别")),
          h("span", null, t("填一个 mineru.net 的 API Key，不用下模型、不占算力。文件会上传，每天 1000 页额度。")))),
      h("div", { className: "drop-hint rise tight" },
        t("转换完的 Word 旁会附一份复核报告，列出无法自动确认的内容——请对照原件过一遍再用。")));
  }

  Object.assign(window, {
    Gear, Folder, Reveal, X, Check, Retry, Alert, Doc,
    DropArea, FileList, Settings, Sheet, makeT,
  });
})();
