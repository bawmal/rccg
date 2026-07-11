use crate::bible;
use futures_util::{SinkExt, StreamExt};
use std::sync::{Arc, Mutex};
use tokio::sync::broadcast;
use tokio_tungstenite::tungstenite::Message;

pub async fn serve_http(port: u16) {
    let listener = tokio::net::TcpListener::bind(("0.0.0.0", port))
        .await
        .unwrap();
    let html = include_str!("../web-ui/index.html");
    loop {
        if let Ok((mut stream, _)) = listener.accept().await {
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                html.len(),
                html
            );
            let _ = tokio::io::AsyncWriteExt::write_all(&mut stream, response.as_bytes()).await;
        }
    }
}

pub async fn serve_ws(
    port: u16,
    tx: Arc<broadcast::Sender<String>>,
    db: Arc<Mutex<rusqlite::Connection>>,
    active_translation: Arc<Mutex<String>>,
) {
    let listener = tokio::net::TcpListener::bind(("0.0.0.0", port))
        .await
        .unwrap();
    println!("WebSocket server on :{}", port);
    loop {
        if let Ok((stream, _)) = listener.accept().await {
            let rx = tx.subscribe();
            let tx2 = tx.clone();
            let db2 = db.clone();
            let at2 = active_translation.clone();
            tokio::spawn(handle_ws_client(stream, rx, tx2, db2, at2));
        }
    }
}

async fn handle_ws_client(
    stream: tokio::net::TcpStream,
    mut rx: broadcast::Receiver<String>,
    tx: Arc<broadcast::Sender<String>>,
    db: Arc<Mutex<rusqlite::Connection>>,
    active_translation: Arc<Mutex<String>>,
) {
    let ws = match tokio_tungstenite::accept_async(stream).await {
        Ok(ws) => ws,
        Err(_) => return,
    };
    let (mut write, mut read) = ws.split();

    // Send initial state
    {
        let at = active_translation.lock().unwrap().clone();
        let db_lock = db.lock().unwrap();
        let translations = bible::get_translations(&db_lock).unwrap_or_default();
        drop(db_lock);
        let init = serde_json::json!({
            "type": "init",
            "translation": at,
            "translations": translations.iter().map(|(a, t)| serde_json::json!({"abbr": a, "title": t})).collect::<Vec<_>>()
        });
        let _ = write.send(Message::Text(init.to_string())).await;
    }

    loop {
        tokio::select! {
            result = rx.recv() => {
                match result {
                    Ok(msg) => { if write.send(Message::Text(msg)).await.is_err() { break; } }
                    Err(_) => break,
                }
            }
            msg = read.next() => {
                match msg {
                    Some(Ok(Message::Text(text))) => {
                        handle_browser_msg(&text, &tx, &db, &active_translation).await;
                    }
                    Some(Ok(Message::Close(_))) | None => break,
                    _ => {}
                }
            }
        }
    }
}

async fn handle_browser_msg(
    text: &str,
    tx: &broadcast::Sender<String>,
    db: &Arc<Mutex<rusqlite::Connection>>,
    active_translation: &Arc<Mutex<String>>,
) {
    let Ok(msg) = serde_json::from_str::<serde_json::Value>(text) else { return };
    let action = msg.get("action").and_then(|a| a.as_str()).unwrap_or("");
    match action {
        "set_translation" => {
            if let Some(t) = msg.get("translation").and_then(|t| t.as_str()) {
                let mut at = active_translation.lock().unwrap();
                *at = t.to_uppercase();
                let event = serde_json::json!({"type": "translation_change", "translation": at.clone()});
                let _ = tx.send(event.to_string());
            }
        }
        "select_candidate" | "lookup" => {
            if let (Some(book), Some(ch), Some(vs)) = (
                msg.get("book_name").and_then(|v| v.as_str()),
                msg.get("chapter").and_then(|v| v.as_i64()),
                msg.get("verse").and_then(|v| v.as_i64()),
            ) {
                let at = active_translation.lock().unwrap().clone();
                let db_lock = db.lock().unwrap();
                if let Ok(Some(verse)) = bible::get_verse_by_ref(&db_lock, book, ch, vs, &at) {
                    let event = serde_json::json!({
                        "type": "verse_detected", "source": "manual", "confidence": 1.0,
                        "reference": verse.reference(), "translation": at,
                        "book_name": verse.book_name, "chapter": verse.chapter,
                        "verse": verse.verse, "text": verse.text
                    });
                    let _ = tx.send(event.to_string());
                }
            }
        }
        _ => {}
    }
}
