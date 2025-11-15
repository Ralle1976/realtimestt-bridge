#!/usr/bin/env node

const { execFile } = require("node:child_process");
const { join } = require("node:path");
const { writeFileSync, existsSync } = require("node:fs");

async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch (err) {
    console.error("Failed to parse JSON input:", err.message);
    process.exit(1);
  }
}

async function main() {
  const payload = await readStdinJson();
  const pluginRoot = join(__dirname, "..");
  const pidFile = join(pluginRoot, "stt_daemon.pid");

  if (existsSync(pidFile)) {
    const resp = {
      success: false,
      message: "STT daemon already armed (pid file exists). Use /stt-disarm first if stuck."
    };
    process.stdout.write(JSON.stringify(resp, null, 2));
    return;
  }

  const env = {
    ...process.env,
    STT_LANGUAGE: payload.language || "",
    STT_TRIGGER_PREFIX: (payload.trigger_prefix || "claude schreibe").toLowerCase(),
    STT_STOP_WORD: "claude stop"
  };

  const child = execFile(
    "python3",
    ["stt_daemon.py"],
    {
      cwd: pluginRoot,
      env,
      detached: true,
      stdio: "ignore"
    },
    () => {
      // We don't care about exit here; daemon should detach.
    }
  );

  child.unref();

  writeFileSync(pidFile, String(child.pid), { encoding: "utf8" });

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
