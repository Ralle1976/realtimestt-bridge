#!/usr/bin/env node

/**
 * stt-hotkey-start.cjs - Startet den STT Hotkey-Daemon
 *
 * Der Daemon laeuft KOMPLETT UNABHAENGIG von Claude Code.
 * Auch wenn Claude Code busy ist, funktionieren die Steuerungen
 * ueber das private benutzerspezifische Runtime-Verzeichnis.
 */

const { spawn } = require("node:child_process");
const path = require("node:path");
const {
  getRuntimePaths,
  isProcessRunning,
  readPidFile,
  readStdinJson,
  resolvePythonCommand,
  safeReadTextFile,
  validateLanguage,
  validateModelName
} = require("../lib/stt-runtime.cjs");

const SCRIPT_DIR = path.dirname(__dirname);
const DAEMON_SCRIPT = path.join(SCRIPT_DIR, "stt_hotkey_daemon.py");

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
      // Fall through to default
    }
  }
  return { status: "not_running" };
}

function buildControls(paths, pid) {
  const controls = {
    start_recording: paths.startTrigger,
    stop_recording: paths.stopTrigger,
    hotkey: "F9 (falls evdev installiert)",
    stop_daemon: "/stt-hotkey-stop"
  };
  if (process.platform !== "win32" && pid) {
    controls.toggle = `kill -SIGUSR1 ${pid}`;
  }
  return controls;
}

async function main() {
  const paths = getRuntimePaths();
  const payload = await readStdinJson();

  const modelCheck = validateModelName(payload.model, (process.env.STT_MODEL || "distil-de").trim() || "distil-de");
  if (!modelCheck.ok) {
    console.log(JSON.stringify({
      success: false,
      error: "invalid_input",
      message: modelCheck.message
    }, null, 2));
    return;
  }

  const langCheck = validateLanguage(payload.language !== undefined ? payload.language : (process.env.STT_LANGUAGE || "de"));
  if (!langCheck.ok) {
    console.log(JSON.stringify({
      success: false,
      error: "invalid_input",
      message: langCheck.message
    }, null, 2));
    return;
  }

  // Check if already running
  const existingPid = isDaemonRunning(paths.pidFile);
  if (existingPid) {
    const status = getStatus(paths.statusFile);
    console.log(JSON.stringify({
      success: true,
      message: "STT Hotkey Daemon laeuft bereits",
      pid: existingPid,
      status: status.status || "ready",
      runtime_dir: paths.runtimeDir,
      transcript_file: paths.transcriptFile,
      controls: buildControls(paths, existingPid)
    }, null, 2));
    return;
  }

  const pythonCmd = resolvePythonCommand();
  const child = spawn(pythonCmd, [DAEMON_SCRIPT, "start"], {
    stdio: ["ignore", "pipe", "pipe"],
    detached: true,
    env: {
      ...process.env,
      STT_RUNTIME_DIR: paths.runtimeDir,
      STT_MODEL: modelCheck.value,
      STT_LANGUAGE: langCheck.value || "de"
    }
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
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(finish, 3000);
    child.once("close", finish);
    child.once("error", (err) => {
      stderr += err.message;
      finish();
    });
  });

  child.unref();

  // Check if started successfully
  await new Promise((r) => setTimeout(r, 250));
  const pid = isDaemonRunning(paths.pidFile);

  if (pid) {
    console.log(JSON.stringify({
      success: true,
      message: "STT Hotkey Daemon gestartet",
      pid: pid,
      model: modelCheck.value,
      language: langCheck.value || "de",
      runtime_dir: paths.runtimeDir,
      controls: buildControls(paths, pid),
      transcript_file: paths.transcriptFile
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
