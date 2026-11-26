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

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

from stt_common import (
    MODEL_NAME_PATTERN,
    calculate_rms,
    parse_positive_float_env,
    validate_language,
)

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

    # Check gemini CLI (resolve via PATH for cross-platform Windows .cmd support without shell=True)
    gemini_bin = shutil.which("gemini")
    if not gemini_bin:
        missing.append("gemini-cli (not installed)")
    else:
        try:
            result = subprocess.run(
                [gemini_bin, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
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

    p = pyaudio.PyAudio()
    stream = None
    frames = []

    try:
        # Find the default input device
        try:
            default_device = p.get_default_input_device_info()
            device_index = default_device["index"]
        except IOError:
            device_index = None
            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if dev["maxInputChannels"] > 0:
                    device_index = i
                    break

            if device_index is None:
                raise RuntimeError("No audio input device found")

        audio_format = FORMAT_PYAUDIO if FORMAT_PYAUDIO is not None else pyaudio.paInt16
        stream = p.open(
            format=audio_format,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=CHUNK
        )

        start_time = time.time()
        last_sound_time = start_time
        has_speech = False
        SILENCE_RMS_THRESHOLD = 500

        print("Recording... (speak now)", file=sys.stderr)

        while True:
            elapsed = time.time() - start_time
            if elapsed > max_seconds:
                break

            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)

            rms = calculate_rms(data)

            if rms > SILENCE_RMS_THRESHOLD:
                has_speech = True
                last_sound_time = time.time()

            if has_speech and (time.time() - last_sound_time) > silence_threshold:
                break

    finally:
        if stream is not None:
            try:
                stream.stop_stream()
            finally:
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
    try:
        validated_language = validate_language(language)
    except ValueError as exc:
        return {
            "success": False,
            "error": "invalid_input",
            "message": str(exc),
            "retryable": False
        }

    gemini_model = (os.getenv("STT_GEMINI_MODEL") or "gemini-2.5-pro").strip()
    if not MODEL_NAME_PATTERN.fullmatch(gemini_model):
        return {
            "success": False,
            "error": "invalid_config",
            "message": f"Invalid STT_GEMINI_MODEL value: '{gemini_model}'",
            "retryable": False
        }

    gemini_bin = shutil.which("gemini")
    if not gemini_bin:
        return {
            "success": False,
            "error": "missing_dependencies",
            "message": "gemini-cli not found in PATH.",
            "retryable": False
        }

    # Save audio to private temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_data)
        tmp_path = tmp.name

    try:
        lang_hint = f" in {validated_language}" if validated_language else ""
        prompt = (
            f"Transcribe the following audio file{lang_hint}.\n"
            "Return ONLY the transcribed text, nothing else.\n"
            "No explanations, no formatting, just the spoken words.\n"
            "If there is no speech or it's unclear, respond with: [NO_SPEECH]\n\n"
            f"Audio file: {tmp_path}\n"
        )

        start = time.time()

        # Pass prompt via stdin to prevent CLI flag injection and OS command-line length limits
        result = subprocess.run(
            [gemini_bin, "-m", gemini_model],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass


def main():
    """Main entry point."""

    dep_error = check_dependencies()
    if dep_error:
        print(json.dumps(dep_error))
        return

    try:
        language = validate_language(os.getenv("STT_LANGUAGE"))
        max_seconds = parse_positive_float_env("STT_MAX_SECONDS", 60.0, min_value=0.1, max_value=3600.0)
        silence_threshold = parse_positive_float_env("STT_SILENCE_THRESHOLD", 2.0, min_value=0.05, max_value=300.0)
    except ValueError as exc:
        print(json.dumps({
            "success": False,
            "error": "invalid_config",
            "message": str(exc),
            "retryable": False
        }))
        return

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
