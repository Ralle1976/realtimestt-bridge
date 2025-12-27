#!/usr/bin/env node

/**
 * stt-models.cjs - Model Management for STT Plugin
 *
 * Commands:
 * - list: Show all available models
 * - status: Show which models are downloaded
 * - download <model>: Download a specific model
 * - remove <model>: Remove a downloaded model
 */

const { execSync, spawn } = require("node:child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

// Config directory for selected model
const CONFIG_DIR = path.join(os.homedir(), ".config", "claude-stt");
const SELECTED_MODEL_FILE = path.join(CONFIG_DIR, "selected_model");

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

// HuggingFace cache directory
function getHfCacheDir() {
  return process.env.HF_HOME ||
         process.env.HUGGINGFACE_HUB_CACHE ||
         path.join(os.homedir(), ".cache", "huggingface", "hub");
}

// Ensure config directory exists
function ensureConfigDir() {
  if (!fs.existsSync(CONFIG_DIR)) {
    fs.mkdirSync(CONFIG_DIR, { recursive: true });
  }
}

// Get currently selected model
function getSelectedModel() {
  if (fs.existsSync(SELECTED_MODEL_FILE)) {
    return fs.readFileSync(SELECTED_MODEL_FILE, "utf8").trim();
  }
  return "tiny"; // Default
}

// Set selected model
function setSelectedModel(modelKey) {
  ensureConfigDir();
  fs.writeFileSync(SELECTED_MODEL_FILE, modelKey);
}

// Check if model is downloaded
function isModelDownloaded(modelKey) {
  const model = MODELS[modelKey];
  if (!model) return false;

  const cacheDir = getHfCacheDir();
  const hfId = model.hfId;

  // Standard models are in models--<name>
  // Custom models are in models--<org>--<name>
  let modelDir;
  if (hfId.includes("/")) {
    modelDir = path.join(cacheDir, `models--${hfId.replace("/", "--")}`);
  } else {
    // Standard whisper models from openai
    modelDir = path.join(cacheDir, `models--Systran--faster-whisper-${hfId}`);
  }

  return fs.existsSync(modelDir);
}

// List all models with status
function listModels() {
  const selected = getSelectedModel();

  console.log("\n=== STT-MODELLE - Speech-to-Text Model Manager ===\n");
  console.log("Modell        | Grosse   | Speed    | Status   | Beschreibung");
  console.log("--------------|----------|----------|----------|---------------------------");

  for (const [key, model] of Object.entries(MODELS)) {
    const downloaded = isModelDownloaded(key);
    const isSelected = key === selected;

    // Status indicator
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

// Select a model (must be downloaded first)
function selectModel(modelKey) {
  const model = MODELS[modelKey];
  if (!model) {
    return {
      success: false,
      error: "invalid_model",
      message: `Unbekanntes Modell '${modelKey}'. Verfugbar: ${Object.keys(MODELS).join(", ")}`
    };
  }

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

// Download a model
async function downloadModel(modelKey) {
  const model = MODELS[modelKey];
  if (!model) {
    return {
      success: false,
      error: "invalid_model",
      message: `Unknown model '${modelKey}'. Use /stt-models {"action": "list"} to see available models.`
    };
  }

  if (isModelDownloaded(modelKey)) {
    return {
      success: true,
      message: `Model '${modelKey}' is already downloaded.`
    };
  }

  console.log(`\nDownloading model '${modelKey}' (${model.size})...`);
  console.log("This may take a few minutes depending on your connection.\n");

  // Use Python to download via faster-whisper
  const pythonCode = `
import sys
try:
    from faster_whisper import WhisperModel
    print(f"Loading model: ${model.hfId}")
    model = WhisperModel("${model.hfId}", device="cpu", compute_type="int8")
    print("Download complete!")
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
`;

  try {
    execSync(`python3 -c '${pythonCode}'`, {
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

// Remove a model
function removeModel(modelKey) {
  const model = MODELS[modelKey];
  if (!model) {
    return {
      success: false,
      error: "invalid_model",
      message: `Unknown model '${modelKey}'.`
    };
  }

  if (!isModelDownloaded(modelKey)) {
    return {
      success: true,
      message: `Model '${modelKey}' is not downloaded.`
    };
  }

  const cacheDir = getHfCacheDir();
  const hfId = model.hfId;

  let modelDir;
  if (hfId.includes("/")) {
    modelDir = path.join(cacheDir, `models--${hfId.replace("/", "--")}`);
  } else {
    modelDir = path.join(cacheDir, `models--Systran--faster-whisper-${hfId}`);
  }

  try {
    fs.rmSync(modelDir, { recursive: true, force: true });
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

// Get status of all models
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

// Read stdin JSON
async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch (err) {
    return {};
  }
}

// Main
async function main() {
  const payload = await readStdinJson();
  const action = (payload.action || "list").toLowerCase();
  const modelKey = payload.model;

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
        message: `Unbekannte Aktion '${action}'. Verfugbar: list, status, download, select, remove`
      };
  }

  process.stdout.write(JSON.stringify(result, null, 2));
}

main().catch((err) => {
  console.error("Error:", err);
  process.exit(1);
});
