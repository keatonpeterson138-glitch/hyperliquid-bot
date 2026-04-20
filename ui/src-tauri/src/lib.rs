// Tauri shell entry. Phase 2 adds the Python sidecar spawn,
// OS keychain plugin, and kill-switch global shortcut.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
