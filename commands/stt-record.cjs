#!/usr/bin/env node

/**
 * stt-record.cjs - Startet/Stoppt Aufnahme im Hotkey-Daemon
 *
 * Eingabe (JSON):
 *   { "action": "start" }   - Startet Aufnahme
 *   { "action": "stop" }    - Stoppt Aufnahme
 *   { "action": "toggle" }  - Toggle Start/Stop
 *   { "action": "get" }     - Holt letztes Transkript
 */

const fs = require("node:fs");

const PID_FILE = "/tmp/stt_daemon.pid";
const STATUS_FILE = "/tmp/stt_status";
const TRANSCRIPT_FILE = "/tmp/stt_transcript.txt";
const START_TRIGGER = "/tmp/stt_start";
const STOP_TRIGGER = "/tmp/stt_stop";

async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return {};
  }
}

function isDaemonRunning() {
  try {
    if (fs.existsSync(PID_FILE)) {
      const pid = parseInt(fs.readFileSync(PID_FILE, "utf8").trim());
      process.kill(pid, 0);
      return pid;
    }
  } catch {}
  return null;
}

function getStatus() {
  try {
    if (fs.existsSync(STATUS_FILE)) {
      return JSON.parse(fs.readFileSync(STATUS_FILE, "utf8"));
    }
  } catch {}
  return { status: "not_running" };
}

function getTranscript() {
  try {
    if (fs.existsSync(TRANSCRIPT_FILE)) {
      return fs.readFileSync(TRANSCRIPT_FILE, "utf8").trim();
    }
  } catch {}
  return null;
}

async function main() {
  const payload = await readStdinJson();
  const action = payload.action || "toggle";

  const pid = isDaemonRunning();

  if (!pid) {
    console.log(JSON.stringify({
      success: false,
      error: "daemon_not_running",
      message: "STT Daemon laeuft nicht. Starte mit /stt-hotkey-start"
    }, null, 2));
    return;
  }

  const status = getStatus();

  switch (action) {
    case "start":
      if (status.status === "recording") {
        console.log(JSON.stringify({
          success: true,
          message: "Bereits am Aufnehmen",
          status: "recording"
        }, null, 2));
      } else {
        fs.writeFileSync(START_TRIGGER, "");
        console.log(JSON.stringify({
          success: true,
          message: "Aufnahme gestartet",
          status: "recording",
          hint: "Stoppe mit /stt-record {\"action\": \"stop\"}"
        }, null, 2));
      }
      break;

    case "stop":
      if (status.status !== "recording") {
        console.log(JSON.stringify({
          success: true,
          message: "Keine aktive Aufnahme",
          status: status.status
        }, null, 2));
      } else {
        fs.writeFileSync(STOP_TRIGGER, "");
        // Wait for processing
        await new Promise(r => setTimeout(r, 2000));
        const transcript = getTranscript();
        console.log(JSON.stringify({
          success: true,
          message: "Aufnahme gestoppt",
          transcript: transcript,
          status: "ready"
        }, null, 2));
      }
      break;

    case "toggle":
      if (status.status === "recording") {
        fs.writeFileSync(STOP_TRIGGER, "");
        await new Promise(r => setTimeout(r, 2000));
        const transcript = getTranscript();
        console.log(JSON.stringify({
          success: true,
          message: "Aufnahme gestoppt",
          transcript: transcript,
          status: "ready"
        }, null, 2));
      } else {
        fs.writeFileSync(START_TRIGGER, "");
        console.log(JSON.stringify({
          success: true,
          message: "Aufnahme gestartet",
          status: "recording"
        }, null, 2));
      }
      break;

    case "get":
      const transcript = getTranscript();
      console.log(JSON.stringify({
        success: true,
        transcript: transcript,
        status: status.status
      }, null, 2));
      break;

    default:
      console.log(JSON.stringify({
        success: false,
        error: "invalid_action",
        message: `Unbekannte Aktion: ${action}. Verfuegbar: start, stop, toggle, get`
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
