#!/usr/bin/env python3
"""Simple microphone test to verify audio input is working"""
import subprocess
import sys
import time

def test_microphone():
    print("🎤 Testing microphone access...")
    print("Please speak into your microphone for 3 seconds...")
    
    try:
        # Try to run whisper-stream with verbose output to see if it gets audio
        proc = subprocess.Popen([
            "whisper-stream",
            "--model", "/Users/bawomaleghemi/CascadeProjects/transcriber/models/ggml-base.en.bin",
            "--language", "en",
            "--step", "1000",
            "--length", "4000",
            "--threads", "2"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # Let it run for 3 seconds
        time.sleep(3)
        
        # Terminate and get output
        proc.terminate()
        stdout, stderr = proc.communicate()
        
        if stdout.strip():
            print("✅ Microphone working! Heard:")
            for line in stdout.strip().split('\n')[-5:]:  # Show last 5 lines
                if line.strip() and not line.startswith('['):
                    print(f"   {line}")
        else:
            print("❌ No audio detected")
            if stderr:
                print(f"Error: {stderr}")
                
    except FileNotFoundError:
        print("❌ whisper-stream not found. Install it first.")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    test_microphone()
