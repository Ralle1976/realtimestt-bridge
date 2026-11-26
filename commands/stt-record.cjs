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

const {
  atomicWriteFile,
  getRuntimePaths,
  isProcessRunning,
  readPidFile,
  readStdinJson,
  safeReadTextFile
} = require("../lib/stt-runtime.cjs");

function isDaemonRunning(pidFile) {
  const pid = readPidFile(pidFile);
  if (pid !== null && isProcessRunning(pid)) {
    return pid;
  }
  return null;
}

function getStatus(statusFile) {
  const raw = safeReadTextFile(statusFile);
  if (raw) {
    try {
      return JSON.parse(raw);
    } catch {
      // Ignore corrupt status file
    }
  }
  return { status: "not_running" };
}

function getTranscript(transcriptFile) {
  const raw = safeReadTextFile(transcriptFile);
  return raw !== null ? raw.trim() : null;
}

function getWaitMs() {
  const raw = Number(process.env.STT_RECORD_WAIT_MS);
  if (Number.isFinite(raw) && raw >= 0 && raw <= 30000) {
    return raw;
  }
  return 2000;
}

async function main() {
  const paths = getRuntimePaths();
  const payload = await readStdinJson();
  const rawAction = payload.action === undefined || payload.action === null ? "toggle" : payload.action;
  const action = typeof rawAction === "string" ? rawAction.trim().toLowerCase() : "";

  const pid = isDaemonRunning(paths.pidFile);

  if (!pid) {
    console.log(JSON.stringify({
      success: false,
      error: "daemon_not_running",
      message: "STT Daemon laeuft nicht. Starte mit /stt-hotkey-start"
    }, null, 2));
    return;
  }

  const status = getStatus(paths.statusFile);
  const waitMs = getWaitMs();

  switch (action) {
    case "start":
      if (status.status === "recording") {
        console.log(JSON.stringify({
          success: true,
          message: "Bereits am Aufnehmen",
          status: "recording"
        }, null, 2));
      } else {
        atomicWriteFile(paths.startTrigger, "");
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
        atomicWriteFile(paths.stopTrigger, "");
        if (waitMs > 0) {
          await new Promise((r) => setTimeout(r, waitMs));
        }
        const transcript = getTranscript(paths.transcriptFile);
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
        atomicWriteFile(paths.stopTrigger, "");
        if (waitMs > 0) {
          await new Promise((r) => setTimeout(r, waitMs));
        }
        const transcript = getTranscript(paths.transcriptFile);
        console.log(JSON.stringify({
          success: true,
          message: "Aufnahme gestoppt",
          transcript: transcript,
          status: "ready"
        }, null, 2));
      } else {
        atomicWriteFile(paths.startTrigger, "");
        console.log(JSON.stringify({
          success: true,
          message: "Aufnahme gestartet",
          status: "recording"
        }, null, 2));
      }
      break;

    case "get": {
      const transcript = getTranscript(paths.transcriptFile);
      console.log(JSON.stringify({
        success: true,
        transcript: transcript,
        status: status.status
      }, null, 2));
      break;
    }

    default:
      console.log(JSON.stringify({
        success: false,
        error: "invalid_action",
        message: `Unbekannte Aktion: ${String(rawAction)}. Verfuegbar: start, stop, toggle, get`
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
