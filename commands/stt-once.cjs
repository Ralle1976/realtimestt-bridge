#!/usr/bin/env node

/**
 * stt-once.cjs - Speech-to-Text for Claude Code
 *
 * Providers:
 * - "fast" (default): faster-whisper with tiny model (~2-3 sec, offline, free)
 * - "local": RealtimeSTT/Whisper (slow, offline)
 * - "cloud": OpenAI Whisper API (requires OPENAI_API_KEY, ~1-2 sec)
 *
 * Recommended: "fast" for CPU-only systems without API keys
 */

const { execFile } = require("node:child_process");
const path = require("node:path");
const {
  hasOwn,
  readStdinJson,
  resolvePythonCommand,
  validateLanguage,
  validateModelName,
  validatePositiveNumber
} = require("../lib/stt-runtime.cjs");

// Provider script mapping
const PROVIDER_SCRIPTS = {
  fast: "stt_fast_local.py",
  local: "stt_once.py",
  cloud: "stt_cloud.py"
};

function runPythonScript(script, validated) {
  return new Promise((resolve) => {
    const scriptPath = path.join(__dirname, "..", script);
    const pythonCmd = resolvePythonCommand();

    // Build environment
    const env = {
      ...process.env,
      STT_LANGUAGE: validated.language,
      STT_MAX_SECONDS: String(validated.maxSeconds),
      STT_SILENCE_THRESHOLD: String(validated.silenceThreshold),
      STT_MODEL: validated.model
    };

    // For RealtimeSTT compatibility
    if (validated.silenceTimeout !== null) {
      env.STT_SILENCE_TIMEOUT = String(validated.silenceTimeout);
    }

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
        maxBuffer: 10 * 1024 * 1024,
        timeout: 180000, // 3 minutes max
        env: env
      },
      (error, stdout, stderr) => {
        if (error) {
          if (error.code === "ENOENT") {
            finish({
              ok: false,
              type: "missing",
              message: `${pythonCmd} or ${script} not found.`
            });
          } else if (error.killed) {
            finish({
              ok: false,
              type: "timeout",
              message: "Recording/transcription timed out."
            });
          } else {
            finish({
              ok: false,
              type: "error",
              message: stderr.toString().trim() || error.message
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
              message: `Parse error: ${stdout.toString().trim()}`
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
          message: `${pythonCmd} not found.`
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

  // Validate provider
  const rawProvider = payload.provider === undefined || payload.provider === null ? "fast" : payload.provider;
  if (typeof rawProvider !== "string") {
    failJson("invalid_provider", "Invalid 'provider': expected a string.");
  }
  let provider = rawProvider.trim().toLowerCase() || "fast";

  // Aliases
  if (provider === "openai" || provider === "whisper-api") {
    provider = "cloud";
  }
  if (provider === "offline" || provider === "faster-whisper") {
    provider = "fast";
  }
  if (provider === "realtimestt") {
    provider = "local";
  }

  if (!hasOwn(PROVIDER_SCRIPTS, provider)) {
    failJson(
      "invalid_provider",
      `Unknown provider "${provider}". Available: fast (recommended), local, cloud`
    );
  }
  const script = PROVIDER_SCRIPTS[provider];

  // Validate numeric & string inputs
  const langCheck = validateLanguage(payload.language);
  if (!langCheck.ok) failJson("invalid_input", langCheck.message, { provider });

  const maxSecCheck = validatePositiveNumber(payload.max_seconds, {
    name: "max_seconds",
    min: 0.1,
    max: 3600,
    defaultValue: 60
  });
  if (!maxSecCheck.ok) failJson("invalid_input", maxSecCheck.message, { provider });

  const silenceThreshCheck = validatePositiveNumber(payload.silence_threshold, {
    name: "silence_threshold",
    min: 0.05,
    max: 300,
    defaultValue: 2.0
  });
  if (!silenceThreshCheck.ok) failJson("invalid_input", silenceThreshCheck.message, { provider });

  const silenceTimeoutCheck = validatePositiveNumber(payload.silence_timeout, {
    name: "silence_timeout",
    min: 0.05,
    max: 600,
    defaultValue: null
  });
  if (!silenceTimeoutCheck.ok) failJson("invalid_input", silenceTimeoutCheck.message, { provider });

  const modelCheck = validateModelName(payload.model, "tiny");
  if (!modelCheck.ok) failJson("invalid_input", modelCheck.message, { provider });

  console.error(`STT Provider: ${provider} (${script})`);

  const result = await runPythonScript(script, {
    language: langCheck.value,
    maxSeconds: maxSecCheck.value,
    silenceThreshold: silenceThreshCheck.value,
    silenceTimeout: silenceTimeoutCheck.value,
    model: modelCheck.value
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
    provider: data.provider || provider,
    processing_time: data.processing_time || null,
    model: data.model || null
  };
  process.stdout.write(JSON.stringify(response, null, 2));
}

main().catch((err) => {
  console.error("Unexpected error:", err);
  process.exit(1);
});
