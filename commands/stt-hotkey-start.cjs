#!/usr/bin/env node

/**
 * stt-hotkey-start.cjs - Startet den STT Hotkey-Daemon
 *
 * Der Daemon laeuft KOMPLETT UNABHAENGIG von Claude Code.
 * Auch wenn Claude Code busy ist, funktionieren die Steuerungen:
 *
 * Steuerung:
 *   - touch /tmp/stt_start    -> Aufnahme starten
 *   - touch /tmp/stt_stop     -> Aufnahme stoppen
 *   - kill -SIGUSR1 <pid>     -> Toggle
 *   - F9 (Hotkey)             -> Toggle (falls evdev installiert)
 *
 * Transkript wird nach /tmp/stt_transcript.txt geschrieben.
 */

const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("path");

const SCRIPT_DIR = path.dirname(__dirname);
const DAEMON_SCRIPT = path.join(SCRIPT_DIR, "stt_hotkey_daemon.py");
const PID_FILE = "/tmp/stt_daemon.pid";
const STATUS_FILE = "/tmp/stt_status";

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
      process.kill(pid, 0); // Check if process exists
      return pid;
    }
  } catch {
    // Process doesn't exist
  }
  return null;
}

function getStatus() {
  try {
    if (fs.existsSync(STATUS_FILE)) {
      return JSON.parse(fs.readFileSync(STATUS_FILE, "utf8"));
    }
  } catch {}
  return { status: "not_running" };
}

async function main() {
  const payload = await readStdinJson();

  // Check if already running
  const existingPid = isDaemonRunning();
  if (existingPid) {
    const status = getStatus();
    console.log(JSON.stringify({
      success: true,
      message: "STT Hotkey Daemon laeuft bereits",
      pid: existingPid,
      status: status.status || "ready",
      controls: {
        start_recording: "touch /tmp/stt_start",
        stop_recording: "touch /tmp/stt_stop",
        toggle: `kill -SIGUSR1 ${existingPid}`,
        stop_daemon: "/stt-hotkey-stop"
      }
    }, null, 2));
    return;
  }

  // Start daemon
  const child = spawn("python3", [DAEMON_SCRIPT, "start"], {
    stdio: ["ignore", "pipe", "pipe"],
    detached: true
  });

  let stdout = "";
  let stderr = "";

  child.stdout.on("data", (data) => {
    stdout += data.toString();
  });

  child.stderr.on("data", (data) => {
    stderr += data.toString();
  });

  await new Promise((resolve) => {
    child.on("close", resolve);
    child.on("error", resolve);
    // Timeout after 3 seconds
    setTimeout(resolve, 3000);
  });

  child.unref();

  // Check if started successfully
  await new Promise(r => setTimeout(r, 500));
  const pid = isDaemonRunning();

  if (pid) {
    console.log(JSON.stringify({
      success: true,
      message: "STT Hotkey Daemon gestartet",
      pid: pid,
      model: process.env.STT_MODEL || "distil-de",
      language: process.env.STT_LANGUAGE || "de",
      controls: {
        start_recording: "touch /tmp/stt_start",
        stop_recording: "touch /tmp/stt_stop",
        toggle: `kill -SIGUSR1 ${pid}`,
        hotkey: "F9 (falls evdev installiert)",
        stop_daemon: "/stt-hotkey-stop"
      },
      transcript_file: "/tmp/stt_transcript.txt",
      hint: "Transkript kann mit 'cat /tmp/stt_transcript.txt' gelesen werden"
    }, null, 2));
  } else {
    console.log(JSON.stringify({
      success: false,
      error: "daemon_start_failed",
      message: "Daemon konnte nicht gestartet werden",
      stdout: stdout.trim(),
      stderr: stderr.trim()
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
