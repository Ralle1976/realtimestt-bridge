#!/usr/bin/env python3
"""
STT Model Manager - Download, List, and Select Whisper Models

Manages faster-whisper models for Speech-to-Text functionality.

Usage:
  python3 stt_models.py                    # Interactive menu
  python3 stt_models.py '{"action": "list"}'
  python3 stt_models.py '{"action": "status"}'
  python3 stt_models.py '{"action": "download", "model": "distil-de"}'
  python3 stt_models.py '{"action": "select", "model": "distil-de"}'
  python3 stt_models.py '{"action": "remove", "model": "tiny"}'

Models are stored in: ~/.cache/huggingface/hub/
Selected model is stored in: ~/.config/claude-stt/selected_model
"""

import json
import os
import sys
from pathlib import Path

# Model definitions with metadata
MODELS = {
    "tiny": {
        "hf_id": "Systran/faster-whisper-tiny",
        "size": "39 MB",
        "speed": "~2-3s",
        "quality": "Basic",
        "description": "Schnellstes Modell, Basis-Qualitat"
    },
    "base": {
        "hf_id": "Systran/faster-whisper-base",
        "size": "142 MB",
        "speed": "~4-6s",
        "quality": "Good",
        "description": "Gute Balance aus Geschwindigkeit und Qualitat"
    },
    "small": {
        "hf_id": "Systran/faster-whisper-small",
        "size": "466 MB",
        "speed": "~10-15s",
        "quality": "Better",
        "description": "Bessere Qualitat, langsamer"
    },
    "medium": {
        "hf_id": "Systran/faster-whisper-medium",
        "size": "1.5 GB",
        "speed": "~20-30s",
        "quality": "High",
        "description": "Hohe Qualitat, fur langere Texte"
    },
    "large-v3": {
        "hf_id": "Systran/faster-whisper-large-v3",
        "size": "3.1 GB",
        "speed": "~40-60s",
        "quality": "Best",
        "description": "Beste Qualitat (langsam auf CPU)"
    },
    "distil-de": {
        "hf_id": "primeline/whisper-large-v3-turbo-german",
        "size": "1.5 GB",
        "speed": "~0.5-1s",
        "quality": "Excellent",
        "description": "BESTE WAHL fur Deutsch! 6x schneller als large",
        "recommended": True,
        "language": "de"
    },
    "distil-en": {
        "hf_id": "distil-whisper/distil-large-v3",
        "size": "1.5 GB",
        "speed": "~0.5-1s",
        "quality": "Excellent",
        "description": "Beste Wahl fur Englisch",
        "language": "en"
    },
    "distil-large": {
        "hf_id": "distil-whisper/distil-large-v3",
        "size": "1.5 GB",
        "speed": "~0.5-1s",
        "quality": "Excellent",
        "description": "Multilingual distilled model"
    }
}

# Config directory for selected model
CONFIG_DIR = Path.home() / ".config" / "claude-stt"
SELECTED_MODEL_FILE = CONFIG_DIR / "selected_model"

# HuggingFace cache directory
HF_CACHE_DIR = Path.home() / ".cache" / "huggingface" / "hub"


def ensure_config_dir():
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_selected_model() -> str:
    """Get currently selected model, default to 'tiny'."""
    if SELECTED_MODEL_FILE.exists():
        return SELECTED_MODEL_FILE.read_text().strip()
    return "tiny"  # Default


def set_selected_model(model: str) -> bool:
    """Set the currently selected model."""
    if model not in MODELS:
        return False
    ensure_config_dir()
    SELECTED_MODEL_FILE.write_text(model)
    return True


def is_model_downloaded(model: str) -> bool:
    """Check if a model is downloaded in HuggingFace cache."""
    if model not in MODELS:
        return False

    hf_id = MODELS[model]["hf_id"]

    # HuggingFace stores models in directories like:
    # models--Systran--faster-whisper-tiny
    # models--primeline--whisper-large-v3-turbo-german
    dir_name = f"models--{hf_id.replace('/', '--')}"
    model_dir = HF_CACHE_DIR / dir_name

    if not model_dir.exists():
        return False

    # Check if snapshots directory has content (actual model files)
    snapshots_dir = model_dir / "snapshots"
    if snapshots_dir.exists():
        # Check if any snapshot directory has files
        for snapshot in snapshots_dir.iterdir():
            if snapshot.is_dir() and any(snapshot.iterdir()):
                return True

    return False


def get_all_model_status() -> dict:
    """Get download status of all models."""
    selected = get_selected_model()
    status = {}

    for model_name, model_info in MODELS.items():
        downloaded = is_model_downloaded(model_name)
        status[model_name] = {
            "downloaded": downloaded,
            "selected": model_name == selected,
            "size": model_info["size"],
            "speed": model_info["speed"],
            "quality": model_info["quality"],
            "description": model_info["description"],
            "recommended": model_info.get("recommended", False),
            "language": model_info.get("language")
        }

    return status


def download_model(model: str) -> dict:
    """Download a model using faster-whisper."""
    if model not in MODELS:
        return {
            "success": False,
            "error": "invalid_model",
            "message": f"Unbekanntes Modell: {model}. Verfugbar: {', '.join(MODELS.keys())}"
        }

    if is_model_downloaded(model):
        return {
            "success": True,
            "message": f"Modell '{model}' ist bereits heruntergeladen.",
            "already_exists": True
        }

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {
            "success": False,
            "error": "missing_dependency",
            "message": "faster-whisper nicht installiert. Bitte: pip install faster-whisper"
        }

    hf_id = MODELS[model]["hf_id"]
    print(f"Lade Modell '{model}' herunter ({MODELS[model]['size']})...", file=sys.stderr)
    print(f"HuggingFace ID: {hf_id}", file=sys.stderr)
    print("Dies kann einige Minuten dauern...", file=sys.stderr)

    try:
        # Loading the model triggers the download
        _ = WhisperModel(hf_id, device="cpu", compute_type="int8")

        return {
            "success": True,
            "message": f"Modell '{model}' erfolgreich heruntergeladen!",
            "model": model,
            "size": MODELS[model]["size"]
        }
    except Exception as e:
        return {
            "success": False,
            "error": "download_error",
            "message": f"Download fehlgeschlagen: {str(e)}"
        }


def select_model(model: str) -> dict:
    """Select a model for use (must be downloaded first)."""
    if model not in MODELS:
        return {
            "success": False,
            "error": "invalid_model",
            "message": f"Unbekanntes Modell: {model}. Verfugbar: {', '.join(MODELS.keys())}"
        }

    if not is_model_downloaded(model):
        return {
            "success": False,
            "error": "not_downloaded",
            "message": f"Modell '{model}' ist nicht heruntergeladen. Bitte zuerst herunterladen mit: action='download', model='{model}'"
        }

    set_selected_model(model)

    return {
        "success": True,
        "message": f"Modell '{model}' wurde ausgewahlt und ist jetzt aktiv.",
        "model": model,
        "info": MODELS[model]
    }


def remove_model(model: str) -> dict:
    """Remove a downloaded model."""
    if model not in MODELS:
        return {
            "success": False,
            "error": "invalid_model",
            "message": f"Unbekanntes Modell: {model}"
        }

    if not is_model_downloaded(model):
        return {
            "success": False,
            "error": "not_downloaded",
            "message": f"Modell '{model}' ist nicht heruntergeladen."
        }

    hf_id = MODELS[model]["hf_id"]
    dir_name = f"models--{hf_id.replace('/', '--')}"
    model_dir = HF_CACHE_DIR / dir_name

    try:
        import shutil
        shutil.rmtree(model_dir)

        # If removed model was selected, reset to default
        if get_selected_model() == model:
            # Find another downloaded model or reset to tiny
            for m in MODELS:
                if is_model_downloaded(m):
                    set_selected_model(m)
                    break
            else:
                set_selected_model("tiny")

        return {
            "success": True,
            "message": f"Modell '{model}' wurde entfernt.",
            "model": model
        }
    except Exception as e:
        return {
            "success": False,
            "error": "remove_error",
            "message": f"Entfernen fehlgeschlagen: {str(e)}"
        }


def format_model_list() -> str:
    """Format model list for display."""
    status = get_all_model_status()
    selected = get_selected_model()

    lines = []
    lines.append("=" * 70)
    lines.append("STT-MODELLE - Speech-to-Text Model Manager")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"{'Modell':<12} {'Status':<12} {'Grosse':<10} {'Speed':<12} {'Beschreibung'}")
    lines.append("-" * 70)

    for model_name, info in status.items():
        # Status indicator
        if info["selected"] and info["downloaded"]:
            status_str = "[AKTIV]"
        elif info["downloaded"]:
            status_str = "[OK]"
        else:
            status_str = "[-]"

        # Recommendation marker
        name_str = model_name
        if info["recommended"]:
            name_str = f"*{model_name}"

        desc = info["description"][:30] + "..." if len(info["description"]) > 30 else info["description"]

        lines.append(f"{name_str:<12} {status_str:<12} {info['size']:<10} {info['speed']:<12} {desc}")

    lines.append("-" * 70)
    lines.append("")
    lines.append("Legende: [AKTIV] = Ausgewahlt, [OK] = Heruntergeladen, [-] = Nicht installiert")
    lines.append("         * = Empfohlen")
    lines.append("")
    lines.append("Aktionen:")
    lines.append('  Download:  {"action": "download", "model": "<name>"}')
    lines.append('  Auswahlen: {"action": "select", "model": "<name>"}')
    lines.append('  Entfernen: {"action": "remove", "model": "<name>"}')
    lines.append('  Status:    {"action": "status"}')
    lines.append("")
    lines.append(f"Empfehlung fur Deutsch: distil-de (schnell & genau)")
    lines.append("=" * 70)

    return "\n".join(lines)


def main():
    """Main entry point."""

    # Parse input
    if len(sys.argv) > 1:
        try:
            input_data = json.loads(sys.argv[1])
        except json.JSONDecodeError:
            input_data = {"action": "list"}
    else:
        # Check for stdin input
        if not sys.stdin.isatty():
            try:
                stdin_data = sys.stdin.read().strip()
                if stdin_data:
                    input_data = json.loads(stdin_data)
                else:
                    input_data = {"action": "list"}
            except json.JSONDecodeError:
                input_data = {"action": "list"}
        else:
            input_data = {"action": "list"}

    action = input_data.get("action", "list")
    model = input_data.get("model")

    if action == "list":
        # Human-readable list
        print(format_model_list())

    elif action == "status":
        # JSON status for programmatic use
        result = {
            "success": True,
            "selected_model": get_selected_model(),
            "models": get_all_model_status()
        }
        print(json.dumps(result, indent=2))

    elif action == "download":
        if not model:
            print(json.dumps({
                "success": False,
                "error": "missing_model",
                "message": "Bitte Modell angeben: {\"action\": \"download\", \"model\": \"<name>\"}"
            }))
        else:
            result = download_model(model)
            print(json.dumps(result, indent=2))

    elif action == "select":
        if not model:
            print(json.dumps({
                "success": False,
                "error": "missing_model",
                "message": "Bitte Modell angeben: {\"action\": \"select\", \"model\": \"<name>\"}"
            }))
        else:
            result = select_model(model)
            print(json.dumps(result, indent=2))

    elif action == "remove":
        if not model:
            print(json.dumps({
                "success": False,
                "error": "missing_model",
                "message": "Bitte Modell angeben: {\"action\": \"remove\", \"model\": \"<name>\"}"
            }))
        else:
            result = remove_model(model)
            print(json.dumps(result, indent=2))

    else:
        print(json.dumps({
            "success": False,
            "error": "invalid_action",
            "message": f"Unbekannte Aktion: {action}. Verfugbar: list, status, download, select, remove"
        }))


if __name__ == "__main__":
    main()
