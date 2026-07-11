#!/usr/bin/env python3
import http.server
import socketserver
import websockets
import asyncio
import json
import subprocess
import threading
import os

PORT = 8080
WS_PORT = 8765

class SimpleHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="/Users/bawomaleghemi/CascadeProjects/transcriber/web-ui", **kwargs)
    
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

def start_http_server():
    """Start HTTP server"""
    with socketserver.TCPServer(("", PORT), SimpleHTTPRequestHandler) as httpd:
        print(f"🌐 Web UI running at: http://localhost:{PORT}")
        httpd.serve_forever()

async def websocket_handler(websocket, path):
    """Handle WebSocket connections"""
    print(f"🔗 WebSocket connected from {websocket.remote_address}")
    
    try:
        # Send initial connection message
        await websocket.send(json.dumps({
            "type": "status",
            "message": "Connected to RCCG COM Bible-lite"
        }))
        
        # Start whisper-stream
        model_path = "/Users/bawomaleghemi/CascadeProjects/transcriber/models/ggml-base.en.bin"
        if not os.path.exists(model_path):
            await websocket.send(json.dumps({
                "type": "error",
                "message": "Whisper model not found"
            }))
            return
        
        process = subprocess.Popen([
            "whisper-stream",
            "--model", model_path,
            "--language", "en",
            "--step", "2000",
            "--length", "8000",
            "--keep", "200",
            "--threads", "4"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        print("🎙️ Whisper stream started")
        
        # Read from whisper-stream
        while True:
            line = process.stdout.readline()
            if not line:
                break
                
            # Clean the output
            cleaned = line.replace("\x1B[2K", "").replace("\x1B[1G", "").replace("\x1B[0m", "")
            cleaned = cleaned.strip()
            
            # Send valid transcriptions
            if cleaned and not cleaned.startswith('[') and not cleaned.startswith("whisper"):
                await websocket.send(json.dumps({
                    "type": "transcription",
                    "text": cleaned
                }))
                
    except websockets.exceptions.ConnectionClosed:
        print("🔌 WebSocket disconnected")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'process' in locals():
            process.terminate()

async def main():
    """Main function"""
    print("🚀 Starting RCCG COM Bible-lite Web Server")
    print("=" * 50)
    
    # Start HTTP server in background
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    
    # Start WebSocket server
    async with websockets.serve(websocket_handler, "localhost", WS_PORT):
        print(f"🔌 WebSocket server on: ws://localhost:{WS_PORT}")
        print("=" * 50)
        print(f"📱 Open browser: http://localhost:{PORT}")
        print("🎤 Ensure microphone is connected")
        print("=" * 50)
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
