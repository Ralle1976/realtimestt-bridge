#!/usr/bin/env node

/**
 * stt.cjs - Main STT Command Entry Point
 *
 * Zeigt das STT-Modell-Menü an und ermöglicht interaktive Auswahl.
 * Ruft intern stt-models.cjs auf.
 */

const { spawn } = require("node:child_process");
const path = require("path");

// Forward to stt-models with list action
const sttModels = spawn("node", [
  path.join(__dirname, "stt-models.cjs")
], {
  stdio: ["pipe", "inherit", "inherit"]
});

// Send empty JSON to trigger list action (default)
sttModels.stdin.write("{}");
sttModels.stdin.end();

sttModels.on("error", (err) => {
  console.error("Fehler beim Starten von stt-models:", err.message);
  process.exit(1);
});

sttModels.on("close", (code) => {
  process.exit(code || 0);
});
