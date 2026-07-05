#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

struct PythonServer(Mutex<Option<Child>>);

fn find_server_binary() -> Option<std::path::PathBuf> {
    let bin_name = if cfg!(windows) { "server.exe" } else { "server" };

    if let Ok(exe) = std::env::current_exe() {
        let exe_dir = exe.parent().unwrap_or(std::path::Path::new("."));

        // 1. Tauri externalBin sidecar — placed next to the main exe
        let candidate = exe_dir.join(bin_name);
        if candidate.exists() { return Some(candidate); }

        // 2. macOS .app bundle: Contents/MacOS/../Resources/server
        let candidate = exe_dir.parent().unwrap_or(std::path::Path::new("."))
            .join("Resources").join(bin_name);
        if candidate.exists() { return Some(candidate); }

        // 3. macOS .app bundle: Contents/MacOS/server (Tauri v1 places externalBin here)
        let candidate = exe_dir.join(bin_name);
        if candidate.exists() { return Some(candidate); }
    }

    // 4. Dev mode: pyidist/server (after local PyInstaller build)
    let candidate = std::path::PathBuf::from(format!("pyidist/{}", bin_name));
    if candidate.exists() { return Some(candidate); }

    None
}

fn main() {
    tauri::Builder::default()
        .manage(PythonServer(Mutex::new(None)))
        .setup(|app| {
            println!("🕊️  RCCG COM Bible-lite starting...");

            let server_bin = find_server_binary().expect("Bundled server binary not found");
            println!("🚀 Launching: {}", server_bin.display());

            let mut cmd = Command::new(&server_bin);
            cmd.current_dir(server_bin.parent().unwrap())
               .stdout(Stdio::null())
               .stderr(Stdio::null());
            // On Windows, prevent a separate console window from appearing
            #[cfg(windows)]
            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
            let child = cmd.spawn().expect("Failed to start server binary");

            *app.state::<PythonServer>().0.lock().unwrap() = Some(child);

            // Give Python server a moment to start, then load the UI
            let handle = app.handle();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_millis(1500));
                if let Some(window) = handle.get_window("operator") {
                    window.eval("window.location.href = 'http://localhost:8080'")
                        .expect("Failed to navigate to server");
                }
            });

            Ok(())
        })
        .on_window_event(|event| {
            if let tauri::WindowEvent::Destroyed = event.event() {
                // Cleanup handled by on_exit below
            }
        })
        .build(tauri::generate_context!())
        .expect("error building tauri app")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                // Kill Python server on app exit
                if let Some(mut child) = app.state::<PythonServer>().0.lock().unwrap().take() {
                    println!("🛑 Shutting down Python server...");
                    let _ = child.kill();
                }
            }
        });
}
