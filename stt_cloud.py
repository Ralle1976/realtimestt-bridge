#!/usr/bin/env python3
"""
Cloud-based Speech-to-Text using OpenAI Whisper API

MUCH faster than local Whisper on systems without GPU.
Typical response time: 1-2 seconds vs 10-30+ seconds locally.

Cost: ~$0.006 per minute of audio

Requirements:
- pip install openai pyaudio
- OPENAI_API_KEY environment variable set

Usage:
  python3 stt_cloud.py

Environment Variables:
  STT_LANGUAGE - Language code (e.g., "de", "en"), default: auto-detect
  STT_MAX_SECONDS - Maximum recording time in seconds, default: 60
  STT_SILENCE_THRESHOLD - Silence duration to stop recording, default: 2.0
  OPENAI_API_KEY - Your OpenAI API key
"""

import io
import json
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

# Audio recording parameters
CHUNK = 1024
FORMAT_PYAUDIO = None  # Set after import
CHANNELS = 1
RATE = 16000  # Whisper optimal sample rate


def check_dependencies():
    """Check if required packages are installed."""
    missing = []

    try:
        import pyaudio
        global FORMAT_PYAUDIO
        FORMAT_PYAUDIO = pyaudio.paInt16
    except ImportError:
        missing.append("pyaudio")

    try:
        import openai
    except ImportError:
        missing.append("openai")

    if missing:
        return {
            "success": False,
            "error": "missing_dependencies",
            "message": f"Missing packages: {', '.join(missing)}. Install with: pip install {' '.join(missing)}",
            "retryable": False
        }

    return None


def record_audio(max_seconds: float = 60.0, silence_threshold: float = 2.0) -> bytes:
    """
    Record audio from microphone until silence is detected or max_seconds reached.

    Uses simple RMS-based silence detection for fast response.
    """
    import pyaudio
    import struct
    import math

    p = pyaudio.PyAudio()

    # Find the default input device
    try:
        default_device = p.get_default_input_device_info()
        device_index = default_device['index']
    except IOError:
        # Fallback to first available input device
        device_index = None
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev['maxInputChannels'] > 0:
                device_index = i
                break

        if device_index is None:
            p.terminate()
            raise RuntimeError("No audio input device found")

    stream = p.open(
        format=FORMAT_PYAUDIO,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=CHUNK
    )

    frames = []
    start_time = time.time()
    last_sound_time = time.time()
    has_speech = False

    # RMS threshold for silence detection (adjust as needed)
    SILENCE_RMS_THRESHOLD = 500

    print("Recording... (speak now)", file=sys.stderr)

    try:
        while True:
            elapsed = time.time() - start_time

            # Check max duration
            if elapsed > max_seconds:
                break

            # Read audio chunk
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)

            # Calculate RMS for silence detection
            shorts = struct.unpack(f'{CHUNK}h', data)
            rms = math.sqrt(sum(s ** 2 for s in shorts) / CHUNK)

            if rms > SILENCE_RMS_THRESHOLD:
                has_speech = True
                last_sound_time = time.time()

            # Stop if silence detected after speech
            if has_speech and (time.time() - last_sound_time) > silence_threshold:
                break

    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

    print("Recording finished.", file=sys.stderr)

    # Convert to WAV format in memory
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))

    return wav_buffer.getvalue()


def transcribe_with_openai(audio_data: bytes, language: str = None) -> dict:
    """Send audio to OpenAI Whisper API for transcription."""
    import openai

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "success": False,
            "error": "auth",
            "message": "OPENAI_API_KEY environment variable not set. Set it with: export OPENAI_API_KEY='your-key'",
            "retryable": False
        }

    client = openai.OpenAI(api_key=api_key)

    # Save to temp file (OpenAI API requires file-like object)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_data)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as audio_file:
            kwargs = {
                "model": "whisper-1",
                "file": audio_file,
                "response_format": "text"
            }

            if language:
                kwargs["language"] = language

            start = time.time()
            transcript = client.audio.transcriptions.create(**kwargs)
            elapsed = time.time() - start

        return {
            "success": True,
            "transcript": transcript.strip(),
            "processing_time": round(elapsed, 2)
        }

    except openai.AuthenticationError:
        return {
            "success": False,
            "error": "auth",
            "message": "OpenAI API authentication failed. Check your OPENAI_API_KEY.",
            "retryable": False
        }

    except openai.RateLimitError:
        return {
            "success": False,
            "error": "limit",
            "message": "OpenAI API rate limit reached. Wait before retrying.",
            "retryable": False
        }

    except openai.APIError as e:
        return {
            "success": False,
            "error": "api_error",
            "message": f"OpenAI API error: {str(e)}",
            "retryable": False
        }

    except Exception as e:
        return {
            "success": False,
            "error": "error",
            "message": f"Transcription failed: {str(e)}",
            "retryable": False
        }

    finally:
        # Clean up temp file
        try:
            Path(tmp_path).unlink()
        except:
            pass


def main():
    """Main entry point."""

    # Check dependencies first
    dep_error = check_dependencies()
    if dep_error:
        print(json.dumps(dep_error))
        return

    # Get configuration from environment
    language = os.getenv("STT_LANGUAGE") or None
    max_seconds = float(os.getenv("STT_MAX_SECONDS") or "60")
    silence_threshold = float(os.getenv("STT_SILENCE_THRESHOLD") or "2.0")

    try:
        # Record audio
        audio_data = record_audio(max_seconds=max_seconds, silence_threshold=silence_threshold)

        if len(audio_data) < 1000:  # Too short
            result = {
                "success": False,
                "error": "no_speech",
                "message": "No speech detected. Please speak louder or check microphone."
            }
        else:
            # Transcribe with OpenAI
            result = transcribe_with_openai(audio_data, language)

    except RuntimeError as e:
        result = {
            "success": False,
            "error": "audio_error",
            "message": str(e)
        }

    except Exception as e:
        result = {
            "success": False,
            "error": "error",
            "message": f"Unexpected error: {str(e)}"
        }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
