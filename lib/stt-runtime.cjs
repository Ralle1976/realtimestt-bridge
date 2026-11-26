"use strict";

/**
 * Shared cross-platform runtime, security, and validation utilities for STT Node commands.
 * Zero external dependencies (Node.js standard library only).
 */

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");

const LANGUAGE_PATTERN = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;
const MODEL_NAME_PATTERN = /^[A-Za-z0-9._-]+$/;
const PID_PATTERN = /^[1-9]\d*$/;
const MAX_PID = 2147483647;
const DEFAULT_MAX_STDIN_BYTES = 1024 * 1024; // 1 MiB

function hasOwn(obj, key) {
  return obj != null && Object.prototype.hasOwnProperty.call(obj, key);
}

function sanitizeUserTag(raw) {
  const cleaned = String(raw || "")
    .replace(/[^A-Za-z0-9._-]/g, "_")
    .replace(/^[._-]+|[._-]+$/g, "");
  return cleaned || "user";
}

/**
 * Resolve a safe Python executable name/path across Linux, macOS, and Windows.
 * Respects STT_PYTHON environment override.
 */
function resolvePythonCommand() {
  const override = (process.env.STT_PYTHON || "").trim();
  if (override) {
    return override;
  }

  const isWin = process.platform === "win32";
  const candidates = isWin ? ["python", "python3"] : ["python3", "python"];
  const pathEnv = process.env.PATH || "";
  const pathDirs = pathEnv.split(path.delimiter).filter(Boolean);
  const exts = isWin
    ? (process.env.PATHEXT || ".EXE;.CMD;.BAT;.COM")
        .split(";")
        .map((e) => e.trim())
        .filter(Boolean)
    : [""];

  const foundReal = [];
  const foundFallback = [];

  for (const cmd of candidates) {
    for (const dir of pathDirs) {
      for (const ext of exts) {
        const fullPath = path.join(dir, cmd + ext);
        try {
          if (fs.existsSync(fullPath) && fs.statSync(fullPath).isFile()) {
            const isWinStoreStub =
              isWin && fullPath.toLowerCase().includes(`${path.sep}microsoft${path.sep}windowsapps${path.sep}`);
            if (isWinStoreStub) {
              foundFallback.push(fullPath);
            } else {
              foundReal.push(fullPath);
            }
          }
        } catch {
          // Ignore inaccessible PATH entries
        }
      }
    }
  }

  if (foundReal.length > 0) {
    return foundReal[0];
  }
  if (foundFallback.length > 0) {
    return foundFallback[0];
  }
  return isWin ? "python" : "python3";
}

function ensurePrivateDir(dirPath) {
  let exists = false;
  try {
    const lst = fs.lstatSync(dirPath);
    if (lst.isSymbolicLink()) {
      throw new Error(`Refusing to use symlink as runtime directory: ${dirPath}`);
    }
    if (!lst.isDirectory()) {
      throw new Error(`Runtime path is not a directory: ${dirPath}`);
    }
    exists = true;
  } catch (err) {
    if (err.code !== "ENOENT") {
      throw err;
    }
  }

  if (!exists) {
    fs.mkdirSync(dirPath, { recursive: true, mode: 0o700 });
  }

  const lst = fs.lstatSync(dirPath);
  if (lst.isSymbolicLink() || !lst.isDirectory()) {
    throw new Error(`Runtime path is not a real directory: ${dirPath}`);
  }

  if (process.platform !== "win32" && typeof process.getuid === "function") {
    if (lst.uid !== process.getuid()) {
      throw new Error(`Runtime directory is not owned by current user: ${dirPath}`);
    }
    if ((lst.mode & 0o077) !== 0) {
      try {
        fs.chmodSync(dirPath, 0o700);
      } catch {
        // Best-effort tighten permissions
      }
    }
  }
}

/**
 * Compute private per-user runtime directory matching stt_common.get_runtime_dir().
 */
function getRuntimeDir() {
  const override = (process.env.STT_RUNTIME_DIR || "").trim();
  let runtimeDir;

  if (override) {
    runtimeDir = path.resolve(override);
  } else if (process.platform !== "win32" && typeof process.getuid === "function") {
    const uid = process.getuid();
    const xdg = (process.env.XDG_RUNTIME_DIR || "").trim();
    let useXdg = false;
    if (xdg) {
      try {
        const st = fs.lstatSync(xdg);
        if (st.isDirectory() && !st.isSymbolicLink() && st.uid === uid) {
          useXdg = true;
        }
      } catch {
        useXdg = false;
      }
    }
    runtimeDir = useXdg
      ? path.join(xdg, "realtimestt-bridge")
      : path.join(os.tmpdir(), `realtimestt-bridge-${uid}`);
  } else {
    let username = "user";
    try {
      username = os.userInfo().username;
    } catch {
      username = process.env.USERNAME || process.env.USER || "user";
    }
    runtimeDir = path.join(os.tmpdir(), `realtimestt-bridge-${sanitizeUserTag(username)}`);
  }

  ensurePrivateDir(runtimeDir);
  return runtimeDir;
}

function getRuntimePaths() {
  const runtimeDir = getRuntimeDir();
  return {
    runtimeDir,
    pidFile: path.join(runtimeDir, "stt_daemon.pid"),
    statusFile: path.join(runtimeDir, "stt_status"),
    transcriptFile: path.join(runtimeDir, "stt_transcript.txt"),
    startTrigger: path.join(runtimeDir, "stt_start"),
    stopTrigger: path.join(runtimeDir, "stt_stop")
  };
}

function parsePid(text) {
  if (typeof text !== "string") return null;
  const trimmed = text.trim();
  if (!PID_PATTERN.test(trimmed)) return null;
  const pid = Number(trimmed);
  if (!Number.isSafeInteger(pid) || pid <= 0 || pid > MAX_PID) {
    return null;
  }
  return pid;
}

function isSymlink(filePath) {
  try {
    return fs.lstatSync(filePath).isSymbolicLink();
  } catch {
    return false;
  }
}

function readPidFile(pidFile) {
  try {
    const st = fs.lstatSync(pidFile);
    if (st.isSymbolicLink() || !st.isFile()) {
      return null;
    }
    const content = fs.readFileSync(pidFile, "utf8");
    return parsePid(content);
  } catch {
    return null;
  }
}

function isProcessRunning(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0 || pid > MAX_PID) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err && err.code === "EPERM";
  }
}

function safeReadTextFile(filePath) {
  try {
    const st = fs.lstatSync(filePath);
    if (st.isSymbolicLink() || !st.isFile()) {
      return null;
    }
    return fs.readFileSync(filePath, "utf8");
  } catch {
    return null;
  }
}

function atomicWriteFile(filePath, content, mode = 0o600) {
  if (isSymlink(filePath)) {
    throw new Error(`Refusing to overwrite symlink: ${filePath}`);
  }
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const tmpName = `.${path.basename(filePath)}.${process.pid}.${crypto.randomBytes(6).toString("hex")}.tmp`;
  const tmpPath = path.join(dir, tmpName);
  try {
    fs.writeFileSync(tmpPath, content, { encoding: "utf8", mode, flag: "wx" });
    if (isSymlink(filePath)) {
      throw new Error(`Refusing to overwrite symlink: ${filePath}`);
    }
    fs.renameSync(tmpPath, filePath);
  } catch (err) {
    try {
      fs.unlinkSync(tmpPath);
    } catch {
      // Ignore cleanup error
    }
    throw err;
  }
}

function isPathWithin(childPath, parentPath) {
  const resolvedParent = path.resolve(parentPath);
  const resolvedChild = path.resolve(childPath);
  const rel = path.relative(resolvedParent, resolvedChild);
  return Boolean(rel) && !rel.startsWith("..") && !path.isAbsolute(rel);
}

function validateLanguage(value) {
  if (value === undefined || value === null || value === "") {
    return { ok: true, value: "" };
  }
  if (typeof value !== "string") {
    return { ok: false, message: "Invalid 'language': expected a string." };
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return { ok: true, value: "" };
  }
  if (!LANGUAGE_PATTERN.test(trimmed)) {
    return {
      ok: false,
      message: `Invalid 'language' code "${trimmed}". Expected e.g. "de", "en", or "en-US".`
    };
  }
  return { ok: true, value: trimmed };
}

function validatePositiveNumber(value, { name, min = 0.05, max = 3600, defaultValue = null }) {
  if (value === undefined || value === null || value === "") {
    return { ok: true, value: defaultValue };
  }
  const num = typeof value === "number" ? value : Number(value);
  if (typeof value === "boolean" || !Number.isFinite(num) || num < min || num > max) {
    return {
      ok: false,
      message: `Invalid '${name}': expected a finite number between ${min} and ${max}.`
    };
  }
  return { ok: true, value: num };
}

function validateModelName(value, defaultValue = "tiny") {
  if (value === undefined || value === null || value === "") {
    return { ok: true, value: defaultValue };
  }
  if (typeof value !== "string") {
    return { ok: false, message: "Invalid 'model': expected a string." };
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return { ok: true, value: defaultValue };
  }
  if (!MODEL_NAME_PATTERN.test(trimmed)) {
    return { ok: false, message: `Invalid 'model' name "${trimmed}".` };
  }
  return { ok: true, value: trimmed };
}

async function readStdinJson({ maxBytes = DEFAULT_MAX_STDIN_BYTES, strict = false } = {}) {
  const chunks = [];
  let totalBytes = 0;

  for await (const chunk of process.stdin) {
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    totalBytes += buf.length;
    if (totalBytes > maxBytes) {
      const msg = `Input JSON exceeds maximum size of ${maxBytes} bytes.`;
      if (strict) {
        return { ok: false, error: "input_too_large", message: msg };
      }
      throw new Error(msg);
    }
    chunks.push(buf);
  }

  if (!chunks.length) {
    return strict ? { ok: true, data: {} } : {};
  }

  const text = Buffer.concat(chunks).toString("utf8").trim();
  if (!text) {
    return strict ? { ok: true, data: {} } : {};
  }

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    if (strict) {
      return { ok: false, error: "invalid_json", message: `Failed to parse JSON input: ${err.message}` };
    }
    return {};
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    if (strict) {
      return { ok: false, error: "invalid_json", message: "JSON input must be an object." };
    }
    return {};
  }

  return strict ? { ok: true, data: parsed } : parsed;
}

module.exports = {
  LANGUAGE_PATTERN,
  MODEL_NAME_PATTERN,
  PID_PATTERN,
  MAX_PID,
  hasOwn,
  resolvePythonCommand,
  getRuntimeDir,
  getRuntimePaths,
  parsePid,
  isSymlink,
  readPidFile,
  isProcessRunning,
  safeReadTextFile,
  atomicWriteFile,
  isPathWithin,
  validateLanguage,
  validatePositiveNumber,
  validateModelName,
  readStdinJson
};
