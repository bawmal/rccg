use futures_util::SinkExt;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Arc;
use tokio::sync::broadcast;

const WS_PORT: u16 = 3001;
const UI_PORT: u16 = 3000;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let model_path = find_model()?;

    println!("🎙️  Offline Transcriber (Whisper)");
    println!("📦 Model: {}", model_path.display());
    println!("🔌 No internet required");
    println!("🌐 UI:     http://localhost:{}", UI_PORT);
    println!("🔌 WS:     ws://localhost:{}", WS_PORT);
    println!("Press Ctrl+C to stop\n");

    let (tx, _) = broadcast::channel::<String>(256);
    let tx = Arc::new(tx);

    // ── Spawn WebSocket server ──────────────────────────────────────
    let tx_ws = tx.clone();
    tokio::spawn(async move {
        let listener = tokio::net::TcpListener::bind(("0.0.0.0", WS_PORT)).await.unwrap();
        println!("✅ WebSocket server listening on :{}", WS_PORT);
        loop {
            if let Ok((stream, _)) = listener.accept().await {
                let rx = tx_ws.subscribe();
                tokio::spawn(handle_client(stream, rx));
            }
        }
    });

    // ── Spawn simple HTTP server for the UI ─────────────────────────
    tokio::spawn(async move {
        let listener = tokio::net::TcpListener::bind(("0.0.0.0", UI_PORT)).await.unwrap();
        let html = include_str!("../web-ui/index.html");
        println!("✅ UI server listening on :{}", UI_PORT);
        loop {
            if let Ok((mut stream, _)) = listener.accept().await {
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    html.len(), html
                );
                let _ = tokio::io::AsyncWriteExt::write_all(&mut stream, response.as_bytes()).await;
            }
        }
    });

    // ── Launch whisper-stream and pipe its output ───────────────────
    println!("🔗 Starting whisper-stream...");
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
        .map_err(|e| format!(
            "Failed to start whisper-stream: {e}\nInstall with: brew install whisper-cpp"
        ))?;

    println!("✅ Listening... speak now");
    println!("   Open http://localhost:{} in your browser\n", UI_PORT);

    let stdout = child.stdout.take().unwrap();
    let reader = BufReader::new(stdout);

    for line in reader.lines() {
        if let Ok(raw) = line {
            let trimmed = raw.trim().to_string();
            if !trimmed.is_empty()
                && !trimmed.starts_with('[')
                && !trimmed.starts_with("whisper")
                && !trimmed.starts_with("ggml")
                && !trimmed.starts_with("load_")
                && !trimmed.starts_with("main:")
                && !trimmed.starts_with("processing")
            {
                println!("📝 {}", trimmed);
                let _ = tx.send(trimmed);
            }
        }
    }

    child.wait()?;
    println!("\n👋 Transcription stopped");
    Ok(())
}

async fn handle_client(
    stream: tokio::net::TcpStream,
    mut rx: broadcast::Receiver<String>,
) {
    let ws_stream = match tokio_tungstenite::accept_async(stream).await {
        Ok(ws) => ws,
        Err(_) => return,
    };
    let (mut write, _) = futures_util::StreamExt::split(ws_stream);

    loop {
        match rx.recv().await {
            Ok(msg) => {
                if write
                    .send(tokio_tungstenite::tungstenite::Message::Text(msg))
                    .await
                    .is_err()
                {
                    break;
                }
            }
            Err(_) => break,
        }
    }
}

fn find_model() -> Result<PathBuf, Box<dyn std::error::Error>> {
    let home = std::env::var("HOME").unwrap_or_default();
    let candidates = [
        PathBuf::from("models/ggml-base.en.bin"),
        PathBuf::from(format!("{}/CascadeProjects/transcriber/models/ggml-base.en.bin", home)),
    ];
    for path in &candidates {
        if path.exists() {
            return Ok(path.clone());
        }
    }
    Err(format!(
        "Model not found. Run:\n  curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin -o {}/CascadeProjects/transcriber/models/ggml-base.en.bin",
        home
    ).into())
}
