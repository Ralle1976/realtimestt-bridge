#!/usr/bin/env python3
"""
Fast Local Speech-to-Text using faster-whisper with tiny/base model

Uses faster-whisper with CTranslate2 optimization for CPU performance.
Much faster than standard Whisper on CPU-only systems.

Model comparison (on CPU):
- tiny:  ~2-3 seconds processing for 10 sec audio (RECOMMENDED)
- base:  ~4-6 seconds processing
- small: ~10-15 seconds processing
- turbo: ~20-40 seconds processing (too slow without GPU)

Requirements:
- pip install faster-whisper

Usage:
  python3 stt_fast_local.py

Environment Variables:
  STT_LANGUAGE - Language code (e.g., "de", "en"), default: auto-detect
  STT_MAX_SECONDS - Maximum recording time in seconds, default: 60
  STT_SILENCE_THRESHOLD - Silence duration to stop recording, default: 2.0
  STT_MODEL - Whisper model: "tiny", "base", "small", default: "tiny"
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
FORMAT_PYAUDIO = None
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

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        missing.append("faster-whisper")

    if missing:
        install_cmd = f"pip install {' '.join(missing)}"
        return {
            "success": False,
            "error": "missing_dependencies",
            "message": f"Missing packages: {', '.join(missing)}. Install with: {install_cmd}",
            "retryable": False
        }

    return None


def record_audio(max_seconds: float = 60.0, silence_threshold: float = 2.0) -> bytes:
    """Record audio from microphone until silence is detected."""
    import pyaudio
    import struct
    import math

    p = pyaudio.PyAudio()

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

    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))

    return wav_buffer.getvalue()


# Global model cache to avoid reloading
_model_cache = {}


def get_model(model_size: str):
    """Get or create cached Whisper model."""
    global _model_cache

    if model_size not in _model_cache:
        from faster_whisper import WhisperModel

        print(f"Loading whisper model: {model_size}...", file=sys.stderr)
        start = time.time()

        # Use INT8 quantization for faster CPU inference
        _model_cache[model_size] = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8"
        )

        elapsed = time.time() - start
        print(f"Model loaded in {elapsed:.1f}s", file=sys.stderr)

    return _model_cache[model_size]


def transcribe_local(audio_data: bytes, language: str = None, model_size: str = "tiny") -> dict:
    """Transcribe audio using faster-whisper."""

    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_data)
        tmp_path = tmp.name

    try:
        model = get_model(model_size)

        start = time.time()

        # Transcribe
        kwargs = {
            "beam_size": 1,  # Faster, slightly less accurate
            "best_of": 1,
            "vad_filter": True,  # Filter out non-speech
        }

        if language:
            kwargs["language"] = language

        segments, info = model.transcribe(tmp_path, **kwargs)

        # Collect all segments
        transcript_parts = []
        for segment in segments:
            transcript_parts.append(segment.text.strip())

        elapsed = time.time() - start

        transcript = " ".join(transcript_parts).strip()

        if not transcript:
            return {
                "success": False,
                "error": "no_speech",
                "message": "No speech detected in audio."
            }

        return {
            "success": True,
            "transcript": transcript,
            "processing_time": round(elapsed, 2),
            "model": model_size,
            "detected_language": info.language if hasattr(info, 'language') else None,
            "provider": "faster-whisper"
        }

    except Exception as e:
        return {
            "success": False,
            "error": "transcription_error",
            "message": f"Transcription failed: {str(e)}"
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
    model_size = os.getenv("STT_MODEL") or "tiny"

    # Validate model
    valid_models = ["tiny", "base", "small"]
    if model_size not in valid_models:
        print(json.dumps({
            "success": False,
            "error": "invalid_model",
            "message": f"Invalid model '{model_size}'. Use: {', '.join(valid_models)}"
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
            result = transcribe_local(audio_data, language, model_size)

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
