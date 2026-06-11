# 🎙️ Clean Transcriber

A minimal, working audio transcription app using Deepgram API.

## ✅ What Works

- **Audio capture** at native device sample rate (48000Hz)
- **Deepgram WebSocket** connection with proper authentication
- **Live transcription** with real-time output
- **Cross-platform** (macOS, Windows, Linux)

## 🚀 Quick Start

### 1. Set API Key
```bash
cd transcriber
echo "DEEPGRAM_API_KEY=your_api_key_here" > .env
```

### 2. Run Simple Version
```bash
cargo run --bin simple
```

That's it! The app will:
- Show available audio devices
- Connect to Deepgram
- Start transcribing live audio
- Display results in real-time

## 📁 Project Structure

```
transcriber/
├── src/
│   ├── simple.rs     # Working command-line transcriber ✅
│   └── server.rs     # Web server version (complex)
├── static/
│   └── index.html    # Web UI (if needed)
├── Cargo.toml
├── .env
└── README.md
```

## 🔧 Technical Details

- **Language**: Rust
- **Audio**: `cpal` crate for cross-platform audio capture
- **WebSocket**: `tokio-tungstenite` for Deepgram connection
- **Sample Rate**: Automatically uses device native rate (48000Hz)
- **Authentication**: Deepgram API token in WebSocket header

## 🎯 Why This Works

1. **Simple Architecture**: No complex UI, Bible detection, or ONNX models
2. **Proven Foundation**: Based on working simple-transcriber code
3. **Native Audio**: Uses device sample rate instead of forcing 16000Hz
4. **Clean Dependencies**: Minimal, focused dependency set

## 📝 Usage Examples

### Basic Transcription
```bash
cargo run --bin simple
```

Output:
```
🎙️  Clean Transcriber
🔑 API Key: d3c5a34d...
🎤 Using device: MacBook Air Microphone
📊 Device config: 48000Hz, 2 channels
🔗 Connecting to Deepgram...
✅ Connected to Deepgram
🎧 Listening for transcription...
🔄 Hello world
📝 Hello world
🔄 How are you today?
📝 How are you today?
```

## 🔍 Troubleshooting

### Microphone Permission
- First run: macOS will ask for microphone permission
- Grant permission when prompted
- Restart app if permission was denied

### API Key Issues
- Verify Deepgram API key is valid
- Check `.env` file format: `DEEPGRAM_API_KEY=your_key`
- Ensure no extra spaces or quotes

### Audio Device Issues
- App uses default audio device
- Supports multi-channel audio
- Automatically handles sample rate conversion

## 🚧 Future Enhancements

If needed, you can add:
- Web UI (server.rs has starter code)
- Audio device selection
- File output
- Custom vocabulary

## 📊 Comparison to Rhema

| Feature | Clean Transcriber | Rhema |
|---------|-------------------|-------|
| Working transcription | ✅ | ❌ (UI issues) |
| Simple setup | ✅ | ❌ (complex) |
| Audio capture | ✅ | ✅ |
| Deepgram integration | ✅ | ✅ |
| Bible verse detection | ❌ | ✅ |
| Web UI | ❌ (optional) | ✅ |

## 🎉 Success!

This is the working transcription solution you need. No complex setup, no UI issues, just clean, functional audio transcription.
