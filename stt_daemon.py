import json
import os
import sys
import time
from typing import List


LOG_FILE = "stt_daemon.log"


def log(msg: str) -> None:
  ts = time.strftime("%Y-%m-%d %H:%M:%S")
  with open(LOG_FILE, "a", encoding="utf-8") as f:
    f.write(f"[{ts}] {msg}\n")


def main() -> None:
  try:
    from RealtimeSTT import AudioToTextRecorder
  except Exception as exc:  # noqa: BLE001
    log(f"Failed to import RealtimeSTT: {exc}")
    return

  language = os.getenv("STT_LANGUAGE") or None
  trigger_prefix = (os.getenv("STT_TRIGGER_PREFIX") or "claude schreibe").lower()
  stop_word = (os.getenv("STT_STOP_WORD") or "claude stop").lower()

  recorder = AudioToTextRecorder(language=language) if language else AudioToTextRecorder()

  log(
    f"STT daemon started with trigger_prefix='{trigger_prefix}', "
    f"stop_word='{stop_word}'"
  )

  buffer: List[str] = []
  listening = False

  def on_text(text: str) -> None:
    nonlocal buffer
    text = text.strip()
    if not text:
      return
    log(f"Recognized: {text}")
    lower = text.lower()
    nonlocal listening

    # Start listening: "claude schreibe ..."
    if lower.startswith(trigger_prefix):
      listening = True
      content = text[len(trigger_prefix) :].strip()
      event = {
        "type": "start",
        "trigger_prefix": trigger_prefix,
        "raw_text": text,
        "command_text": content,
      }
      with open("stt_triggers.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
      log(f"Start trigger detected, listening=True, command_text='{content}'")
      return

    # Stop listening: "claude stop"
    if lower.startswith(stop_word):
      if listening:
        listening = False
        event = {
          "type": "stop",
          "stop_word": stop_word,
          "raw_text": text,
        }
        with open("stt_triggers.jsonl", "a", encoding="utf-8") as f:
          f.write(json.dumps(event, ensure_ascii=False) + "\n")
        log("Stop trigger detected, listening=False")
      return

    # While listening, record all recognized text segments
    if listening:
      buffer.append(text)
      event = {
        "type": "text",
        "raw_text": text,
      }
      with open("stt_triggers.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
      log(f"Listening text: '{text}'")

  # Simple loop: keep calling recorder.text with callback
  while True:
    try:
      recorder.text(on_text)
    except KeyboardInterrupt:
      log("STT daemon received KeyboardInterrupt, exiting.")
      break
    except Exception as exc:  # noqa: BLE001
      log(f"Error in recorder loop: {exc}")
      time.sleep(1.0)


if __name__ == "__main__":
  if sys.platform.startswith("win"):
    if __name__ == "__main__":
      main()
  else:
    main()
