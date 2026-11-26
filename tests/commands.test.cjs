"use strict";

/**
 * 100% offline mocked test suite for lib/stt-runtime.cjs and commands/*.cjs
 * Run with: node --test tests/commands.test.cjs
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const runtime = require("../lib/stt-runtime.cjs");

const REPO_ROOT = path.resolve(__dirname, "..");
const COMMANDS_DIR = path.join(REPO_ROOT, "commands");

function makeTempDir(prefix = "stt-test-") {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function runCommand(scriptName, { stdin = "{}", env = {} } = {}) {
  const scriptPath = path.join(COMMANDS_DIR, scriptName);
  return spawnSync(process.execPath, [scriptPath], {
    input: stdin,
    encoding: "utf8",
    env: {
      ...process.env,
      ...env
    },
    timeout: 15000
  });
}

test("lib/stt-runtime.cjs: parsePid & isProcessRunning reject unsafe PIDs", () => {
  assert.equal(runtime.parsePid("1234"), 1234);
  assert.equal(runtime.parsePid(" 42\n"), 42);

  for (const bad of ["", "0", "-1", "-42", "1.5", "NaN", "Infinity", "12abc", "999999999999"]) {
    assert.equal(runtime.parsePid(bad), null, `expected null for ${bad}`);
  }

  assert.equal(runtime.isProcessRunning(process.pid), true);
  assert.equal(runtime.isProcessRunning(0), false);
  assert.equal(runtime.isProcessRunning(-1), false);
  assert.equal(runtime.isProcessRunning(NaN), false);
  assert.equal(runtime.isProcessRunning(99999999), false);
});

test("lib/stt-runtime.cjs: path containment, validators, and atomic UTF-8 write", (t) => {
  const tmpDir = makeTempDir();
  t.after(() => fs.rmSync(tmpDir, { recursive: true, force: true }));

  const child = path.join(tmpDir, "models--tiny");
  assert.equal(runtime.isPathWithin(child, tmpDir), true);
  assert.equal(runtime.isPathWithin(tmpDir, tmpDir), false);
  assert.equal(runtime.isPathWithin(path.join(tmpDir, "..", "escape"), tmpDir), false);

  assert.equal(runtime.validateLanguage("de-DE").ok, true);
  assert.equal(runtime.validateLanguage("en; rm -rf /").ok, false);
  assert.equal(runtime.validateLanguage(123).ok, false);

  assert.equal(runtime.validatePositiveNumber(10, { name: "x", min: 1, max: 60 }).ok, true);
  assert.equal(runtime.validatePositiveNumber(-1, { name: "x", min: 1, max: 60 }).ok, false);
  assert.equal(runtime.validatePositiveNumber(NaN, { name: "x", min: 1, max: 60 }).ok, false);
  assert.equal(runtime.validatePositiveNumber(true, { name: "x", min: 1, max: 60 }).ok, false);

  assert.equal(runtime.validateModelName("distil-de").ok, true);
  assert.equal(runtime.validateModelName("../evil").ok, false);

  const outFile = path.join(tmpDir, "utf8.txt");
  runtime.atomicWriteFile(outFile, "Umlaute: äöü ÄÖÜ ß");
  assert.equal(fs.readFileSync(outFile, "utf8"), "Umlaute: äöü ÄÖÜ ß");
});

test("commands/stt-once.cjs: blocks invalid inputs, prototype pollution, and missing python", () => {
  // Invalid JSON
  const badJson = runCommand("stt-once.cjs", { stdin: "{not json" });
  assert.equal(badJson.status, 1);
  assert.equal(JSON.parse(badJson.stdout).error_type, "invalid_json");

  // Non-object JSON
  const arrJson = runCommand("stt-once.cjs", { stdin: "[]" });
  assert.equal(arrJson.status, 1);
  assert.equal(JSON.parse(arrJson.stdout).error_type, "invalid_json");

  // Prototype pollution attempts
  for (const proto of ["constructor", "toString", "__proto__"]) {
    const res = runCommand("stt-once.cjs", { stdin: JSON.stringify({ provider: proto }) });
    assert.equal(res.status, 1);
    assert.equal(JSON.parse(res.stdout).error_type, "invalid_provider");
  }

  // Invalid numeric & language inputs
  const badLang = runCommand("stt-once.cjs", { stdin: JSON.stringify({ language: "de;evil" }) });
  assert.equal(badLang.status, 1);
  assert.equal(JSON.parse(badLang.stdout).error_type, "invalid_input");

  const badMax = runCommand("stt-once.cjs", { stdin: JSON.stringify({ max_seconds: -5 }) });
  assert.equal(badMax.status, 1);
  assert.equal(JSON.parse(badMax.stdout).error_type, "invalid_input");

  const badModel = runCommand("stt-once.cjs", { stdin: JSON.stringify({ model: "../bad" }) });
  assert.equal(badModel.status, 1);
  assert.equal(JSON.parse(badModel.stdout).error_type, "invalid_input");

  // Missing Python executable cleanly returns error_type="missing"
  const missingPy = runCommand("stt-once.cjs", {
    stdin: JSON.stringify({ provider: "fast", language: "de", max_seconds: 5 }),
    env: { STT_PYTHON: "definitely-nonexistent-python-binary-xyz" }
  });
  assert.equal(missingPy.status, 1);
  assert.equal(JSON.parse(missingPy.stdout).error_type, "missing");
});

test("commands/stt-once-improved.cjs: validates provider, inputs, and missing python", () => {
  const badProv = runCommand("stt-once-improved.cjs", { stdin: JSON.stringify({ provider: "constructor" }) });
  assert.equal(badProv.status, 1);
  assert.equal(JSON.parse(badProv.stdout).error_type, "invalid_provider");

  const badLang = runCommand("stt-once-improved.cjs", { stdin: JSON.stringify({ language: "bad\nlang" }) });
  assert.equal(badLang.status, 1);
  assert.equal(JSON.parse(badLang.stdout).error_type, "invalid_input");

  const missingPy = runCommand("stt-once-improved.cjs", {
    stdin: JSON.stringify({ provider: "cloud", language: "en", max_seconds: 10 }),
    env: { STT_PYTHON: "definitely-nonexistent-python-binary-xyz" }
  });
  assert.equal(missingPy.status, 1);
  assert.equal(JSON.parse(missingPy.stdout).error_type, "missing");
});

test("commands/stt-models.cjs & stt.cjs: isolated lifecycle, corrupt fallback, prototype safety", (t) => {
  const tmpDir = makeTempDir("stt-models-");
  t.after(() => fs.rmSync(tmpDir, { recursive: true, force: true }));

  const cfgDir = path.join(tmpDir, "cfg");
  const cacheDir = path.join(tmpDir, "hf_hub");
  fs.mkdirSync(cacheDir, { recursive: true });
  const env = { STT_CONFIG_DIR: cfgDir, HUGGINGFACE_HUB_CACHE: cacheDir };

  // Prototype pollution keys safely rejected
  for (const proto of ["constructor", "toString", "__proto__"]) {
    const sel = runCommand("stt-models.cjs", {
      stdin: JSON.stringify({ action: "select", model: proto }),
      env
    });
    assert.equal(sel.status, 0);
    assert.equal(JSON.parse(sel.stdout).error, "invalid_model");

    const rem = runCommand("stt-models.cjs", {
      stdin: JSON.stringify({ action: "remove", model: proto }),
      env
    });
    assert.equal(rem.status, 0);
    assert.equal(JSON.parse(rem.stdout).error, "invalid_model");
  }

  // Non-string action handled cleanly
  const badAct = runCommand("stt-models.cjs", { stdin: JSON.stringify({ action: 123 }), env });
  assert.equal(badAct.status, 0);
  assert.equal(JSON.parse(badAct.stdout).error, "invalid_action");

  // Fake downloaded distil-de model
  const distilDir = path.join(cacheDir, "models--Systran--faster-whisper-large-v3-turbo");
  fs.mkdirSync(distilDir, { recursive: true });

  const status1 = JSON.parse(runCommand("stt-models.cjs", { stdin: JSON.stringify({ action: "status" }), env }).stdout);
  assert.equal(status1.success, true);
  assert.equal(status1.downloadedModels, 1);
  assert.equal(status1.models["distil-de"].downloaded, true);

  // Select downloaded model
  const selectRes = JSON.parse(
    runCommand("stt-models.cjs", { stdin: JSON.stringify({ action: "select", model: "distil-de" }), env }).stdout
  );
  assert.equal(selectRes.success, true);
  assert.equal(fs.readFileSync(path.join(cfgDir, "selected_model"), "utf8"), "distil-de");

  // Corrupt selected_model falls back to tiny
  fs.writeFileSync(path.join(cfgDir, "selected_model"), "corrupt-model", "utf8");
  const status2 = JSON.parse(runCommand("stt-models.cjs", { stdin: JSON.stringify({ action: "status" }), env }).stdout);
  assert.equal(status2.selectedModel, "tiny");

  // Remove distil-de
  const remRes = JSON.parse(
    runCommand("stt-models.cjs", { stdin: JSON.stringify({ action: "remove", model: "distil-de" }), env }).stdout
  );
  assert.equal(remRes.success, true);
  assert.equal(fs.existsSync(distilDir), false);

  // Wrapper commands/stt.cjs succeeds cleanly
  const listWrap = runCommand("stt.cjs", { stdin: "", env });
  assert.equal(listWrap.status, 0);
  assert.match(listWrap.stdout, /STT-MODELLE/);
});

test("commands/stt-hotkey-* & stt-record.cjs: isolated runtime dir & dangerous PID protection", (t) => {
  const rtDir = makeTempDir("stt-rt-");
  t.after(() => fs.rmSync(rtDir, { recursive: true, force: true }));
  const env = { STT_RUNTIME_DIR: rtDir, STT_RECORD_WAIT_MS: "0" };

  // Dangerous PID "-1" MUST NOT signal all user processes; status reports not_running and stop cleans file
  const pidFile = path.join(rtDir, "stt_daemon.pid");
  fs.writeFileSync(pidFile, "-1", "utf8");

  const st1 = JSON.parse(runCommand("stt-hotkey-status.cjs", { env }).stdout);
  assert.equal(st1.daemon_running, false);
  assert.equal(st1.status, "not_running");

  const stop1 = JSON.parse(runCommand("stt-hotkey-stop.cjs", { env }).stdout);
  assert.equal(stop1.success, true);
  assert.equal(fs.existsSync(pidFile), false);

  // Simulate live daemon using current test process PID
  fs.writeFileSync(pidFile, String(process.pid), "utf8");
  fs.writeFileSync(path.join(rtDir, "stt_status"), JSON.stringify({ status: "ready", model: "distil-de" }), "utf8");
  fs.writeFileSync(path.join(rtDir, "stt_transcript.txt"), "Hallo aus dem Test äöü", "utf8");

  // stt-hotkey-start detects already-running daemon without spawning python
  const startAlready = JSON.parse(runCommand("stt-hotkey-start.cjs", { stdin: "{}", env }).stdout);
  assert.equal(startAlready.success, true);
  assert.equal(startAlready.pid, process.pid);

  // stt-hotkey-start rejects invalid language
  const startBadLang = JSON.parse(
    runCommand("stt-hotkey-start.cjs", { stdin: JSON.stringify({ language: "de;evil" }), env }).stdout
  );
  assert.equal(startBadLang.success, false);
  assert.equal(startBadLang.error, "invalid_input");

  // stt-hotkey-status reports live daemon + transcript
  const st2 = JSON.parse(runCommand("stt-hotkey-status.cjs", { env }).stdout);
  assert.equal(st2.daemon_running, true);
  assert.equal(st2.pid, process.pid);
  assert.equal(st2.last_transcript.text, "Hallo aus dem Test äöü");

  // stt-record start creates start trigger
  const recStart = JSON.parse(runCommand("stt-record.cjs", { stdin: JSON.stringify({ action: "start" }), env }).stdout);
  assert.equal(recStart.success, true);
  assert.equal(fs.existsSync(path.join(rtDir, "stt_start")), true);

  // stt-record stop while recording creates stop trigger and reads transcript
  fs.writeFileSync(path.join(rtDir, "stt_status"), JSON.stringify({ status: "recording" }), "utf8");
  const recStop = JSON.parse(runCommand("stt-record.cjs", { stdin: JSON.stringify({ action: "stop" }), env }).stdout);
  assert.equal(recStop.success, true);
  assert.equal(recStop.transcript, "Hallo aus dem Test äöü");
  assert.equal(fs.existsSync(path.join(rtDir, "stt_stop")), true);

  // stt-record get & invalid action
  const recGet = JSON.parse(runCommand("stt-record.cjs", { stdin: JSON.stringify({ action: "get" }), env }).stdout);
  assert.equal(recGet.success, true);
  assert.equal(recGet.transcript, "Hallo aus dem Test äöü");

  const recBad = JSON.parse(runCommand("stt-record.cjs", { stdin: JSON.stringify({ action: 999 }), env }).stdout);
  assert.equal(recBad.success, false);
  assert.equal(recBad.error, "invalid_action");
});

test("commands/stt-arm.cjs & stt-disarm.cjs: PID safety, validation, and missing python", (t) => {
  const tmpDir = makeTempDir("stt-arm-");
  t.after(() => fs.rmSync(tmpDir, { recursive: true, force: true }));
  const pidFile = path.join(tmpDir, "daemon.pid");
  const env = { STT_ARM_PID_FILE: pidFile };

  // Missing python does NOT write "undefined" into PID file
  const armMissing = runCommand("stt-arm.cjs", {
    stdin: JSON.stringify({ language: "de" }),
    env: { ...env, STT_PYTHON: "definitely-nonexistent-python-binary-xyz" }
  });
  assert.equal(armMissing.status, 1);
  assert.equal(JSON.parse(armMissing.stdout).error_type, "spawn_failed");
  assert.equal(fs.existsSync(pidFile), false);

  // Invalid language rejected
  const armBadLang = runCommand("stt-arm.cjs", {
    stdin: JSON.stringify({ language: "bad;lang" }),
    env
  });
  assert.equal(armBadLang.status, 1);
  assert.equal(JSON.parse(armBadLang.stdout).error_type, "invalid_input");

  // Already armed live PID detected
  fs.writeFileSync(pidFile, String(process.pid), "utf8");
  const armBusy = runCommand("stt-arm.cjs", { stdin: "{}", env });
  assert.equal(armBusy.status, 0);
  assert.equal(JSON.parse(armBusy.stdout).success, false);

  // Disarm with dangerous "-1" PID does NOT signal -1 and cleans up file
  fs.writeFileSync(pidFile, "-1", "utf8");
  const disarmCorrupt = runCommand("stt-disarm.cjs", { stdin: "", env });
  assert.equal(disarmCorrupt.status, 0);
  const parsed = JSON.parse(disarmCorrupt.stdout);
  assert.equal(parsed.success, true);
  assert.equal(parsed.pid, null);
  assert.equal(parsed.signaled, false);
  assert.equal(fs.existsSync(pidFile), false);

  // Disarm when no PID file exists
  const disarmEmpty = runCommand("stt-disarm.cjs", { stdin: "", env });
  assert.equal(disarmEmpty.status, 0);
  assert.equal(JSON.parse(disarmEmpty.stdout).success, false);
});
