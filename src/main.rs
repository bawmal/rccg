use tauri::Manager;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

struct PythonServer(Mutex<Option<Child>>);

fn find_python() -> &'static str {
    // Try python3 first, fall back to python
    if std::process::Command::new("python3").arg("--version").output().is_ok() {
        "python3"
    } else {
        "python"
    }
}

fn find_serve_py() -> Option<std::path::PathBuf> {
    // 1. Next to the binary (bundled)
    if let Ok(exe) = std::env::current_exe() {
        let candidate = exe.parent().unwrap_or(std::path::Path::new(".")).join("serve.py");
        if candidate.exists() { return Some(candidate); }
        // macOS .app bundle: Contents/MacOS/../Resources/serve.py
        let candidate = exe.parent().unwrap_or(std::path::Path::new("."))
            .parent().unwrap_or(std::path::Path::new("."))
            .join("Resources").join("serve.py");
        if candidate.exists() { return Some(candidate); }
    }
    // 2. Dev mode: current working directory
    let candidate = std::path::PathBuf::from("serve.py");
    if candidate.exists() { return Some(candidate); }
    // 3. Absolute dev path
    let home = std::env::var("HOME").unwrap_or_default();
    let candidate = std::path::PathBuf::from(format!("{}/CascadeProjects/transcriber/serve.py", home));
    if candidate.exists() { return Some(candidate); }
    None
}

fn main() {
    tauri::Builder::default()
        .manage(PythonServer(Mutex::new(None)))
        .setup(|app| {
            println!("🕊️  RCCG COM Bible-lite starting...");

            let serve_py = find_serve_py().expect("serve.py not found");
            let python  = find_python();
            println!("� Launching: {} {}", python, serve_py.display());

            let child = Command::new(python)
                .arg(&serve_py)
                .current_dir(serve_py.parent().unwrap())
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit())
                .spawn()
                .expect("Failed to start Python server");

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
