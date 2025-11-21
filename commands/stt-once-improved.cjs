#!/usr/bin/env node

/**
 * stt-once-improved.cjs
 *
 * Speech-to-Text command with provider selection:
 * - "cloud": OpenAI Whisper API (fast, ~1-2 sec, requires API key)
 * - "local": RealtimeSTT/Whisper (slow without GPU, offline)
 *
 * Default: "cloud" (recommended for most users)
 */

const { execFile } = require("node:child_process");
const path = require("path");

// Provider scripts
const CLOUD_SCRIPT = "stt_cloud.py";
const LOCAL_SCRIPT = "stt_once.py";

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

function runPythonScript(script, payload) {
  return new Promise((resolve) => {
    const scriptPath = path.join(__dirname, "..", script);

    const child = execFile(
      "python3",
      [scriptPath],
      {
        cwd: path.join(__dirname, ".."),
        maxBuffer: 10 * 1024 * 1024, // 10MB
        timeout: 120000, // 2 minutes max
        env: {
          ...process.env,
          STT_LANGUAGE: payload.language || "",
          STT_MAX_SECONDS: payload.max_seconds != null ? String(payload.max_seconds) : "",
          STT_SILENCE_TIMEOUT: payload.silence_timeout != null ? String(payload.silence_timeout) : "",
          STT_SILENCE_THRESHOLD: payload.silence_threshold != null ? String(payload.silence_threshold) : ""
        }
      },
      (error, stdout, stderr) => {
        if (error) {
          if (error.code === "ENOENT") {
            resolve({
              ok: false,
              type: "missing",
              message: `python3 or ${script} not found. Ensure Python is installed.`
            });
          } else if (error.killed) {
            resolve({
              ok: false,
              type: "timeout",
              message: "Recording timed out after 2 minutes."
            });
          } else {
            resolve({
              ok: false,
              type: "error",
              message: `${script} error:\n${stderr.toString().trim() || error.message}`
            });
          }
        } else {
          try {
            const data = JSON.parse(stdout.toString() || "{}");
            resolve({ ok: true, data });
          } catch (err) {
            resolve({
              ok: false,
              type: "parse_error",
              message: `Failed to parse output from ${script}.\nRaw:\n${stdout.toString().trim()}`
            });
          }
        }
      }
    );

    child.on("error", (err) => {
      if (err.code === "ENOENT") {
        resolve({
          ok: false,
          type: "missing",
          message: `python3 not found. Install Python 3.`
        });
      }
    });
  });
}

async function main() {
  const payload = await readStdinJson();

  // Default to cloud provider (faster)
  const provider = (payload.provider || "cloud").toLowerCase();

  let script;
  if (provider === "local") {
    script = LOCAL_SCRIPT;
  } else if (provider === "cloud" || provider === "openai") {
    script = CLOUD_SCRIPT;
  } else {
    const response = {
      success: false,
      error_type: "invalid_provider",
      message: `Unknown provider "${provider}". Use "cloud" (recommended) or "local".`,
      retryable: false
    };
    process.stdout.write(JSON.stringify(response, null, 2));
    process.exit(1);
  }

  console.error(`Using STT provider: ${provider}`);

  const result = await runPythonScript(script, payload);

  if (!result.ok) {
    const response = {
      success: false,
      error_type: result.type,
      message: result.message,
      provider: provider,
      retryable: false
    };
    process.stdout.write(JSON.stringify(response, null, 2));
    process.exit(1);
  }

  const data = result.data || {};

  if (data.success === false) {
    // Python script returned an error
    const response = {
      success: false,
      error_type: data.error || "error",
      message: data.message || "Unknown error",
      provider: provider,
      retryable: false
    };
    process.stdout.write(JSON.stringify(response, null, 2));
    process.exit(1);
  }

  const response = {
    success: true,
    transcript: data.transcript || "",
    provider: provider,
    processing_time: data.processing_time || null
  };
  process.stdout.write(JSON.stringify(response, null, 2));
}

main().catch((err) => {
  console.error("Unexpected error in stt-once:", err);
  process.exit(1);
});
