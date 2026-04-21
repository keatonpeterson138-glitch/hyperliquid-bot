//! Python sidecar spawn for Phase 12 shipping.
//!
//! In production builds, the Tauri shell launches `uvicorn backend.main:app`
//! on `127.0.0.1:8787` as a child process, then kills it on window close.
//! The UI talks to the sidecar exactly the same way it does in dev, so no
//! frontend change is needed when this lights up.
//!
//! In dev (`cargo tauri dev`), we skip the spawn — the user runs uvicorn
//! themselves so hot-reload works without fighting us for the port.

use std::sync::Mutex;
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};

const SIDECAR_BIN: &str = "backend-sidecar";
const DEFAULT_HOST: &str = "127.0.0.1";
const DEFAULT_PORT: &str = "8787";

pub struct SidecarHandle(pub Mutex<Option<CommandChild>>);

pub fn spawn(app: &AppHandle) -> tauri::Result<()> {
    // Dev mode gets its own uvicorn; don't compete with it.
    if cfg!(debug_assertions) {
        return Ok(());
    }

    // Kill any zombie sidecar from a prior install. MSI upgrades can't
    // replace a running .exe, so the old process keeps holding port 8787
    // — the new sidecar then crashes on bind and every request 404s
    // against whatever routes the stale process had.
    kill_zombie_sidecars();

    let sidecar = app
        .shell()
        .sidecar(SIDECAR_BIN)
        .expect("sidecar binary configured in tauri.conf.json")
        .args(["--host", DEFAULT_HOST, "--port", DEFAULT_PORT]);

    let (mut rx, child) = sidecar.spawn().expect("failed to spawn backend sidecar");

    app.manage(SidecarHandle(Mutex::new(Some(child))));

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    eprintln!("[backend] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[backend!] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Error(err) => {
                    eprintln!("[backend-error] {}", err);
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!("[backend-exit] code={:?}", payload.code);
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(())
}

pub fn kill(app: &AppHandle) {
    if let Some(handle) = app.try_state::<SidecarHandle>() {
        if let Ok(mut guard) = handle.0.lock() {
            if let Some(child) = guard.take() {
                let _ = child.kill();
            }
        }
    }
}

pub fn on_run_event(app: &AppHandle, event: &RunEvent) {
    if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
        kill(app);
    }
}

/// Kill whatever process is listening on port 8787 — works regardless of
/// the sidecar's executable name.
///
/// We used to filter ``taskkill /IM`` by exe name, but Tauri strips the
/// target triple at bundle time (``backend-sidecar-x86_64-pc-windows-msvc.exe``
/// on disk becomes ``backend-sidecar.exe`` in the install), so the kill
/// missed the actual zombie. Port-based kill is name-invariant and fixes
/// the bug once and for all.
#[cfg(target_os = "windows")]
fn kill_zombie_sidecars() {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;

    // Find every PID listening on the sidecar port. One-liner batch:
    //   netstat -ano | findstr :8787 | findstr LISTENING
    // Powershell makes this cleaner + returns something we can parse.
    let ps = r#"
        Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { $_.OwningProcess } | Sort-Object -Unique
    "#;
    let out = std::process::Command::new("powershell")
        .args(["-NoProfile", "-Command", ps])
        .creation_flags(CREATE_NO_WINDOW)
        .output();
    if let Ok(out) = out {
        let stdout = String::from_utf8_lossy(&out.stdout);
        for line in stdout.lines() {
            let pid = line.trim();
            if pid.is_empty() || !pid.chars().all(|c| c.is_ascii_digit()) {
                continue;
            }
            let _ = std::process::Command::new("taskkill")
                .args(["/F", "/PID", pid])
                .creation_flags(CREATE_NO_WINDOW)
                .output();
        }
    }

    // Belt-and-suspenders: also taskkill by both possible exe names in
    // case a dead parent left orphans the port check can't see.
    for name in [SIDECAR_BIN, &format!("{SIDECAR_BIN}.exe"),
                 &format!("{SIDECAR_BIN}-x86_64-pc-windows-msvc.exe")] {
        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/T", "/IM", name])
            .creation_flags(CREATE_NO_WINDOW)
            .output();
    }
}

#[cfg(not(target_os = "windows"))]
fn kill_zombie_sidecars() {
    // Kill whatever holds the sidecar port (works regardless of binary name).
    if let Ok(out) = std::process::Command::new("lsof")
        .args(["-t", "-i", "tcp:8787", "-sTCP:LISTEN"])
        .output()
    {
        let stdout = String::from_utf8_lossy(&out.stdout);
        for pid in stdout.split_whitespace() {
            if pid.chars().all(|c| c.is_ascii_digit()) {
                let _ = std::process::Command::new("kill")
                    .args(["-9", pid])
                    .output();
            }
        }
    }
    // Fallback: name match.
    let _ = std::process::Command::new("pkill")
        .args(["-f", SIDECAR_BIN])
        .output();
}
