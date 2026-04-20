// Tauri shell entry. Phase 12 adds the Python sidecar spawn +
// graceful shutdown. Global kill-switch hotkey lands alongside the
// Phase 11 UI polish (todo: `tauri-plugin-global-shortcut`).

mod sidecar;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let handle = app.handle().clone();
            // Fire-and-forget; errors are logged inside spawn().
            if let Err(err) = sidecar::spawn(&handle) {
                eprintln!("failed to spawn backend sidecar: {err}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|handle, event| {
        sidecar::on_run_event(handle, &event);
    });
}
