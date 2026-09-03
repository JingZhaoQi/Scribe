// Tauri shell for pdf2word. On startup it launches the Python FastAPI backend
// (p2w_gui.server) as a child process; the web UI talks to it over HTTP. The
// child is killed when the app exits.
#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Manager};

struct Backend(Mutex<Option<Child>>);

/// Sync NSWindow.appearance when the frontend switches theme.
///
/// Required because both the window material (NSVisualEffectView) and the
/// webview's prefers-color-scheme follow window appearance. theme is
/// "light" | "dark" | "system".
#[tauri::command]
fn set_appearance(theme: String, app: AppHandle) {
    #[cfg(target_os = "macos")]
    if let Some(win) = app.get_window("main") {
        use cocoa::base::{id, nil};
        use cocoa::foundation::NSString;
        use objc::{class, msg_send, sel, sel_impl};
        unsafe {
            let ns_window = win.ns_window().unwrap() as id;
            let appearance: id = match theme.as_str() {
                "light" | "dark" => {
                    let name = if theme == "light" {
                        "NSAppearanceNameAqua"
                    } else {
                        "NSAppearanceNameDarkAqua"
                    };
                    let s = NSString::alloc(nil).init_str(name);
                    msg_send![class!(NSAppearance), appearanceNamed: s]
                }
                _ => nil, // system: follow the OS
            };
            let _: () = msg_send![ns_window, setAppearance: appearance];
        }
    }
    #[cfg(not(target_os = "macos"))]
    let _ = (theme, app);
}

/// Locate the backend `src` directory plus any bundled python / mineru.
///
/// Packaged builds keep these under the bundle's Resources/; development uses
/// the repository. `env!("CARGO_MANIFEST_DIR")` must never be used as a runtime
/// path -- it is a compile-time constant pointing at the build machine.
struct Layout {
    src: PathBuf,
    /// Bundled interpreter (Resources/python), shared by p2w and MinerU.
    bundled_python: Option<PathBuf>,
    /// Development-only .venv-mineru at the repo root
    dev_mineru: Option<PathBuf>,
}

fn locate(app: &AppHandle) -> Option<Layout> {
    // Packaged: <bundle>/Contents/Resources/payload/. Development: repo root.
    let bundled = app.path_resolver().resource_dir().map(|r| r.join("payload"));
    let dev_repo = Path::new(env!("CARGO_MANIFEST_DIR")).parent().map(Path::to_path_buf);

    for root in bundled.into_iter().chain(dev_repo) {
        let src = root.join("src");
        if !src.join("p2w_gui").is_dir() {
            continue;
        }
        let exists = |p: PathBuf| if p.exists() { Some(p) } else { None };
        return Some(Layout {
            src,
            bundled_python: exists(root.join("python/bin/python3.12"))
                .or_else(|| exists(root.join("python/bin/python3")))
                .or_else(|| exists(root.join("python/python.exe"))),
            dev_mineru: exists(root.join(".venv-mineru/bin/mineru"))
                .or_else(|| exists(root.join(".venv-mineru/Scripts/mineru.exe"))),
        });
    }
    None
}

fn spawn_backend(app: &AppHandle) -> Option<Child> {
    // Port 8756 may still hold a backend from a previous run. A new frontend
    // talking to an old backend gets unexpected shapes from missing endpoints,
    // so clear the port before spawning ours.
    #[cfg(unix)]
    let _ = Command::new("sh")
        .args(["-c", "lsof -ti:8756 | xargs kill -9 2>/dev/null"])
        .status();
    #[cfg(windows)]
    let _ = Command::new("powershell")
        .args(["-NoProfile", "-Command",
               "Get-NetTCPConnection -LocalPort 8756 -ErrorAction SilentlyContinue | \
                ForEach-Object { Stop-Process -Id $_.OwningProcess -Force \
                -ErrorAction SilentlyContinue }"])
        .status();

    let Layout { src, bundled_python, dev_mineru } = locate(app)?;
    let bundled = bundled_python.is_some();

    // Interpreter priority: bundled > P2W_PYTHON > python3 on PATH
    let python = bundled_python
        .map(|p| p.to_string_lossy().into_owned())
        .or_else(|| std::env::var("P2W_PYTHON").ok())
        .unwrap_or_else(|| "python3".to_string());

    let mut cmd = Command::new(&python);
    cmd.args(["-m", "p2w_gui.server", "8756"]).env("PYTHONPATH", &src);
    // This process is windows_subsystem="windows", so the child inherits no
    // console: its std handles are invalid and Python sets sys.stdout to None.
    // Hand it explicit null streams instead, and suppress the console window
    // Windows would otherwise pop up for a console-subsystem child.
    cmd.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    if bundled {
        // In bundled builds MinerU lives in this interpreter; `python -m` avoids
        // the broken console-script shebang.
        cmd.env("P2W_MINERU_PYTHON", &python);
    } else if let Some(mineru) = dev_mineru {
        cmd.env("P2W_MINERU", mineru);
    }
    cmd.spawn().ok()
}

fn main() {
    tauri::Builder::default()
        .manage(Backend(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![set_appearance])
        .setup(|app| {
            // Native macOS vibrancy: the window is transparent with an
            // NSVisualEffectView behind it, so the desktop actually shows
            // through. CSS backdrop-filter cannot do this.
            #[cfg(target_os = "macos")]
            {
                use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial,
                                      NSVisualEffectState};
                if let Some(win) = app.get_window("main") {
                    // Sidebar is denser than HudWindow so text stays legible;
                    // Active keeps the material when the window loses focus.
                    let _ = apply_vibrancy(&win, NSVisualEffectMaterial::Sidebar,
                                           Some(NSVisualEffectState::Active), Some(16.0));
                }
            }
            if let Some(child) = spawn_backend(&app.handle()) {
                *app.state::<Backend>().0.lock().unwrap() = Some(child);
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
