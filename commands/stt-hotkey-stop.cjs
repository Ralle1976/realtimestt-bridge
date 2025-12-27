#!/usr/bin/env node

/**
 * stt-hotkey-stop.cjs - Stoppt den STT Hotkey-Daemon
 */

const { execSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("path");

const SCRIPT_DIR = path.dirname(__dirname);
const DAEMON_SCRIPT = path.join(SCRIPT_DIR, "stt_hotkey_daemon.py");
const PID_FILE = "/tmp/stt_daemon.pid";

async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return {};
  }
}

function isDaemonRunning() {
  try {
    if (fs.existsSync(PID_FILE)) {
      const pid = parseInt(fs.readFileSync(PID_FILE, "utf8").trim());
      process.kill(pid, 0);
      return pid;
    }
  } catch {}
  return null;
}

async function main() {
  await readStdinJson();

  const pid = isDaemonRunning();

  if (!pid) {
    console.log(JSON.stringify({
      success: true,
      message: "STT Hotkey Daemon laeuft nicht"
    }, null, 2));
    return;
  }

  try {
    // Send SIGTERM
    process.kill(pid, "SIGTERM");

    // Wait a bit and verify
    await new Promise(r => setTimeout(r, 500));

    const stillRunning = isDaemonRunning();
    if (stillRunning) {
      // Force kill
      process.kill(pid, "SIGKILL");
    }

    // Clean up PID file if still exists
    if (fs.existsSync(PID_FILE)) {
      fs.unlinkSync(PID_FILE);
    }

    console.log(JSON.stringify({
      success: true,
      message: `STT Hotkey Daemon gestoppt (PID: ${pid})`
    }, null, 2));

  } catch (err) {
    console.log(JSON.stringify({
      success: false,
      error: "stop_failed",
      message: `Fehler beim Stoppen: ${err.message}`,
      pid: pid
    }, null, 2));
  }
}

main().catch((err) => {
  console.log(JSON.stringify({
    success: false,
    error: "unexpected_error",
    message: err.message
  }, null, 2));
});
