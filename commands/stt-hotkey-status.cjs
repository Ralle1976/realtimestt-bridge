#!/usr/bin/env node

/**
 * stt-hotkey-status.cjs - Zeigt Status des STT Hotkey-Daemon
 */

const fs = require("node:fs");

const PID_FILE = "/tmp/stt_daemon.pid";
const STATUS_FILE = "/tmp/stt_status";
const TRANSCRIPT_FILE = "/tmp/stt_transcript.txt";

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

function getStatus() {
  try {
    if (fs.existsSync(STATUS_FILE)) {
      return JSON.parse(fs.readFileSync(STATUS_FILE, "utf8"));
    }
  } catch {}
  return null;
}

function getLastTranscript() {
  try {
    if (fs.existsSync(TRANSCRIPT_FILE)) {
      const stat = fs.statSync(TRANSCRIPT_FILE);
      return {
        text: fs.readFileSync(TRANSCRIPT_FILE, "utf8").trim(),
        modified: stat.mtime.toISOString()
      };
    }
  } catch {}
  return null;
}

async function main() {
  await readStdinJson();

  const pid = isDaemonRunning();
  const status = getStatus();
  const transcript = getLastTranscript();

  const response = {
    success: true,
    daemon_running: pid !== null,
    pid: pid,
    status: status?.status || "not_running",
    model: status?.model || process.env.STT_MODEL || "distil-de",
    language: process.env.STT_LANGUAGE || "de"
  };

  if (transcript) {
    response.last_transcript = transcript;
  }

  if (pid) {
    response.controls = {
      start_recording: "touch /tmp/stt_start",
      stop_recording: "touch /tmp/stt_stop",
      toggle: `kill -SIGUSR1 ${pid}`,
      hotkey: "F9"
    };
  } else {
    response.hint = "Starte Daemon mit /stt-hotkey-start";
  }

  console.log(JSON.stringify(response, null, 2));
}

main().catch((err) => {
  console.log(JSON.stringify({
    success: false,
    error: "unexpected_error",
    message: err.message
  }, null, 2));
});
