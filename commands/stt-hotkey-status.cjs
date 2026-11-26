#!/usr/bin/env node

/**
 * stt-hotkey-status.cjs - Zeigt Status des STT Hotkey-Daemon
 */

const fs = require("node:fs");
const {
  getRuntimePaths,
  isProcessRunning,
  isSymlink,
  readPidFile,
  readStdinJson,
  safeReadTextFile
} = require("../lib/stt-runtime.cjs");

function isDaemonRunning(pidFile) {
  const pid = readPidFile(pidFile);
  if (pid !== null && isProcessRunning(pid)) {
    return pid;
  }
  return null;
}

function getStatus(statusFile) {
  const raw = safeReadTextFile(statusFile);
  if (raw) {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }
  return null;
}

function getLastTranscript(transcriptFile) {
  try {
    if (!fs.existsSync(transcriptFile) || isSymlink(transcriptFile)) {
      return null;
    }
    const stat = fs.statSync(transcriptFile);
    if (!stat.isFile()) return null;
    return {
      text: fs.readFileSync(transcriptFile, "utf8").trim(),
      modified: stat.mtime.toISOString()
    };
  } catch {
    return null;
  }
}

async function main() {
  await readStdinJson();
  const paths = getRuntimePaths();

  const pid = isDaemonRunning(paths.pidFile);
  const status = pid !== null ? getStatus(paths.statusFile) : null;
  const transcript = getLastTranscript(paths.transcriptFile);

  const response = {
    success: true,
    daemon_running: pid !== null,
    pid: pid,
    status: pid !== null ? (status?.status || "ready") : "not_running",
    model: status?.model || process.env.STT_MODEL || "distil-de",
    language: process.env.STT_LANGUAGE || "de",
    runtime_dir: paths.runtimeDir
  };

  if (transcript) {
    response.last_transcript = transcript;
  }

  if (pid) {
    response.controls = {
      start_recording: paths.startTrigger,
      stop_recording: paths.stopTrigger,
      hotkey: "F9"
    };
    if (process.platform !== "win32") {
      response.controls.toggle = `kill -SIGUSR1 ${pid}`;
    }
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
