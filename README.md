# RealtimeSTT Bridge Plugin v2.0

Speech-to-Text for Claude Code with multiple provider support.

## Quick Start

```bash
# Install dependencies
pip install faster-whisper pyaudio

# Use in Claude Code
/stt-once {}
```

## Providers

| Provider | Speed | Quality | Offline | Cost |
|----------|-------|---------|---------|------|
| **fast** (default) | ~2-3 sec | Good | Yes | Free |
| local | 10-30+ sec | Good | Yes | Free |
| cloud | ~1-2 sec | Best | No | $0.006/min |

### fast (RECOMMENDED)
Uses `faster-whisper` with CTranslate2 optimization. Works great on CPU-only systems.

```bash
pip install faster-whisper pyaudio
```

### local
Original RealtimeSTT implementation. Slower without GPU.

```bash
pip install RealtimeSTT
```

### cloud
OpenAI Whisper API. Requires API key.

```bash
pip install openai pyaudio
export OPENAI_API_KEY="your-key"
```

## Commands

### `/stt-once` - Single Recording

```json
{
  "language": "de",
  "max_seconds": 60,
  "silence_threshold": 2.0,
  "provider": "fast",
  "model": "tiny"
}
```

All parameters optional. Default: fast provider with tiny model.

**Models for fast provider:**
- `tiny` - Fastest (~2-3 sec for 10 sec audio)
- `base` - Better quality (~4-6 sec)
- `small` - Best quality (~10-15 sec)

**Response:**
```json
{
  "success": true,
  "transcript": "Das ist ein gesprochener Satz.",
  "provider": "faster-whisper",
  "processing_time": 2.3,
  "model": "tiny"
}
```

### `/stt-arm` - Continuous Listening

Starts a background daemon that listens for voice triggers.

```json
{
  "language": "de",
  "trigger_prefix": "claude schreibe"
}
```

**Voice Triggers:**
- Start: "CLAUDE schreibe ..." - activates listening mode
- Stop: "CLAUDE stop" - deactivates listening mode

Events are written to `stt_triggers.jsonl`:

```json
{"type": "start", "command_text": "Text über Quicksort"}
{"type": "text", "raw_text": "weiterer Text"}
{"type": "stop"}
```

### `/stt-disarm` - Stop Continuous Listening

```json
{}
```

## Installation

### Command Registration (Required)

Commands must be in `~/.claude/commands/`:

```bash
# Automatic
cd /home/ralle/claude-code-multimodel/plugins/realtimestt-bridge
./install-stt-commands.sh

# Or manual
ln -sf /home/ralle/claude-code-multimodel/plugins/realtimestt-bridge/commands/stt-once.cjs ~/.claude/commands/stt-once
ln -sf /home/ralle/claude-code-multimodel/plugins/realtimestt-bridge/commands/stt-arm.cjs ~/.claude/commands/stt-arm
ln -sf /home/ralle/claude-code-multimodel/plugins/realtimestt-bridge/commands/stt-disarm.cjs ~/.claude/commands/stt-disarm
```

### Linux/WSL Dependencies

```bash
sudo apt-get update
sudo apt-get install python3-dev portaudio19-dev
```

### WSL Audio Setup

WSLg provides PulseAudio automatically. Verify with:
```bash
pactl list short sources
```

## Error Handling

```json
{
  "success": false,
  "error_type": "no_speech | missing_dependencies | timeout | error",
  "message": "Description",
  "retryable": false
}
```

| Error Type | Meaning | Action |
|------------|---------|--------|
| no_speech | No voice detected | Speak louder, check microphone |
| missing_dependencies | Package not installed | `pip install <package>` |
| timeout | Recording too long | Reduce max_seconds |
| audio_error | Microphone issue | Check audio devices |

## Performance Comparison

On CPU-only system (Intel i5, no GPU):

| Provider/Model | 10 sec Audio |
|----------------|--------------|
| fast/tiny | ~2.5 sec |
| fast/base | ~5 sec |
| fast/small | ~12 sec |
| local (turbo) | ~25 sec |
| cloud | ~1.5 sec |

## Files

```
realtimestt-bridge/
├── commands/
│   ├── stt-once.cjs      # Main command (multi-provider)
│   ├── stt-arm.cjs       # Continuous mode start
│   └── stt-disarm.cjs    # Continuous mode stop
├── stt_fast_local.py     # faster-whisper implementation
├── stt_cloud.py          # OpenAI Whisper API
├── stt_once.py           # Original RealtimeSTT
├── stt_daemon.py         # Continuous mode daemon
└── README.md
```

## Changelog

### v2.0 (2025-11-21)
- Added `fast` provider using faster-whisper (CTranslate2)
- Multi-provider architecture (fast/local/cloud)
- Model selection for fast provider (tiny/base/small)
- Improved silence detection
- Better error handling with retryable flag

### v1.0
- Initial release with RealtimeSTT
