#!/usr/bin/env python3
"""
Robustes STT Model Download Script

Dieses Script handhabt den Download von Whisper-Modellen mit:
- Speicherplatz-Pruefung
- Internet-Verbindungstest
- Saubere Fehlerbehandlung
- Fortschrittsanzeige
- Cache-Bereinigung bei korrupten Downloads

Verwendung:
  python3 stt_model_downloader.py download distil-de
  python3 stt_model_downloader.py list
  python3 stt_model_downloader.py status
  python3 stt_model_downloader.py clean distil-de
"""

import json
import os
import shutil
import socket
import sys
from pathlib import Path

# Modell-Definitionen mit korrekten HuggingFace IDs
MODELS = {
    "tiny": {
        "hf_id": "tiny",
        "size_mb": 39,
        "description": "Schnellstes, Basis-Qualitaet"
    },
    "base": {
        "hf_id": "base",
        "size_mb": 142,
        "description": "Gute Balance"
    },
    "small": {
        "hf_id": "small",
        "size_mb": 466,
        "description": "Bessere Qualitaet"
    },
    "medium": {
        "hf_id": "medium",
        "size_mb": 1500,
        "description": "Hohe Qualitaet"
    },
    "large-v3": {
        "hf_id": "large-v3",
        "size_mb": 3100,
        "description": "Beste Qualitaet (langsam auf CPU)"
    },
    "distil-de": {
        "hf_id": "large-v3-turbo",
        "size_mb": 1600,
        "description": "EMPFOHLEN fuer Deutsch! Turbo-optimiert",
        "recommended": True
    },
    "distil-en": {
        "hf_id": "distil-large-v3",
        "size_mb": 1500,
        "description": "Beste Wahl fuer Englisch"
    },
    "turbo": {
        "hf_id": "large-v3-turbo",
        "size_mb": 1600,
        "description": "Alias fuer distil-de"
    }
}

HF_CACHE_DIR = Path.home() / ".cache" / "huggingface" / "hub"
CONFIG_DIR = Path.home() / ".config" / "claude-stt"
SELECTED_MODEL_FILE = CONFIG_DIR / "selected_model"


def check_internet_connection(timeout=5):
    """Prueft ob Internet-Verbindung besteht."""
    try:
        socket.create_connection(("huggingface.co", 443), timeout=timeout)
        return True
    except (socket.timeout, socket.error):
        return False


def get_free_disk_space_mb():
    """Gibt freien Speicherplatz in MB zurueck."""
    stat = os.statvfs(str(HF_CACHE_DIR.parent))
    return (stat.f_frsize * stat.f_bavail) // (1024 * 1024)


def get_model_cache_dir(model_key):
    """Gibt den Cache-Pfad fuer ein Modell zurueck."""
    if model_key not in MODELS:
        return None

    hf_id = MODELS[model_key]["hf_id"]

    # Standard-Modelle werden von Systran gehostet
    if "/" not in hf_id and hf_id in ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo", "distil-large-v3"]:
        # faster-whisper verwendet verschiedene Repos
        possible_dirs = [
            HF_CACHE_DIR / f"models--Systran--faster-whisper-{hf_id}",
            HF_CACHE_DIR / f"models--mobiuslabsgmbh--faster-whisper-{hf_id}",
            HF_CACHE_DIR / f"models--openai--whisper-{hf_id}",
        ]
        for d in possible_dirs:
            if d.exists():
                return d
        # Default
        return HF_CACHE_DIR / f"models--Systran--faster-whisper-{hf_id}"
    else:
        return HF_CACHE_DIR / f"models--{hf_id.replace('/', '--')}"


def is_model_downloaded(model_key):
    """Prueft ob ein Modell vollstaendig heruntergeladen ist."""
    cache_dir = get_model_cache_dir(model_key)
    if not cache_dir or not cache_dir.exists():
        return False

    # Pruefe ob snapshots existieren und model.bin vorhanden ist
    snapshots_dir = cache_dir / "snapshots"
    if not snapshots_dir.exists():
        return False

    for snapshot in snapshots_dir.iterdir():
        if snapshot.is_dir():
            # Pruefe auf model.bin (CTranslate2) oder pytorch_model.bin
            model_files = list(snapshot.glob("model*.bin"))
            if model_files:
                return True

    return False


def clean_model_cache(model_key):
    """Entfernt korrupten/unvollstaendigen Cache fuer ein Modell."""
    cache_dir = get_model_cache_dir(model_key)
    if cache_dir and cache_dir.exists():
        shutil.rmtree(cache_dir)
        return True
    return False


def download_model(model_key):
    """Laedt ein Modell mit allen Pruefungen herunter."""

    # 1. Pruefe ob Modell existiert
    if model_key not in MODELS:
        return {
            "success": False,
            "error": "invalid_model",
            "message": f"Unbekanntes Modell: {model_key}. Verfuegbar: {', '.join(MODELS.keys())}"
        }

    model_info = MODELS[model_key]

    # 2. Pruefe ob bereits heruntergeladen
    if is_model_downloaded(model_key):
        return {
            "success": True,
            "message": f"Modell '{model_key}' ist bereits vollstaendig heruntergeladen.",
            "already_exists": True
        }

    # 3. Bereinige eventuelle korrupte Downloads
    cache_dir = get_model_cache_dir(model_key)
    if cache_dir and cache_dir.exists():
        print(f"Bereinige unvollstaendigen Download...", file=sys.stderr)
        clean_model_cache(model_key)

    # 4. Pruefe Internet-Verbindung
    print("Pruefe Internet-Verbindung...", file=sys.stderr)
    if not check_internet_connection():
        return {
            "success": False,
            "error": "no_internet",
            "message": "Keine Internet-Verbindung. Bitte Verbindung pruefen und erneut versuchen."
        }

    # 5. Pruefe Speicherplatz
    required_mb = model_info["size_mb"] * 2  # 2x fuer Download + Entpacken
    free_mb = get_free_disk_space_mb()
    print(f"Speicherplatz: {free_mb} MB frei, {required_mb} MB benoetigt", file=sys.stderr)

    if free_mb < required_mb:
        return {
            "success": False,
            "error": "insufficient_space",
            "message": f"Nicht genuegend Speicherplatz. Benoetigt: {required_mb} MB, Verfuegbar: {free_mb} MB"
        }

    # 6. Lade Modell herunter
    hf_id = model_info["hf_id"]
    print(f"\nLade Modell '{model_key}' herunter ({model_info['size_mb']} MB)...", file=sys.stderr)
    print(f"HuggingFace ID: {hf_id}", file=sys.stderr)
    print("Dies kann einige Minuten dauern...\n", file=sys.stderr)

    try:
        from faster_whisper import WhisperModel

        # Der WhisperModel Constructor laedt das Modell automatisch herunter
        model = WhisperModel(hf_id, device="cpu", compute_type="int8")

        # Pruefe ob Download erfolgreich
        if not is_model_downloaded(model_key):
            return {
                "success": False,
                "error": "download_incomplete",
                "message": "Download abgeschlossen, aber Modell-Dateien fehlen. Bitte erneut versuchen."
            }

        return {
            "success": True,
            "message": f"Modell '{model_key}' erfolgreich heruntergeladen!",
            "model": model_key,
            "size_mb": model_info["size_mb"]
        }

    except ImportError:
        return {
            "success": False,
            "error": "missing_dependency",
            "message": "faster-whisper nicht installiert. Bitte: pip install faster-whisper"
        }
    except Exception as e:
        error_msg = str(e)

        # Bereinige fehlerhaften Download
        clean_model_cache(model_key)

        # Spezifische Fehlermeldungen
        if "Unable to open file" in error_msg:
            return {
                "success": False,
                "error": "download_failed",
                "message": f"Download fehlgeschlagen - Modell-Dateien unvollstaendig. Cache wurde bereinigt. Bitte erneut versuchen."
            }
        elif "ConnectionError" in error_msg or "timeout" in error_msg.lower():
            return {
                "success": False,
                "error": "connection_error",
                "message": "Verbindungsfehler zum Server. Bitte spaeter erneut versuchen."
            }
        else:
            return {
                "success": False,
                "error": "download_error",
                "message": f"Download fehlgeschlagen: {error_msg}"
            }


def get_status():
    """Gibt Status aller Modelle zurueck."""
    selected = get_selected_model()
    status = {}

    for model_key, model_info in MODELS.items():
        downloaded = is_model_downloaded(model_key)
        status[model_key] = {
            "downloaded": downloaded,
            "selected": model_key == selected,
            "size_mb": model_info["size_mb"],
            "description": model_info["description"],
            "recommended": model_info.get("recommended", False)
        }

    return {
        "success": True,
        "selected_model": selected,
        "free_space_mb": get_free_disk_space_mb(),
        "internet_available": check_internet_connection(timeout=2),
        "models": status
    }


def get_selected_model():
    """Gibt aktuell ausgewaehltes Modell zurueck."""
    if SELECTED_MODEL_FILE.exists():
        return SELECTED_MODEL_FILE.read_text().strip()
    return "tiny"


def set_selected_model(model_key):
    """Setzt das ausgewaehlte Modell."""
    if model_key not in MODELS:
        return False
    if not is_model_downloaded(model_key):
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SELECTED_MODEL_FILE.write_text(model_key)
    return True


def download_all_models():
    """Laedt alle nicht-heruntergeladenen Modelle herunter."""
    results = []
    total = 0
    success = 0
    skipped = 0

    # Berechne Gesamtgroesse
    total_size_mb = sum(
        MODELS[m]["size_mb"] for m in MODELS
        if not is_model_downloaded(m) and m != "turbo"  # turbo ist Alias
    )

    print(f"\n=== Download aller STT-Modelle ===", file=sys.stderr)
    print(f"Zu laden: {total_size_mb} MB total\n", file=sys.stderr)

    for model_key in MODELS:
        # Skip turbo (ist Alias fuer distil-de)
        if model_key == "turbo":
            continue

        total += 1

        if is_model_downloaded(model_key):
            print(f"[SKIP] {model_key} - bereits vorhanden", file=sys.stderr)
            skipped += 1
            results.append({"model": model_key, "status": "skipped"})
            continue

        print(f"\n[{total}] Lade {model_key} ({MODELS[model_key]['size_mb']} MB)...", file=sys.stderr)
        result = download_model(model_key)

        if result.get("success"):
            success += 1
            results.append({"model": model_key, "status": "success"})
            print(f"    --> OK", file=sys.stderr)
        else:
            results.append({"model": model_key, "status": "failed", "error": result.get("error")})
            print(f"    --> FEHLER: {result.get('message')}", file=sys.stderr)

    return {
        "success": True,
        "message": f"Download abgeschlossen: {success} erfolgreich, {skipped} uebersprungen, {total - success - skipped} fehlgeschlagen",
        "total": total,
        "success_count": success,
        "skipped_count": skipped,
        "failed_count": total - success - skipped,
        "results": results
    }


def select_model(model_key):
    """Waehlt ein Modell aus."""
    if model_key not in MODELS:
        return {
            "success": False,
            "error": "invalid_model",
            "message": f"Unbekanntes Modell: {model_key}"
        }

    if not is_model_downloaded(model_key):
        return {
            "success": False,
            "error": "not_downloaded",
            "message": f"Modell '{model_key}' ist nicht heruntergeladen. Bitte zuerst herunterladen."
        }

    set_selected_model(model_key)
    return {
        "success": True,
        "message": f"Modell '{model_key}' ausgewaehlt.",
        "model": model_key
    }


def list_models():
    """Zeigt alle Modelle an."""
    status = get_status()
    selected = status["selected_model"]

    print("\n" + "=" * 70)
    print("STT-MODELLE - Speech-to-Text Model Manager")
    print("=" * 70)
    print(f"\nSpeicherplatz: {status['free_space_mb']} MB frei")
    print(f"Internet: {'Verfuegbar' if status['internet_available'] else 'NICHT VERFUEGBAR'}")
    print(f"Ausgewaehlt: {selected}")
    print()
    print(f"{'Modell':<12} {'Groesse':<10} {'Status':<10} {'Beschreibung'}")
    print("-" * 70)

    for model_key, info in status["models"].items():
        size_str = f"{info['size_mb']} MB"

        if info["selected"] and info["downloaded"]:
            status_str = "[AKTIV]"
        elif info["downloaded"]:
            status_str = "[OK]"
        else:
            status_str = "[-]"

        rec = " *" if info["recommended"] else ""
        print(f"{model_key:<12} {size_str:<10} {status_str:<10} {info['description']}{rec}")

    print("-" * 70)
    print("\nLegende: [AKTIV]=Ausgewaehlt, [OK]=Heruntergeladen, [-]=Nicht installiert")
    print("         * = Empfohlen")
    print("\nBefehle:")
    print("  python3 stt_model_downloader.py download distil-de  # Einzelnes Modell")
    print("  python3 stt_model_downloader.py download-all        # Alle Modelle")
    print("  python3 stt_model_downloader.py select distil-de    # Modell auswaehlen")
    print("  python3 stt_model_downloader.py clean distil-de     # Cache bereinigen")
    print("=" * 70 + "\n")


def main():
    if len(sys.argv) < 2:
        list_models()
        return

    action = sys.argv[1].lower()
    model_key = sys.argv[2] if len(sys.argv) > 2 else None

    if action == "list":
        list_models()

    elif action == "status":
        result = get_status()
        print(json.dumps(result, indent=2))

    elif action == "download":
        if not model_key:
            print(json.dumps({
                "success": False,
                "error": "missing_model",
                "message": "Bitte Modell angeben: python3 stt_model_downloader.py download distil-de"
            }))
            return
        result = download_model(model_key)
        print(json.dumps(result, indent=2))

    elif action == "download-all":
        result = download_all_models()
        print(json.dumps(result, indent=2))

    elif action == "select":
        if not model_key:
            print(json.dumps({
                "success": False,
                "error": "missing_model",
                "message": "Bitte Modell angeben"
            }))
            return
        result = select_model(model_key)
        print(json.dumps(result, indent=2))

    elif action == "clean":
        if not model_key:
            print(json.dumps({
                "success": False,
                "error": "missing_model",
                "message": "Bitte Modell angeben"
            }))
            return
        if clean_model_cache(model_key):
            print(json.dumps({
                "success": True,
                "message": f"Cache fuer '{model_key}' bereinigt."
            }))
        else:
            print(json.dumps({
                "success": True,
                "message": f"Kein Cache fuer '{model_key}' vorhanden."
            }))

    else:
        print(json.dumps({
            "success": False,
            "error": "invalid_action",
            "message": f"Unbekannte Aktion: {action}. Verfuegbar: list, status, download, download-all, select, clean"
        }))


if __name__ == "__main__":
    main()
