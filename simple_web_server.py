#!/usr/bin/env python3
import asyncio
import websockets
import json
import threading
import subprocess
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import sys

class CORSHTTPRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

def start_http_server():
    """Start HTTP server for web UI"""
    os.chdir('/Users/bawomaleghemi/CascadeProjects/transcriber/web-ui')
    server = HTTPServer(('localhost', 8080), CORSHTTPRequestHandler)
    print("🌐 Web UI available at: http://localhost:8080")
    server.serve_forever()

async def handle_websocket(websocket, path):
    """Handle WebSocket connections"""
    print(f"🔗 WebSocket client connected: {websocket.remote_address}")
    
    # Start whisper-stream process
    whisper_process = None
    try:
        model_path = "/Users/bawomaleghemi/CascadeProjects/transcriber/models/ggml-base.en.bin"
        whisper_process = subprocess.Popen([
            "whisper-stream",
            "--model", model_path,
            "--language", "en",
            "--step", "2000",
            "--length", "8000",
            "--keep", "200",
            "--threads", "4"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        print("🎙️  Whisper stream started")
        
        # Send initial status
        await websocket.send(json.dumps({
            "type": "status",
            "message": "Connected and ready"
        }))
        
        # Read from whisper-stream and send to client
        while True:
            if whisper_process.poll() is not None:
                break
                
            line = whisper_process.stdout.readline()
            if line:
                cleaned = line.replace("\x1B[2K", "").replace("\x1B[1G", "").replace("\x1B[0m", "").replace("\r", "").replace("\n", " ")
                cleaned = cleaned.strip()
                
                if cleaned and not cleaned.startswith('[') and not cleaned.startswith("whisper"):
                    # Send transcription to client
                    await websocket.send(json.dumps({
                        "type": "transcription",
                        "text": cleaned
                    }))
            
            await asyncio.sleep(0.01)
            
    except websockets.exceptions.ConnectionClosed:
        print("🔌 WebSocket client disconnected")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if whisper_process:
            whisper_process.terminate()
            print("🛑 Whisper stream stopped")

async def main():
    """Main server function"""
    print("🚀 Starting RCCG COM Bible-lite Web Server")
    print("=" * 50)
    
    # Start HTTP server in separate thread
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    
    # Start WebSocket server
    websocket_server = await websockets.serve(handle_websocket, "localhost", 8765)
    print("🔌 WebSocket server running on: ws://localhost:8765")
    print("=" * 50)
    print("📱 Open your browser and go to: http://localhost:8080")
    print("🎤 Make sure your microphone is connected and permitted")
    print("=" * 50)
    
    await websocket_server.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
