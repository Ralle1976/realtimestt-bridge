#!/usr/bin/env node

const { join } = require("node:path");
const { existsSync, unlinkSync } = require("node:fs");
const {
  isProcessRunning,
  isSymlink,
  readPidFile
} = require("../lib/stt-runtime.cjs");

async function main() {
  const pluginRoot = join(__dirname, "..");
  const pidFile = (process.env.STT_ARM_PID_FILE || "").trim() || join(pluginRoot, "stt_daemon.pid");

  if (!existsSync(pidFile)) {
    const resp = {
      success: false,
      message: "No STT daemon pid file found; nothing to disarm."
    };
    process.stdout.write(JSON.stringify(resp, null, 2));
    return;
  }

  if (isSymlink(pidFile)) {
    const resp = {
      success: false,
      error_type: "unsafe_pid_file",
      message: "Refusing to read symlink PID file."
    };
    process.stdout.write(JSON.stringify(resp, null, 2));
    process.exit(1);
  }

  const pid = readPidFile(pidFile);
  let signaled = false;

  if (pid !== null && isProcessRunning(pid)) {
    try {
      process.kill(pid, "SIGTERM");
      signaled = true;
    } catch {
      // Ignore, process may already have exited
    }
  }

  try {
    unlinkSync(pidFile);
  } catch {
    // Ignore
  }

  const resp = {
    success: true,
    message: "RealtimeSTT daemon disarmed.",
    pid: pid,
    signaled: signaled
  };
  process.stdout.write(JSON.stringify(resp, null, 2));
}

main().catch((err) => {
  console.error("Unexpected error in stt-disarm command:", err);
  process.exit(1);
});
