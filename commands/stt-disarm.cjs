#!/usr/bin/env node

const { join } = require("node:path");
const { readFileSync, existsSync, unlinkSync } = require("node:fs");

async function main() {
  const pluginRoot = join(__dirname, "..");
  const pidFile = join(pluginRoot, "stt_daemon.pid");

  if (!existsSync(pidFile)) {
    const resp = {
      success: false,
      message: "No STT daemon pid file found; nothing to disarm."
    };
    process.stdout.write(JSON.stringify(resp, null, 2));
    return;
  }

  const pidText = readFileSync(pidFile, "utf8").trim();
  const pid = Number(pidText || "0");

  if (pid > 0) {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      // ignore, process may already be dead
    }
  }

  try {
    unlinkSync(pidFile);
  } catch {
    // ignore
  }

  const resp = {
    success: true,
    message: "RealtimeSTT daemon disarmed."
  };
  process.stdout.write(JSON.stringify(resp, null, 2));
}

main().catch((err) => {
  console.error("Unexpected error in stt-disarm command:", err);
  process.exit(1);
});

