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
