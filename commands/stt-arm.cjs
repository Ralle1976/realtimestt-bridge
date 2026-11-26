#!/usr/bin/env node

const { spawn } = require("node:child_process");
const { join } = require("node:path");
const { existsSync, unlinkSync } = require("node:fs");
const {
  atomicWriteFile,
  isProcessRunning,
  isSymlink,
  readPidFile,
  readStdinJson,
  resolvePythonCommand,
  validateLanguage
} = require("../lib/stt-runtime.cjs");

async function main() {
  const input = await readStdinJson({ strict: true });
  if (!input.ok) {
    process.stdout.write(JSON.stringify({
      success: false,
      error_type: input.error,
      message: input.message
    }, null, 2));
    process.exit(1);
  }
  const payload = input.data;

  const langCheck = validateLanguage(payload.language);
  if (!langCheck.ok) {
    process.stdout.write(JSON.stringify({
      success: false,
      error_type: "invalid_input",
      message: langCheck.message
    }, null, 2));
    process.exit(1);
  }

  let triggerPrefix = "claude schreibe";
  if (payload.trigger_prefix !== undefined && payload.trigger_prefix !== null) {
    if (typeof payload.trigger_prefix !== "string" || !payload.trigger_prefix.trim()) {
      process.stdout.write(JSON.stringify({
        success: false,
        error_type: "invalid_input",
        message: "Invalid 'trigger_prefix': expected a non-empty string."
      }, null, 2));
      process.exit(1);
    }
    triggerPrefix = payload.trigger_prefix.trim().toLowerCase();
  }

  const pluginRoot = join(__dirname, "..");
  const pidFile = (process.env.STT_ARM_PID_FILE || "").trim() || join(pluginRoot, "stt_daemon.pid");

  if (existsSync(pidFile)) {
    const existingPid = readPidFile(pidFile);
    if (existingPid !== null && isProcessRunning(existingPid)) {
      const resp = {
        success: false,
        message: "STT daemon already armed (pid file exists). Use /stt-disarm first if stuck.",
        pid: existingPid
      };
      process.stdout.write(JSON.stringify(resp, null, 2));
      return;
    }
    // Remove stale/corrupt non-symlink PID file
    if (!isSymlink(pidFile)) {
      try {
        unlinkSync(pidFile);
      } catch {
        // Ignore race
      }
    }
  }

  const env = {
    ...process.env,
    STT_LANGUAGE: langCheck.value,
    STT_TRIGGER_PREFIX: triggerPrefix,
    STT_STOP_WORD: "claude stop"
  };

  const pythonCmd = resolvePythonCommand();
  const child = spawn(
    pythonCmd,
    ["stt_daemon.py"],
    {
      cwd: pluginRoot,
      env,
      detached: true,
      stdio: "ignore"
    }
  );

  const spawned = await new Promise((resolve) => {
    child.once("spawn", () => resolve({ ok: true }));
    child.once("error", (err) => resolve({ ok: false, error: err }));
  });

  if (!spawned.ok || !Number.isSafeInteger(child.pid) || child.pid <= 0) {
    const resp = {
      success: false,
      error_type: "spawn_failed",
      message: `Failed to start STT daemon with '${pythonCmd}': ${spawned.error ? spawned.error.message : "unknown error"}`
    };
    process.stdout.write(JSON.stringify(resp, null, 2));
    process.exit(1);
  }

  child.unref();
  atomicWriteFile(pidFile, String(child.pid));

  const resp = {
    success: true,
    message: "RealtimeSTT daemon armed.",
    pid: child.pid,
    trigger_prefix: env.STT_TRIGGER_PREFIX
  };
  process.stdout.write(JSON.stringify(resp, null, 2));
}

main().catch((err) => {
  console.error("Unexpected error in stt-arm command:", err);
  process.exit(1);
});
