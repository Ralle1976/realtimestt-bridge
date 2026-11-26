#!/usr/bin/env node

/**
 * stt-models.cjs - Model Management for STT Plugin
 *
 * Commands:
 * - list: Show all available models
 * - status: Show which models are downloaded
 * - download <model>: Download a specific model
 * - select <model>: Select a downloaded model
 * - remove <model>: Remove a downloaded model
 */

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const {
  atomicWriteFile,
  hasOwn,
  isPathWithin,
  isSymlink,
  readStdinJson,
  resolvePythonCommand
} = require("../lib/stt-runtime.cjs");

// Model definitions
const MODELS = {
  // Standard Whisper models
  "tiny": {
    size: "39 MB",
    description: "Fastest, basic quality",
    hfId: "tiny",
    speed: "~2-3s"
  },
  "base": {
    size: "142 MB",
    description: "Good balance",
    hfId: "base",
    speed: "~4-6s"
  },
  "small": {
    size: "466 MB",
    description: "Better quality",
    hfId: "small",
    speed: "~10-15s"
  },
  "medium": {
    size: "1.5 GB",
    description: "High quality",
    hfId: "medium",
    speed: "~20-30s"
  },
  "large-v3": {
    size: "3.1 GB",
    description: "Best quality (slow on CPU)",
    hfId: "large-v3",
    speed: "~40-60s"
  },
  // Distilled/optimized models
  "distil-de": {
    size: "1.6 GB",
    description: "BEST for German! Turbo-optimiert, 8x schneller",
    hfId: "large-v3-turbo",
    speed: "~0.5-1s",
    recommended: true
  },
  "distil-en": {
    size: "1.5 GB",
    description: "BEST for English! 6x faster than large",
    hfId: "distil-whisper/distil-large-v3",
    speed: "~0.5-1s"
  },
  "distil-large": {
    size: "1.5 GB",
    description: "Multilingual distilled model",
    hfId: "distil-whisper/distil-large-v3",
    speed: "~0.5-1s"
  }
};

function getConfigDir() {
  const override = (process.env.STT_CONFIG_DIR || "").trim();
  return override || path.join(os.homedir(), ".config", "claude-stt");
}

function getSelectedModelFile() {
  return path.join(getConfigDir(), "selected_model");
}

// HuggingFace cache directory (respects HUGGINGFACE_HUB_CACHE and HF_HOME/hub)
function getHfCacheDir() {
  const hubCache = (process.env.HUGGINGFACE_HUB_CACHE || "").trim();
  if (hubCache) return hubCache;
  const hfHome = (process.env.HF_HOME || "").trim();
  if (hfHome) return path.join(hfHome, "hub");
  return path.join(os.homedir(), ".cache", "huggingface", "hub");
}

function ensureConfigDir() {
  const configDir = getConfigDir();
  if (!fs.existsSync(configDir)) {
    fs.mkdirSync(configDir, { recursive: true, mode: 0o700 });
  }
}

function getSelectedModel() {
  const selectedFile = getSelectedModelFile();
  try {
    if (fs.existsSync(selectedFile) && !isSymlink(selectedFile)) {
      const value = fs.readFileSync(selectedFile, "utf8").trim();
      if (hasOwn(MODELS, value)) {
        return value;
      }
    }
  } catch {
    // Fallback to default on read error
  }
  return "tiny";
}

function setSelectedModel(modelKey) {
  if (typeof modelKey !== "string" || !hasOwn(MODELS, modelKey)) {
    return false;
  }
  ensureConfigDir();
  atomicWriteFile(getSelectedModelFile(), modelKey);
  return true;
}

function getCandidateModelDirs(modelKey) {
  if (typeof modelKey !== "string" || !hasOwn(MODELS, modelKey)) {
    return [];
  }
  const cacheDir = getHfCacheDir();
  const hfId = MODELS[modelKey].hfId;

  if (hfId.includes("/")) {
    return [path.join(cacheDir, `models--${hfId.replace(/\//g, "--")}`)];
  }
  return [
    path.join(cacheDir, `models--Systran--faster-whisper-${hfId}`),
    path.join(cacheDir, `models--mobiuslabsgmbh--faster-whisper-${hfId}`),
    path.join(cacheDir, `models--openai--whisper-${hfId}`)
  ];
}

function findDownloadedModelDir(modelKey) {
  for (const dir of getCandidateModelDirs(modelKey)) {
    if (fs.existsSync(dir)) {
      return dir;
    }
  }
  return null;
}

function isModelDownloaded(modelKey) {
  return findDownloadedModelDir(modelKey) !== null;
}

function listModels() {
  const selected = getSelectedModel();

  console.log("\n=== STT-MODELLE - Speech-to-Text Model Manager ===\n");
  console.log("Modell        | Grosse   | Speed    | Status   | Beschreibung");
  console.log("--------------|----------|----------|----------|---------------------------");

  for (const [key, model] of Object.entries(MODELS)) {
    const downloaded = isModelDownloaded(key);
    const isSelected = key === selected;

    let status;
    if (isSelected && downloaded) {
      status = "[AKTIV] ";
    } else if (downloaded) {
      status = "[OK]    ";
    } else {
      status = "[-]     ";
    }

    const rec = model.recommended ? " *EMPFOHLEN*" : "";
    const name = key.padEnd(13);
    const size = model.size.padEnd(8);
    const speed = model.speed.padEnd(8);

    console.log(`${name} | ${size} | ${speed} | ${status} | ${model.description}${rec}`);
  }

  console.log("\n------------------------------------------------------------");
  console.log("Legende: [AKTIV] = Ausgewahlt, [OK] = Heruntergeladen, [-] = Nicht installiert");
  console.log(`\nAktuell ausgewahlt: ${selected}`);
  console.log("\nAktionen:");
  console.log('  Download:  /stt-models {"action": "download", "model": "distil-de"}');
  console.log('  Auswahlen: /stt-models {"action": "select", "model": "distil-de"}');
  console.log('  Entfernen: /stt-models {"action": "remove", "model": "tiny"}');
  console.log('  Status:    /stt-models {"action": "status"}');
  console.log("\nEmpfehlung fur Deutsch: distil-de (schnell & genau)");
  console.log("");
}

function selectModel(modelKey) {
  if (typeof modelKey !== "string" || !hasOwn(MODELS, modelKey)) {
    return {
      success: false,
      error: "invalid_model",
      message: `Unbekanntes Modell '${String(modelKey)}'. Verfugbar: ${Object.keys(MODELS).join(", ")}`
    };
  }
  const model = MODELS[modelKey];

  if (!isModelDownloaded(modelKey)) {
    return {
      success: false,
      error: "not_downloaded",
      message: `Modell '${modelKey}' ist nicht heruntergeladen. Bitte zuerst herunterladen:\n  /stt-models {"action": "download", "model": "${modelKey}"}`
    };
  }

  setSelectedModel(modelKey);

  return {
    success: true,
    message: `Modell '${modelKey}' wurde ausgewahlt und ist jetzt aktiv.`,
    model: modelKey,
    info: {
      size: model.size,
      speed: model.speed,
      description: model.description
    }
  };
}

async function downloadModel(modelKey) {
  if (typeof modelKey !== "string" || !hasOwn(MODELS, modelKey)) {
    return {
      success: false,
      error: "invalid_model",
      message: `Unknown model '${String(modelKey)}'. Use /stt-models {"action": "list"} to see available models.`
    };
  }
  const model = MODELS[modelKey];

  if (isModelDownloaded(modelKey)) {
    return {
      success: true,
      message: `Model '${modelKey}' is already downloaded.`
    };
  }

  console.log(`\nDownloading model '${modelKey}' (${model.size})...`);
  console.log("This may take a few minutes depending on your connection.\n");

  // Pass HuggingFace ID as argv (never interpolated into code or shell string)
  const pythonCode = [
    "import sys",
    "try:",
    "    from faster_whisper import WhisperModel",
    "    hf_id = sys.argv[1]",
    "    print(f'Loading model: {hf_id}')",
    "    WhisperModel(hf_id, device='cpu', compute_type='int8')",
    "    print('Download complete!')",
    "except Exception as e:",
    "    print(f'Error: {e}', file=sys.stderr)",
    "    sys.exit(1)"
  ].join("\n");

  try {
    const pythonCmd = resolvePythonCommand();
    execFileSync(pythonCmd, ["-c", pythonCode, model.hfId], {
      stdio: "inherit",
      timeout: 600000 // 10 minutes
    });

    return {
      success: true,
      message: `Model '${modelKey}' downloaded successfully.`
    };
  } catch (error) {
    return {
      success: false,
      error: "download_failed",
      message: `Failed to download model '${modelKey}': ${error.message}`
    };
  }
}

function removeModel(modelKey) {
  if (typeof modelKey !== "string" || !hasOwn(MODELS, modelKey)) {
    return {
      success: false,
      error: "invalid_model",
      message: `Unknown model '${String(modelKey)}'.`
    };
  }

  const modelDir = findDownloadedModelDir(modelKey);
  if (!modelDir) {
    return {
      success: true,
      message: `Model '${modelKey}' is not downloaded.`
    };
  }

  const cacheDir = getHfCacheDir();
  if (!isPathWithin(modelDir, cacheDir)) {
    return {
      success: false,
      error: "unsafe_path",
      message: "Refusing to remove directory outside HuggingFace cache."
    };
  }

  try {
    fs.rmSync(modelDir, { recursive: true, force: true });

    if (getSelectedModel() === modelKey) {
      const replacement = Object.keys(MODELS).find((k) => isModelDownloaded(k)) || "tiny";
      setSelectedModel(replacement);
    }

    return {
      success: true,
      message: `Model '${modelKey}' removed successfully.`
    };
  } catch (error) {
    return {
      success: false,
      error: "remove_failed",
      message: `Failed to remove model: ${error.message}`
    };
  }
}

function getStatus() {
  const status = {};
  let totalDownloaded = 0;
  const selected = getSelectedModel();

  for (const key of Object.keys(MODELS)) {
    const downloaded = isModelDownloaded(key);
    status[key] = {
      downloaded,
      selected: key === selected,
      ...MODELS[key]
    };
    if (downloaded) totalDownloaded++;
  }

  return {
    success: true,
    selectedModel: selected,
    totalModels: Object.keys(MODELS).length,
    downloadedModels: totalDownloaded,
    models: status
  };
}

async function main() {
  const payload = await readStdinJson();
  const rawAction = payload.action === undefined || payload.action === null ? "list" : payload.action;
  const action = typeof rawAction === "string" ? rawAction.trim().toLowerCase() : "";
  const modelKey = typeof payload.model === "string" ? payload.model.trim() : null;

  let result;

  switch (action) {
    case "list":
      listModels();
      result = { success: true, action: "list" };
      break;

    case "status":
      result = getStatus();
      break;

    case "download":
      if (!modelKey) {
        result = {
          success: false,
          error: "missing_model",
          message: "Please specify a model to download: {\"action\": \"download\", \"model\": \"distil-de\"}"
        };
      } else {
        result = await downloadModel(modelKey);
      }
      break;

    case "remove":
      if (!modelKey) {
        result = {
          success: false,
          error: "missing_model",
          message: "Bitte Modell angeben: {\"action\": \"remove\", \"model\": \"tiny\"}"
        };
      } else {
        result = removeModel(modelKey);
      }
      break;

    case "select":
      if (!modelKey) {
        result = {
          success: false,
          error: "missing_model",
          message: "Bitte Modell angeben: {\"action\": \"select\", \"model\": \"distil-de\"}"
        };
      } else {
        result = selectModel(modelKey);
      }
      break;

    default:
      result = {
        success: false,
        error: "invalid_action",
        message: `Unbekannte Aktion '${String(rawAction)}'. Verfugbar: list, status, download, select, remove`
      };
  }

  process.stdout.write(JSON.stringify(result, null, 2));
}

main().catch((err) => {
  console.error("Error:", err);
  process.exit(1);
});
