# RealtimeSTT Bridge Plugin

This Claude Code plugin lets Claude trigger a one-shot speech-to-text capture using [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT).

- Plugin path: `/home/ralle/claude-code-multimodel/plugins/realtimestt-bridge`
- Command: `/stt-once`

## Requirements

- Python 3 installed
- `RealtimeSTT` installed in the same environment that runs Claude:

```bash
pip install RealtimeSTT
```

On Linux you may also need:

```bash
sudo apt-get update
sudo apt-get install python3-dev portaudio19-dev
```

## Command: `/stt-once`

One-shot microphone capture:

- Listens briefly to the microphone using `RealtimeSTT.AudioToTextRecorder`.
- Stops after:
  - the first detected utterance, or
  - `max_seconds` (timeout), or
  - `silence_timeout` seconds of silence.
- Returns the recognized text to Claude as JSON.

### Input JSON

- `language` (string, optional): language hint (e.g. `"de"`, `"en"`).
- `max_seconds` (number, optional): hard timeout in seconds (default: 10).
- `silence_timeout` (number, optional): stop after this many seconds of silence once speech started (default: 2).

### Example usage in Claude

```text
/stt-once {
  "language": "de",
  "max_seconds": 8,
  "silence_timeout": 2
}
```

Example response:

```json
{
  "success": true,
  "transcript": "Das ist ein kurzer gesprochener Satz.",
  "raw": {
    "success": true,
    "transcript": "Das ist ein kurzer gesprochener Satz."
  }
}
```

On failure (e.g. no speech detected or missing library) you get:

```json
{
  "success": false,
  "error_type": "error | missing | parse_error",
  "message": "Human-readable explanation"
}
```

## Notes on Hotkey Integration (future)

This plugin focuses on providing a clean `/stt-once` tool for Claude.

For a push-to-talk workflow, you can add a separate system-level hotkey tool (e.g. AutoHotkey on Windows or a small Python script on Linux) that:

- starts `python3 stt_once.py`,
- reads the JSON output,
- pastes or types the transcript into the active window (e.g. Claude terminal).

This keeps the Claude plugin simple and focused, while allowing flexible frontends for voice input.

## Continuous mode: `/stt-arm` and `/stt-disarm`

For a more assistant-like experience, the plugin also provides a simple continuous listener:

- `/stt-arm` – starts a background daemon using `stt_daemon.py`.
- `/stt-disarm` – stops the daemon again.

The daemon:

- runs RealtimeSTT continuously,
- listens for:
  - a start trigger prefix (default: `"claude schreibe"`)
  - a stop word (default: `"claude stop"`)
- whenever recognized text starts with the start trigger, it switches into "listening" mode,
  records subsequent text segments, and writes events to `stt_triggers.jsonl` in the plugin folder, e.g.:

```json
{
  "type": "start",
  "trigger_prefix": "claude schreibe",
  "raw_text": "CLAUDE schreibe Text über Quicksort",
  "command_text": "Text über Quicksort"
}
```

You (or additional tooling) can tail this file to react to spoken commands.

### Example usage

```text
/stt-arm {
  "language": "de",
  "trigger_prefix": "claude schreibe"
}
```

The daemon starts in the background. When you say:

> „CLAUDE schreibe Text über Quicksort“

an entry will be appended to `stt_triggers.jsonl` with `"type": "start"` and `"command_text": "Text über Quicksort"`.

While you keep speaking (and until you say `"CLAUDE stop"`), additional `"type": "text"` events will be appended containing your spoken segments. Saying `"CLAUDE stop"` writes a `"type": "stop"` event and returns the daemon to idle listening mode.

To stop the daemon:

```text
/stt-disarm {}
```

This basic continuous mode does not yet inject prompts directly into Claude chats, but it gives you a structured event stream you can connect to Claude via your preferred automation (e.g. a small script that reads `stt_triggers.jsonl` and sends prompts to Claude).
