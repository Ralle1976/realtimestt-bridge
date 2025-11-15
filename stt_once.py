import json
import os
import sys
import time


def main():
  try:
    from RealtimeSTT import AudioToTextRecorder
  except Exception as exc:  # noqa: BLE001
    out = {
      "success": False,
      "error": "import_failed",
      "message": (
        "Failed to import RealtimeSTT. Install it with `pip install RealtimeSTT` "
        "in the same environment where Claude runs this plugin."
      ),
      "details": str(exc),
    }
    print(json.dumps(out))
    return

  language = os.getenv("STT_LANGUAGE") or None
  max_seconds_env = os.getenv("STT_MAX_SECONDS") or ""
  silence_timeout_env = os.getenv("STT_SILENCE_TIMEOUT") or ""

  # Default behaviour:
  # - max_seconds: 120s Gesamtaufnahme (Sicherheit, falls nie Stille erkannt wird)
  # - silence_timeout: 20s Stille nach erster Erkennung
  #   -> Du kannst lange sprechen und auch nachdenken; erst wenn 20 Sekunden
  #      gar nichts mehr gesagt wird, wird gestoppt.
  max_seconds = float(max_seconds_env) if max_seconds_env else 120.0
  silence_timeout = float(silence_timeout_env) if silence_timeout_env else 20.0

  recorder = AudioToTextRecorder(language=language) if language else AudioToTextRecorder()

  transcript_parts = []
  finished = False
  last_text_time = time.time()

  def on_text(text: str) -> None:
    nonlocal finished, last_text_time
    text = text.strip()
    if not text:
      return
    transcript_parts.append(text)
    last_text_time = time.time()
    # Stop after first full utterance; adjust as needed
    finished = True

  start = time.time()

  # Wait for at least one text callback, but respect max_seconds and silence_timeout
  while True:
    if finished:
      break
    now = time.time()
    if now - start > max_seconds:
      break
    if transcript_parts and (now - last_text_time) > silence_timeout:
      break
    # Give the recorder a chance to process
    try:
      recorder.text(on_text, timeout=0.1)
    except Exception:
      # Swallow occasional timing issues; loop will exit by timeouts
      pass

  full_transcript = " ".join(transcript_parts).strip()
  if not full_transcript:
    out = {
      "success": False,
      "error": "no_speech",
      "message": "No speech detected within the configured time window.",
    }
  else:
    out = {
      "success": True,
      "transcript": full_transcript,
    }

  print(json.dumps(out))


if __name__ == "__main__":
  if sys.platform.startswith("win"):
    # multiprocessing safety; even though we do not spawn here,
    # follow RealtimeSTT guidance
    if __name__ == "__main__":
      main()
  else:
    main()
