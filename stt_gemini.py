#!/usr/bin/env python3
"""
Speech-to-Text using Gemini CLI

Uses Gemini's multimodal capabilities to transcribe audio.
Leverages existing Gemini CLI OAuth authentication.

Requirements:
- gemini CLI installed and authenticated
- pip install pyaudio

Usage:
  python3 stt_gemini.py

Environment Variables:
  STT_LANGUAGE - Language hint (e.g., "de", "en"), default: auto-detect
  STT_MAX_SECONDS - Maximum recording time in seconds, default: 60
  STT_SILENCE_THRESHOLD - Silence duration to stop recording, default: 2.0
"""

import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

# Audio recording parameters
CHUNK = 1024
FORMAT_PYAUDIO = None  # Set after import
CHANNELS = 1
RATE = 16000


def check_dependencies():
    """Check if required packages are installed."""
    missing = []

    try:
        import pyaudio
        global FORMAT_PYAUDIO
        FORMAT_PYAUDIO = pyaudio.paInt16
    except ImportError:
        missing.append("pyaudio")

    # Check gemini CLI
    try:
        result = subprocess.run(
            ["gemini", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            missing.append("gemini-cli (not working)")
    except FileNotFoundError:
        missing.append("gemini-cli (not installed)")
    except Exception:
        missing.append("gemini-cli (error)")

    if missing:
        return {
            "success": False,
            "error": "missing_dependencies",
            "message": f"Missing: {', '.join(missing)}",
            "retryable": False
        }

    return None


def record_audio(max_seconds: float = 60.0, silence_threshold: float = 2.0) -> bytes:
    """Record audio from microphone until silence is detected."""
    import pyaudio
    import struct
    import math

    p = pyaudio.PyAudio()

    # Find the default input device
    try:
        default_device = p.get_default_input_device_info()
        device_index = default_device['index']
    except IOError:
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
    SILENCE_RMS_THRESHOLD = 500

    print("Recording... (speak now)", file=sys.stderr)

    try:
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_seconds:
                break

            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)

            shorts = struct.unpack(f'{CHUNK}h', data)
            rms = math.sqrt(sum(s ** 2 for s in shorts) / CHUNK)

            if rms > SILENCE_RMS_THRESHOLD:
                has_speech = True
                last_sound_time = time.time()

            if has_speech and (time.time() - last_sound_time) > silence_threshold:
                break

    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

    print("Recording finished.", file=sys.stderr)

    # Convert to WAV
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))

    return wav_buffer.getvalue()


def transcribe_with_gemini(audio_data: bytes, language: str = None) -> dict:
    """Use Gemini CLI to transcribe audio."""

    # Save audio to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_data)
        tmp_path = tmp.name

    try:
        # Build prompt for Gemini
        lang_hint = f" in {language}" if language else ""
        prompt = f"""Transcribe the following audio file{lang_hint}.
Return ONLY the transcribed text, nothing else.
No explanations, no formatting, just the spoken words.
If there is no speech or it's unclear, respond with: [NO_SPEECH]

Audio file: {tmp_path}"""

        # Note: Gemini CLI may need the file path passed differently
        # For now, we'll use base64 encoding in the prompt
        with open(tmp_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()

        # Alternative prompt with base64
        prompt = f"""I have an audio recording that I need transcribed{lang_hint}.
The audio is base64 encoded WAV format.

Please transcribe the spoken words. Return ONLY the transcript text.
If there is no clear speech, respond with exactly: [NO_SPEECH]

Base64 audio (WAV, 16kHz, mono):
{audio_b64[:100]}...

[Note: This is a speech-to-text request. Please transcribe what you hear in the audio.]"""

        start = time.time()

        # Call Gemini CLI
        result = subprocess.run(
            ["gemini", "-m", "gemini-2.5-pro", prompt],
            capture_output=True,
            text=True,
            timeout=60
        )

        elapsed = time.time() - start

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "auth" in stderr.lower() or "login" in stderr.lower():
                return {
                    "success": False,
                    "error": "auth",
                    "message": "Gemini CLI not authenticated. Run: gemini auth login",
                    "retryable": False
                }
            elif "rate" in stderr.lower() or "limit" in stderr.lower():
                return {
                    "success": False,
                    "error": "limit",
                    "message": "Gemini rate limit reached.",
                    "retryable": False
                }
            else:
                return {
                    "success": False,
                    "error": "cli_error",
                    "message": f"Gemini CLI error: {stderr}",
                    "retryable": False
                }

        transcript = result.stdout.strip()

        # Check for no speech marker
        if transcript == "[NO_SPEECH]" or not transcript:
            return {
                "success": False,
                "error": "no_speech",
                "message": "No clear speech detected in audio."
            }

        return {
            "success": True,
            "transcript": transcript,
            "processing_time": round(elapsed, 2),
            "provider": "gemini"
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "timeout",
            "message": "Gemini request timed out.",
            "retryable": False
        }

    except Exception as e:
        return {
            "success": False,
            "error": "error",
            "message": f"Gemini transcription failed: {str(e)}",
            "retryable": False
        }

    finally:
        try:
            Path(tmp_path).unlink()
        except:
            pass


def main():
    """Main entry point."""

    dep_error = check_dependencies()
    if dep_error:
        print(json.dumps(dep_error))
        return

    language = os.getenv("STT_LANGUAGE") or None
    max_seconds = float(os.getenv("STT_MAX_SECONDS") or "60")
    silence_threshold = float(os.getenv("STT_SILENCE_THRESHOLD") or "2.0")

    try:
        audio_data = record_audio(max_seconds=max_seconds, silence_threshold=silence_threshold)

        if len(audio_data) < 1000:
            result = {
                "success": False,
                "error": "no_speech",
                "message": "No speech detected."
            }
        else:
            result = transcribe_with_gemini(audio_data, language)

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
