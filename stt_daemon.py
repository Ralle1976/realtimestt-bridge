import json
import os
import signal
import time
from typing import Optional

from stt_common import validate_language


LOG_FILE = "stt_daemon.log"
TRIGGERS_FILE = "stt_triggers.jsonl"


def log(msg: str) -> None:
  ts = time.strftime("%Y-%m-%d %H:%M:%S")
  try:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
      f.write(f"[{ts}] {msg}\n")
  except OSError:
    pass


def _append_trigger_event(event: dict, triggers_file: str = TRIGGERS_FILE) -> None:
  with open(triggers_file, "a", encoding="utf-8") as f:
    f.write(json.dumps(event, ensure_ascii=False) + "\n")


class TriggerProcessor:
  """Stateful voice-trigger processor writing JSONL events."""

  def __init__(
    self,
    trigger_prefix: str = "claude schreibe",
    stop_word: str = "claude stop",
    triggers_file: Optional[str] = None,
  ) -> None:
    self.trigger_prefix = (trigger_prefix or "").strip().lower() or "claude schreibe"
    self.stop_word = (stop_word or "").strip().lower() or "claude stop"
    self.triggers_file = triggers_file
    self.listening = False

  def handle_text(self, text: str) -> Optional[dict]:
    text = (text or "").strip()
    if not text:
      return None

    log(f"Recognized: {text}")
    lower = text.lower()
    target_file = self.triggers_file if self.triggers_file is not None else TRIGGERS_FILE

    # Start listening: "claude schreibe ..."
    if lower.startswith(self.trigger_prefix):
      self.listening = True
      content = text[len(self.trigger_prefix) :].strip()
      event = {
        "type": "start",
        "trigger_prefix": self.trigger_prefix,
        "raw_text": text,
        "command_text": content,
      }
      _append_trigger_event(event, target_file)
      log(f"Start trigger detected, listening=True, command_text='{content}'")
      return event

    # Stop listening: "claude stop"
    if lower.startswith(self.stop_word):
      if self.listening:
        self.listening = False
        event = {
          "type": "stop",
          "stop_word": self.stop_word,
          "raw_text": text,
        }
        _append_trigger_event(event, target_file)
        log("Stop trigger detected, listening=False")
        return event
      return None

    # While listening, record all recognized text segments
    if self.listening:
      event = {
        "type": "text",
        "raw_text": text,
      }
      _append_trigger_event(event, target_file)
      log(f"Listening text: '{text}'")
      return event

    return None


def main() -> None:
  try:
    from RealtimeSTT import AudioToTextRecorder
  except Exception as exc:  # noqa: BLE001
    log(f"Failed to import RealtimeSTT: {exc}")
    return

  try:
    language = validate_language(os.getenv("STT_LANGUAGE"))
  except ValueError as exc:
    log(f"Invalid STT_LANGUAGE: {exc}")
    return

  trigger_prefix = (os.getenv("STT_TRIGGER_PREFIX") or "").strip().lower() or "claude schreibe"
  stop_word = (os.getenv("STT_STOP_WORD") or "").strip().lower() or "claude stop"

  running = True

  def handle_stop_signal(_signum, _frame) -> None:
    nonlocal running
    running = False

  signal.signal(signal.SIGTERM, handle_stop_signal)
  signal.signal(signal.SIGINT, handle_stop_signal)

  recorder = AudioToTextRecorder(language=language) if language else AudioToTextRecorder()
  processor = TriggerProcessor(trigger_prefix=trigger_prefix, stop_word=stop_word)

  log(
    f"STT daemon started with trigger_prefix='{processor.trigger_prefix}', "
    f"stop_word='{processor.stop_word}'"
  )

  try:
    # Simple loop: keep calling recorder.text with callback
    while running:
      try:
        recorder.text(processor.handle_text)
      except KeyboardInterrupt:
        log("STT daemon received KeyboardInterrupt, exiting.")
        break
      except Exception as exc:  # noqa: BLE001
        log(f"Error in recorder loop: {exc}")
        time.sleep(1.0)
  finally:
    if hasattr(recorder, "shutdown"):
      try:
        recorder.shutdown()
      except Exception:
        pass
    log("STT daemon stopped.")


if __name__ == "__main__":
  main()
