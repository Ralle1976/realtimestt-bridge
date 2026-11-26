#!/usr/bin/env node

/**
 * stt-hotkey-stop.cjs - Stoppt den STT Hotkey-Daemon
 */

const fs = require("node:fs");
const {
  getRuntimePaths,
  isProcessRunning,
  isSymlink,
  readPidFile,
  readStdinJson
} = require("../lib/stt-runtime.cjs");

function isDaemonRunning(pidFile) {
  const pid = readPidFile(pidFile);
  if (pid !== null && isProcessRunning(pid)) {
    return pid;
  }
  return null;
}

function cleanupPidFile(pidFile) {
  try {
    if (fs.existsSync(pidFile) && !isSymlink(pidFile)) {
      fs.unlinkSync(pidFile);
    }
  } catch {
    // Ignore ENOENT/race
  }
}

async function main() {
  await readStdinJson();
  const paths = getRuntimePaths();

  const pid = isDaemonRunning(paths.pidFile);

  if (!pid) {
    cleanupPidFile(paths.pidFile);
    console.log(JSON.stringify({
      success: true,
      message: "STT Hotkey Daemon laeuft nicht"
    }, null, 2));
    return;
  }

  try {
    // Send SIGTERM to validated positive PID
    try {
      process.kill(pid, "SIGTERM");
    } catch (err) {
      if (err.code !== "ESRCH") {
        throw err;
      }
    }

    // Wait briefly and verify
    await new Promise((r) => setTimeout(r, 300));

    if (isProcessRunning(pid)) {
      try {
        process.kill(pid, "SIGKILL");
      } catch (err) {
        if (err.code !== "ESRCH") {
          throw err;
        }
      }
    }

    cleanupPidFile(paths.pidFile);

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
