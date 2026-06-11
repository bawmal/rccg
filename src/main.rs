use tauri::{Manager, Window};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::io::{BufRead, BufReader};

mod bible;
mod detector;

pub struct AppState {
    pub db: Arc<std::sync::Mutex<rusqlite::Connection>>,
    pub active_translation: Arc<std::sync::Mutex<String>>,
}

fn find_model() -> Result<PathBuf, String> {
    let home = std::env::var("HOME").unwrap_or_default();
    let candidates = [
        PathBuf::from("models/ggml-base.en.bin"),
        PathBuf::from(format!("{}/CascadeProjects/transcriber/models/ggml-base.en.bin", home)),
    ];
    for p in &candidates {
        if p.exists() { return Ok(p.clone()); }
    }
    Err(format!("Whisper model not found. Run:\n  curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin -o {}/CascadeProjects/transcriber/models/ggml-base.en.bin", home))
}

fn find_db() -> Result<PathBuf, String> {
    let home = std::env::var("HOME").unwrap_or_default();
    let candidates = [
        PathBuf::from("data/rhema.db"),
        PathBuf::from(format!("{}/CascadeProjects/transcriber/data/rhema.db", home)),
    ];
    for p in &candidates {
        if p.exists() { return Ok(p.clone()); }
    }
    Err("Bible database (rhema.db) not found.".to_string())
}

fn main() {
    let model_path = find_model().expect("Model not found");
    let db_path = find_db().expect("Database not found");

    let db = Arc::new(std::sync::Mutex::new(bible::open_db(&db_path).expect("Failed to open DB")));
    let active_translation = Arc::new(std::sync::Mutex::new("KJV".to_string()));

    tauri::Builder::default()
        .manage(AppState {
            db: db.clone(),
            active_translation: active_translation.clone(),
        })
        .invoke_handler(tauri::generate_handler![
            lookup_verse,
            search_verse_text,
            get_translations,
            set_translation,
            detect_reference,
            open_projection_window,
            close_projection_window,
            update_projection,
            get_available_monitors
        ])
        .setup(move |app| {
            println!("🕊️  RCCG COM Bible-lite — Offline Bible Transcriber");
            println!("📦 Model:    {}", model_path.display());
            println!("📖 Database: {}", db_path.display());
            
            let app_handle = app.handle();
            let db_thread = db.clone();
            let at_thread = active_translation.clone();

            std::thread::spawn(move || {
                println!("🎙️  Starting whisper-stream...");
                let mut child = Command::new("whisper-stream")
                    .args([
                        "--model", model_path.to_str().unwrap(),
                        "--language", "en",
                        "--step", "2000",
                        "--length", "8000",
                        "--keep", "200",
                        "--threads", "4",
                    ])
                    .stdout(Stdio::piped())
                    .stderr(Stdio::null())
                    .spawn()
                    .expect("Failed to start whisper-stream");

                let stdout = child.stdout.take().unwrap();
                let reader = BufReader::new(stdout);

                for line in reader.lines() {
                    let Ok(raw) = line else { break };
                    let cleaned = raw.replace("\x1B[2K", "").replace("\x1B[1G", "").replace("\x1B[0m", "").replace("\r", "").replace("\n", " ");
                    let trimmed = cleaned.trim().to_string();

                    if trimmed.is_empty() || trimmed.starts_with('[') || trimmed.starts_with("whisper")
                        || trimmed.starts_with("ggml") || trimmed.starts_with("load_")
                        || trimmed.starts_with("main:") || trimmed.starts_with("processing") {
                        continue;
                    }

                    let normalized = if trimmed.contains("world") || trimmed.contains("word") {
                        trimmed.replace("the world was", "the Word was")
                               .replace("The world was", "The Word was")
                               .replace(" was the word", " was the Word")
                               .replace(" was the world", " was the Word")
                    } else {
                        trimmed.clone()
                    };

                    let at = at_thread.lock().unwrap().clone();

                    if let Some(trans) = detector::detect_translation(&normalized) {
                        let mut current = at_thread.lock().unwrap();
                        if *current != trans {
                            println!("🔄 Switching to {}", trans);
                            *current = trans.clone();
                            let _ = app_handle.emit_all("translation_change", trans);
                        }
                    }

                    if let Some(verse_ref) = detector::detect_verse_reference(&normalized) {
                        let translation = detector::detect_translation(&normalized).unwrap_or(at.clone());
                        println!("🔍 Detected ref: '{}' translation: '{}'", verse_ref, translation);
                        
                        // Parse "Book Chapter:Verse" -> (book, chapter, verse)
                        let parts: Vec<&str> = verse_ref.split(' ').collect();
                        if parts.len() >= 2 {
                            let book_name = parts[0..parts.len()-1].join(" ");
                            let cv = parts[parts.len()-1];
                            if let Some((ch_str, vs_str)) = cv.split_once(':') {
                                if let (Ok(chapter), Ok(verse)) = (ch_str.parse::<i64>(), vs_str.parse::<i64>()) {
                                    let db_lock = db_thread.lock().unwrap();
                                    match bible::get_verse_by_ref(&db_lock, &book_name, chapter, verse, &translation) {
                                        Ok(Some(verse)) => {
                                            println!("📖 {} {} — {}", translation, verse_ref, &verse.text[..verse.text.len().min(60)]);
                                            let _ = app_handle.emit_all("verse_detected", serde_json::json!({
                                                "reference": verse_ref,
                                                "translation": translation,
                                                "book_name": verse.book_name,
                                                "chapter": verse.chapter,
                                                "verse": verse.verse,
                                                "text": verse.text
                                            }));
                                        }
                                        Ok(None) => println!("⚠️  Ref detected but not found: {} {}", translation, verse_ref),
                                        Err(e) => println!("❌ DB error: {}", e),
                                    }
                                }
                            }
                        }
                    } else {
                        let db_lock = db_thread.lock().unwrap();
                        let results = bible::search_verses(&db_lock, &normalized, &at, 5);
                        drop(db_lock);
                        if let Ok(results) = results {
                            if let Some(top) = results.first() {
                                if top.score >= 0.95 {
                                    let _ = app_handle.emit_all("verse_detected", serde_json::json!({
                                        "reference": top.verse.reference(),
                                        "translation": at,
                                        "book_name": top.verse.book_name,
                                        "chapter": top.verse.chapter,
                                        "verse": top.verse.verse,
                                        "text": top.verse.text
                                    }));
                                }
                            }
                        }
                    }
                }
                
                let _ = child.wait();
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[tauri::command]
fn lookup_verse(
    state: tauri::State<AppState>,
    book_name: String,
    chapter: i64,
    verse: i64,
    translation: Option<String>,
) -> Result<Option<bible::Verse>, String> {
    let trans = translation.unwrap_or_else(|| state.active_translation.lock().unwrap().clone());
    let db_lock = state.db.lock().map_err(|e| e.to_string())?;
    bible::get_verse_by_ref(&db_lock, &book_name, chapter, verse, &trans).map_err(|e| e.to_string())
}

#[tauri::command]
fn search_verse_text(
    state: tauri::State<AppState>,
    text: String,
    limit: Option<usize>,
) -> Result<Vec<(bible::Verse, f64)>, String> {
    let limit = limit.unwrap_or(5);
    let at = state.active_translation.lock().unwrap().clone();
    let db_lock = state.db.lock().map_err(|e| e.to_string())?;
    let results = bible::search_verses(&db_lock, &text, &at, limit).map_err(|e| e.to_string())?;
    Ok(results.into_iter().map(|r| (r.verse, r.score)).collect())
}

#[tauri::command]
fn get_translations(state: tauri::State<AppState>) -> Result<Vec<(String, String)>, String> {
    let db_lock = state.db.lock().map_err(|e| e.to_string())?;
    bible::get_translations(&db_lock).map_err(|e| e.to_string())
}

#[tauri::command]
fn set_translation(state: tauri::State<AppState>, translation: String) -> Result<(), String> {
    let mut at = state.active_translation.lock().map_err(|e| e.to_string())?;
    *at = translation.to_uppercase();
    Ok(())
}

#[tauri::command]
fn detect_reference(text: String) -> Option<String> {
    detector::detect_verse_reference(&text)
}

#[tauri::command]
fn get_available_monitors(window: Window) -> Vec<String> {
    match window.available_monitors() {
        Ok(monitors) => monitors.iter().enumerate().map(|(i, m)| {
            let name = m.name().unwrap_or_else(|| format!("Monitor {}", i).into());
            format!("{}: {}x{}", name, m.size().width, m.size().height)
        }).collect(),
        Err(_) => vec![]
    }
}

#[tauri::command]
fn open_projection_window(
    app: tauri::AppHandle,
    window: Window,
    monitor_index: Option<usize>,
) -> Result<(), String> {
    let monitors = window.available_monitors().map_err(|e| e.to_string())?;
    
    // Use specified monitor, or default to index 1 (external) if available, otherwise 0
    let target_monitor = if let Some(idx) = monitor_index {
        monitors.get(idx).cloned()
    } else if monitors.len() > 1 {
        monitors.get(1).cloned()  // Second monitor (external)
    } else {
        monitors.first().cloned()  // Primary monitor
    };
    
    let monitor = target_monitor.ok_or("No monitor found")?;
    let monitor_size = monitor.size();
    let monitor_pos = monitor.position();

    let proj_window = tauri::WindowBuilder::new(
        &app,
        "projection",
        tauri::WindowUrl::App("index.html?mode=projection".into())
    )
    .title("RCCG COM Bible-lite — Projection")
    .decorations(false)
    .fullscreen(true)
    .inner_size(monitor_size.width as f64, monitor_size.height as f64)
    .position(monitor_pos.x as f64, monitor_pos.y as f64)
    .always_on_top(true)
    .build()
    .map_err(|e| e.to_string())?;

    proj_window.set_focus().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn close_projection_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_window("projection") {
        window.close().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn update_projection(
    app: tauri::AppHandle,
    reference: String,
    book_name: String,
    chapter: i64,
    verse: i64,
    text: String,
    translation: String,
) -> Result<(), String> {
    if let Some(window) = app.get_window("projection") {
        let js = format!(
            r#"if(window.updateProjection){{window.updateProjection("{}", "{}", {}, {}, "{}", "{}");}}"#,
            reference.replace("\"", "\\\""),
            book_name.replace("\"", "\\\""),
            chapter,
            verse,
            text.replace("\"", "\\\"").replace("\n", " "),
            translation.replace("\"", "\\\"")
        );
        window.eval(&js).map_err(|e| e.to_string())?;
    }
    Ok(())
}
