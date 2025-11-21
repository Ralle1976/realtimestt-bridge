#!/usr/bin/env bash

#
# Upgrade Script: Enable Cloud-based STT (Fast Mode)
#
# This script upgrades the stt-once command to use the improved version
# with cloud provider support (OpenAI Whisper API).
#

set -e

PLUGIN_DIR="/home/ralle/claude-code-multimodel/plugins/realtimestt-bridge"
COMMANDS_DIR="$HOME/.claude/commands"

echo "=== RealtimeSTT Bridge - Cloud STT Upgrade ==="
echo ""

# Check if plugin directory exists
if [ ! -d "$PLUGIN_DIR" ]; then
  echo "Error: Plugin directory not found: $PLUGIN_DIR"
  exit 1
fi

# Check if improved version exists
if [ ! -f "$PLUGIN_DIR/commands/stt-once-improved.cjs" ]; then
  echo "Error: stt-once-improved.cjs not found"
  exit 1
fi

if [ ! -f "$PLUGIN_DIR/stt_cloud.py" ]; then
  echo "Error: stt_cloud.py not found"
  exit 1
fi

echo "Found improved STT scripts"
echo ""

# Create backup
BACKUP_DIR="$PLUGIN_DIR/commands/backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f "$PLUGIN_DIR/commands/stt-once.cjs" ]; then
  cp "$PLUGIN_DIR/commands/stt-once.cjs" "$BACKUP_DIR/stt-once.cjs"
  echo "Backed up original stt-once.cjs"
fi

# Replace with improved version
cp "$PLUGIN_DIR/commands/stt-once-improved.cjs" "$PLUGIN_DIR/commands/stt-once.cjs"
chmod +x "$PLUGIN_DIR/commands/stt-once.cjs"
echo "Upgraded stt-once.cjs to cloud-enabled version"

# Make cloud script executable
chmod +x "$PLUGIN_DIR/stt_cloud.py"
echo "Made stt_cloud.py executable"

# Update symlink
if [ -L "$COMMANDS_DIR/stt-once" ]; then
  rm "$COMMANDS_DIR/stt-once"
fi
ln -sf "$PLUGIN_DIR/commands/stt-once.cjs" "$COMMANDS_DIR/stt-once"
echo "Updated symlink in ~/.claude/commands/"

echo ""
echo "=== Upgrade Complete ==="
echo ""
echo "New Features:"
echo "  - Cloud STT via OpenAI Whisper API (1-2 sec response)"
echo "  - Local fallback still available (provider: 'local')"
echo "  - Auto-silence detection"
echo ""
echo "Usage:"
echo "  /stt-once {}                        # Cloud mode (default, fast)"
echo "  /stt-once {\"provider\": \"local\"}     # Local mode (slow, offline)"
echo "  /stt-once {\"language\": \"de\"}        # German language"
echo ""
echo "Requirements for Cloud Mode:"
echo "  1. OPENAI_API_KEY environment variable set"
echo "  2. pip install openai pyaudio"
echo ""
echo "Backup Location: $BACKUP_DIR"
echo ""
