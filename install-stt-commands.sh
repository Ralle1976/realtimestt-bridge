#!/usr/bin/env bash

#
# Install STT Commands for Claude Code
#

set -e

PLUGIN_DIR="/home/ralle/claude-code-multimodel/plugins/realtimestt-bridge"
COMMANDS_DIR="$HOME/.claude/commands"

echo "=== RealtimeSTT Bridge - Install Commands ==="
echo ""

# Create commands directory if needed
mkdir -p "$COMMANDS_DIR"

# Create symlinks
echo "Creating command symlinks..."

ln -sf "$PLUGIN_DIR/commands/stt-once.cjs" "$COMMANDS_DIR/stt-once"
echo "  /stt-once -> stt-once.cjs"

ln -sf "$PLUGIN_DIR/commands/stt-arm.cjs" "$COMMANDS_DIR/stt-arm"
echo "  /stt-arm -> stt-arm.cjs"

ln -sf "$PLUGIN_DIR/commands/stt-disarm.cjs" "$COMMANDS_DIR/stt-disarm"
echo "  /stt-disarm -> stt-disarm.cjs"

echo ""

# Make scripts executable
chmod +x "$PLUGIN_DIR/commands/"*.cjs
chmod +x "$PLUGIN_DIR/"*.py
echo "Made scripts executable."

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Available commands:"
echo "  /stt-once {}           - Single speech recognition"
echo "  /stt-arm {}            - Start continuous listening"
echo "  /stt-disarm {}         - Stop continuous listening"
echo ""
echo "Install dependencies:"
echo "  pip install faster-whisper pyaudio"
echo ""
echo "Restart Claude Code to use the commands."
