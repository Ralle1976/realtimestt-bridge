#!/usr/bin/env node

const { execFile } = require("node:child_process");

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

function runSttOnce(payload) {
  return new Promise((resolve) => {
    const args = ["stt_once.py"];
    const child = execFile(
      "python3",
      args,
      {
        cwd: __dirname + "/..",
        maxBuffer: 1024 * 1024,
        env: {
          ...process.env,
          STT_LANGUAGE: payload.language || "",
          STT_MAX_SECONDS: payload.max_seconds != null ? String(payload.max_seconds) : "",
          STT_SILENCE_TIMEOUT:
            payload.silence_timeout != null ? String(payload.silence_timeout) : ""
        }
      },
      (error, stdout, stderr) => {
        if (error) {
          if (error.code === "ENOENT") {
            resolve({
              ok: false,
              type: "missing",
              message:
                "python3 or stt_once.py not found. Ensure Python and RealtimeSTT bridge script are installed."
            });
          } else {
            resolve({
              ok: false,
              type: "error",
              message:
                "stt_once.py returned an error.\nStderr:\n" +
                stderr.toString().trim()
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
              message:
                "Failed to parse JSON from stt_once.py.\nRaw output:\n" +
                stdout.toString().trim()
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
          message:
            "python3 or stt_once.py not found. Ensure Python and RealtimeSTT bridge script are installed."
        });
      }
    });
  });
}

async function main() {
  const payload = await readStdinJson();

  const result = await runSttOnce(payload);

  if (!result.ok) {
    const response = {
      success: false,
      error_type: result.type,
      message: result.message
    };
    process.stdout.write(JSON.stringify(response, null, 2));
    process.exit(1);
  }

  const data = result.data || {};
  const response = {
    success: Boolean(data.success),
    transcript: data.transcript || "",
    raw: data
  };
  process.stdout.write(JSON.stringify(response, null, 2));
}

main().catch((err) => {
  console.error("Unexpected error in stt-once command:", err);
  process.exit(1);
});

