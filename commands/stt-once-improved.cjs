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
const path = require("node:path");
const {
  readStdinJson,
  resolvePythonCommand,
  validateLanguage,
  validatePositiveNumber
} = require("../lib/stt-runtime.cjs");

// Provider scripts
const CLOUD_SCRIPT = "stt_cloud.py";
const LOCAL_SCRIPT = "stt_once.py";

function runPythonScript(script, validated) {
  return new Promise((resolve) => {
    const scriptPath = path.join(__dirname, "..", script);
    const pythonCmd = resolvePythonCommand();

    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };

    const child = execFile(
      pythonCmd,
      [scriptPath],
      {
        cwd: path.join(__dirname, ".."),
        maxBuffer: 10 * 1024 * 1024, // 10MB
        timeout: 120000, // 2 minutes max
        env: {
          ...process.env,
          STT_LANGUAGE: validated.language,
          STT_MAX_SECONDS: validated.maxSeconds != null ? String(validated.maxSeconds) : "",
          STT_SILENCE_TIMEOUT: validated.silenceTimeout != null ? String(validated.silenceTimeout) : "",
          STT_SILENCE_THRESHOLD: validated.silenceThreshold != null ? String(validated.silenceThreshold) : ""
        }
      },
      (error, stdout, stderr) => {
        if (error) {
          if (error.code === "ENOENT") {
            finish({
              ok: false,
              type: "missing",
              message: `${pythonCmd} or ${script} not found. Ensure Python is installed.`
            });
          } else if (error.killed) {
            finish({
              ok: false,
              type: "timeout",
              message: "Recording timed out after 2 minutes."
            });
          } else {
            finish({
              ok: false,
              type: "error",
              message: `${script} error:\n${stderr.toString().trim() || error.message}`
            });
          }
        } else {
          try {
            const data = JSON.parse(stdout.toString() || "{}");
            finish({ ok: true, data });
          } catch {
            finish({
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
        finish({
          ok: false,
          type: "missing",
          message: `${pythonCmd} not found. Install Python 3.`
        });
      }
    });
  });
}

function failJson(errorType, message, extra = {}) {
  const response = {
    success: false,
    error_type: errorType,
    message,
    retryable: false,
    ...extra
  };
  process.stdout.write(JSON.stringify(response, null, 2));
  process.exit(1);
}

async function main() {
  const input = await readStdinJson({ strict: true });
  if (!input.ok) {
    failJson(input.error, input.message);
  }
  const payload = input.data;

  // Default to cloud provider (faster)
  const rawProvider = payload.provider === undefined || payload.provider === null ? "cloud" : payload.provider;
  if (typeof rawProvider !== "string") {
    failJson("invalid_provider", "Invalid 'provider': expected a string.");
  }
  const provider = rawProvider.trim().toLowerCase() || "cloud";

  let script;
  if (provider === "local") {
    script = LOCAL_SCRIPT;
  } else if (provider === "cloud" || provider === "openai") {
    script = CLOUD_SCRIPT;
  } else {
    failJson("invalid_provider", `Unknown provider "${provider}". Use "cloud" (recommended) or "local".`);
  }

  const langCheck = validateLanguage(payload.language);
  if (!langCheck.ok) failJson("invalid_input", langCheck.message, { provider });

  const maxSecCheck = validatePositiveNumber(payload.max_seconds, {
    name: "max_seconds",
    min: 0.1,
    max: 3600,
    defaultValue: null
  });
  if (!maxSecCheck.ok) failJson("invalid_input", maxSecCheck.message, { provider });

  const silenceTimeoutCheck = validatePositiveNumber(payload.silence_timeout, {
    name: "silence_timeout",
    min: 0.05,
    max: 600,
    defaultValue: null
  });
  if (!silenceTimeoutCheck.ok) failJson("invalid_input", silenceTimeoutCheck.message, { provider });

  const silenceThreshCheck = validatePositiveNumber(payload.silence_threshold, {
    name: "silence_threshold",
    min: 0.05,
    max: 300,
    defaultValue: null
  });
  if (!silenceThreshCheck.ok) failJson("invalid_input", silenceThreshCheck.message, { provider });

  console.error(`Using STT provider: ${provider}`);

  const result = await runPythonScript(script, {
    language: langCheck.value,
    maxSeconds: maxSecCheck.value,
    silenceTimeout: silenceTimeoutCheck.value,
    silenceThreshold: silenceThreshCheck.value
  });

  if (!result.ok) {
    failJson(result.type, result.message, { provider });
  }

  const data = result.data || {};

  if (data.success === false) {
    failJson(data.error || "error", data.message || "Unknown error", { provider });
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
