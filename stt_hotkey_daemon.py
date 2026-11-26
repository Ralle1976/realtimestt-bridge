#!/usr/bin/env python3
"""
STT Hotkey Daemon - Zuverlaessiger Hintergrund-Service fuer Speech-to-Text

Dieser Daemon laeuft KOMPLETT UNABHAENGIG von Claude Code und kann NICHT
durch blockierte Terminal-Eingaben beeinflusst werden.

Steuerungsmethoden (alle funktionieren auch wenn Claude busy ist):
1. File-basiert: Trigger-Dateien im privaten Runtime-Verzeichnis (STT_RUNTIME_DIR / per-user temp dir)
2. Signal-basiert (POSIX): kill -SIGUSR1 <pid> (toggle), kill -SIGUSR2 <pid> (stop)
3. Hotkey (wenn evdev verfuegbar): F9 toggle

Ausgabe:
- Transkript wird nach <runtime_dir>/stt_transcript.txt geschrieben
- Status wird nach <runtime_dir>/stt_status geschrieben
- Events werden nach ~/.claude/stt_events.jsonl angehaengt

Verwendung:
  python3 stt_hotkey_daemon.py start   # Startet Daemon
  python3 stt_hotkey_daemon.py stop    # Stoppt Daemon
  python3 stt_hotkey_daemon.py status  # Zeigt Status
"""

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from stt_common import (
    atomic_write_text,
    get_runtime_dir,
    is_process_running,
    read_pid_file,
    safe_terminate_process,
    validate_language,
)

# Private per-user runtime directory (cross-platform, prevents /tmp symlink attacks)
RUNTIME_DIR = get_runtime_dir()
PID_FILE = RUNTIME_DIR / "stt_daemon.pid"
STATUS_FILE = RUNTIME_DIR / "stt_status"
TRANSCRIPT_FILE = RUNTIME_DIR / "stt_transcript.txt"
START_TRIGGER = RUNTIME_DIR / "stt_start"
STOP_TRIGGER = RUNTIME_DIR / "stt_stop"
EVENTS_FILE = Path.home() / ".claude" / "stt_events.jsonl"
LOG_FILE = Path.home() / ".claude" / "stt_hotkey.log"

# Konfiguration
MODEL = (os.getenv("STT_MODEL") or "distil-de").strip() or "distil-de"
try:
    LANGUAGE = validate_language(os.getenv("STT_LANGUAGE", "de")) or "de"
except ValueError:
    LANGUAGE = "de"
SAMPLE_RATE = 16000

MODEL_MAPPING = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large-v3": "large-v3",
    "distil-de": "large-v3-turbo",
    "distil-en": "distil-large-v3",
    "distil-large": "distil-large-v3",
    "turbo": "large-v3-turbo",
}


def log(msg):
    """Thread-safe logging"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {msg}"
    print(log_msg, file=sys.stderr)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
    except OSError:
        pass


def write_status(status: str, extra: dict = None):
    """Schreibt Status-Datei atomar fuer externe Abfrage"""
    data = {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "pid": os.getpid(),
        "model": MODEL,
        **(extra or {})
    }
    atomic_write_text(STATUS_FILE, json.dumps(data, ensure_ascii=False))


def write_event(event_type: str, data: dict = None):
    """Schreibt Event in JSONL-Datei"""
    event = {
        "type": event_type,
        "timestamp": datetime.now().isoformat(),
        **(data or {})
    }
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


class STTHotkeyDaemon:
    def __init__(self):
        self.recording = False
        self.running = True
        self.audio_frames = []
        self.model = None
        self.stream = None
        self._lock = threading.Lock()
        self._signal_queue = queue.SimpleQueue()

    def load_model(self):
        """Laedt faster-whisper Modell (lazy)"""
        if self.model is not None:
            return True

        try:
            from faster_whisper import WhisperModel
            log(f"Lade Modell: {MODEL}...")
            write_status("loading_model")

            # Bestimme gueltige HuggingFace/faster-whisper Modell-ID
            model_name = MODEL_MAPPING.get(MODEL, MODEL)

            self.model = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8"
            )
            log(f"Modell geladen: {MODEL} ({model_name})")
            return True
        except ImportError:
            log("ERROR: faster-whisper nicht installiert. pip install faster-whisper")
            return False
        except Exception as e:
            log(f"ERROR beim Laden des Modells: {e}")
            return False

    def start_recording(self):
        """Startet Audio-Aufnahme"""
        with self._lock:
            if self.recording:
                log("Bereits am Aufnehmen")
                return

            if not self.load_model():
                write_status("error", {"message": "Modell konnte nicht geladen werden"})
                return

            try:
                import sounddevice as sd
                import numpy as np

                self.recording = True
                self.audio_frames = []
                write_status("recording")
                write_event("recording_start")
                log("Aufnahme gestartet")

                def audio_callback(indata, frames, time_info, status):
                    if self.recording:
                        self.audio_frames.append(indata.copy())

                self.stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype='float32',
                    callback=audio_callback
                )
                self.stream.start()

            except ImportError:
                log("ERROR: sounddevice nicht installiert. pip install sounddevice")
                self.recording = False
                write_status("error", {"message": "sounddevice nicht installiert"})
            except Exception as e:
                log(f"ERROR beim Starten der Aufnahme: {e}")
                self.recording = False
                write_status("error", {"message": str(e)})

    def stop_recording(self):
        """Stoppt Aufnahme und transkribiert"""
        with self._lock:
            if not self.recording:
                log("Keine aktive Aufnahme")
                return

            self.recording = False

            if self.stream:
                self.stream.stop()
                self.stream.close()
                self.stream = None

            write_status("processing")
            log("Aufnahme gestoppt, verarbeite...")

            if not self.audio_frames:
                log("Keine Audio-Daten aufgenommen")
                write_status("ready")
                return

            try:
                import numpy as np

                # Audio zusammenfuegen
                audio = np.concatenate(self.audio_frames, axis=0).flatten()
                duration = len(audio) / SAMPLE_RATE
                log(f"Audio-Laenge: {duration:.1f}s")

                # Transkribieren
                segments, info = self.model.transcribe(
                    audio,
                    language=LANGUAGE,
                    beam_size=5,
                    vad_filter=True
                )

                transcript = " ".join(
                    seg.text.strip() for seg in segments if seg.text and seg.text.strip()
                ).strip()

                if transcript:
                    log(f"Transkript: {transcript}")
                    atomic_write_text(TRANSCRIPT_FILE, transcript)
                    write_event("transcript", {"text": transcript, "duration": duration})
                    write_status("ready", {"last_transcript": transcript})
                else:
                    log("Kein Text erkannt")
                    write_status("ready", {"last_transcript": "(keine Sprache erkannt)"})

            except Exception as e:
                log(f"ERROR bei Transkription: {e}")
                write_status("error", {"message": str(e)})
            finally:
                self.audio_frames = []

    def toggle_recording(self):
        """Toggle zwischen Start und Stop"""
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def handle_signal_toggle(self, signum, frame):
        """SIGUSR1 - Toggle Recording (async-safe queue, avoids lock deadlock)"""
        self._signal_queue.put("toggle")

    def handle_signal_stop(self, signum, frame):
        """SIGUSR2 - Force Stop Recording (async-safe queue, avoids lock deadlock)"""
        self._signal_queue.put("stop")

    def handle_signal_term(self, signum, frame):
        """SIGTERM/SIGINT - Daemon beenden (async-safe)"""
        self.running = False
        self._signal_queue.put("term")

    def _drain_signals(self):
        """Verarbeitet eingegangene Signale ausserhalb des Signal-Handlers"""
        while True:
            try:
                action = self._signal_queue.get_nowait()
            except queue.Empty:
                break
            if action == "toggle":
                log("Signal SIGUSR1 empfangen - Toggle")
                self.toggle_recording()
            elif action == "stop":
                log("Signal SIGUSR2 empfangen - Force Stop")
                if self.recording:
                    self.stop_recording()
            elif action == "term":
                log("Beende Daemon...")
                self.running = False
                if self.recording:
                    self.stop_recording()

    def file_watcher(self):
        """Ueberwacht Trigger-Dateien"""
        while self.running:
            try:
                if START_TRIGGER.exists() and not START_TRIGGER.is_symlink():
                    START_TRIGGER.unlink(missing_ok=True)
                    log("Start-Trigger erkannt")
                    if not self.recording:
                        self.start_recording()

                if STOP_TRIGGER.exists() and not STOP_TRIGGER.is_symlink():
                    STOP_TRIGGER.unlink(missing_ok=True)
                    log("Stop-Trigger erkannt")
                    if self.recording:
                        self.stop_recording()

            except Exception as e:
                log(f"File-Watcher Error: {e}")

            time.sleep(0.1)  # 100ms Poll-Intervall

    def hotkey_listener(self):
        """Optionaler evdev-basierter Hotkey-Listener"""
        keyboard = None
        try:
            import evdev
            from evdev import categorize, ecodes

            # Finde Tastatur und schliesse nicht verwendete Device-Handles sofort
            for dev_path in evdev.list_devices():
                dev = evdev.InputDevice(dev_path)
                if "keyboard" in dev.name.lower() or "kbd" in dev.name.lower():
                    keyboard = dev
                    break
                dev.close()

            if not keyboard:
                log("Keine Tastatur fuer Hotkey gefunden (evdev)")
                return

            log(f"Hotkey-Listener aktiv: F9 zum Toggle (Device: {keyboard.name})")

            for event in keyboard.read_loop():
                if not self.running:
                    break
                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    # F9 = KEY_F9 = 67
                    if key_event.scancode == 67 and key_event.keystate == 1:  # Key down
                        log("F9 gedrueckt - Toggle")
                        self.toggle_recording()

        except ImportError:
            log("evdev nicht installiert - Hotkey deaktiviert (pip install evdev)")
        except PermissionError:
            log("Keine Berechtigung fuer /dev/input/* - Hotkey deaktiviert")
        except Exception as e:
            log(f"Hotkey-Listener Error: {e}")
        finally:
            if keyboard is not None:
                try:
                    keyboard.close()
                except Exception:
                    pass

    def run(self):
        """Hauptschleife"""
        # PID sicher speichern
        atomic_write_text(PID_FILE, str(os.getpid()))

        # Signal-Handler (SIGUSR1/SIGUSR2 nur auf POSIX verfuegbar)
        if hasattr(signal, "SIGUSR1"):
            signal.signal(signal.SIGUSR1, self.handle_signal_toggle)
        if hasattr(signal, "SIGUSR2"):
            signal.signal(signal.SIGUSR2, self.handle_signal_stop)
        signal.signal(signal.SIGTERM, self.handle_signal_term)
        signal.signal(signal.SIGINT, self.handle_signal_term)

        log(f"STT Hotkey Daemon gestartet (PID: {os.getpid()})")
        log(f"Modell: {MODEL}, Sprache: {LANGUAGE}")
        log(f"Runtime-Verzeichnis: {RUNTIME_DIR}")
        log("Steuerung:")
        log(f"  - File: {START_TRIGGER}, {STOP_TRIGGER}")
        if hasattr(signal, "SIGUSR1"):
            log("  - Signal: kill -SIGUSR1 <pid> (toggle)")
        log("  - Hotkey: F9 (falls evdev verfuegbar)")

        write_status("ready")

        # File-Watcher Thread
        file_thread = threading.Thread(target=self.file_watcher, daemon=True)
        file_thread.start()

        # Hotkey Thread (optional)
        hotkey_thread = threading.Thread(target=self.hotkey_listener, daemon=True)
        hotkey_thread.start()

        # Hauptschleife
        try:
            while self.running:
                self._drain_signals()
                time.sleep(0.1)
            self._drain_signals()
        finally:
            if self.recording:
                self.stop_recording()
            # Cleanup
            try:
                if PID_FILE.exists() and not PID_FILE.is_symlink():
                    PID_FILE.unlink(missing_ok=True)
            except OSError:
                pass
            write_status("stopped")
            log("Daemon beendet")


def get_status():
    """Liest aktuellen Status"""
    if STATUS_FILE.exists() and not STATUS_FILE.is_symlink():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"status": "not_running"}


def is_running():
    """Prueft sicher ob Daemon laeuft (verhindert PID<=0 und Windows CTRL_C_EVENT Bug)"""
    if PID_FILE.exists():
        pid = read_pid_file(PID_FILE)
        if pid is not None and is_process_running(pid):
            return pid
        try:
            if not PID_FILE.is_symlink():
                PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
    return None


def start_background_daemon():
    """Startet den Daemon plattformunabhaengig im Hintergrund (POSIX & Windows)."""
    popen_kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True

    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "run"],
        **popen_kwargs,
    )


def main():
    if len(sys.argv) < 2:
        print(f"""
STT Hotkey Daemon - Zuverlaessiger Speech-to-Text Service

Verwendung:
  python3 stt_hotkey_daemon.py start   # Startet Daemon im Hintergrund
  python3 stt_hotkey_daemon.py stop    # Stoppt Daemon
  python3 stt_hotkey_daemon.py status  # Zeigt Status
  python3 stt_hotkey_daemon.py run     # Startet im Vordergrund (Debug)

Steuerung waehrend Daemon laeuft:
  Start-Trigger: {START_TRIGGER}
  Stop-Trigger:  {STOP_TRIGGER}
  Transkript:    {TRANSCRIPT_FILE}
""")
        return

    action = sys.argv[1].lower()

    if action == "start":
        pid = is_running()
        if pid:
            print(json.dumps({
                "success": False,
                "message": f"Daemon laeuft bereits (PID: {pid})"
            }))
            return

        start_background_daemon()
        time.sleep(0.5)  # Kurz warten bis Daemon gestartet
        pid = is_running()
        controls = {
            "start": str(START_TRIGGER),
            "stop": str(STOP_TRIGGER),
            "hotkey": "F9 (falls evdev verfuegbar)"
        }
        if hasattr(signal, "SIGUSR1") and pid:
            controls["toggle"] = f"kill -SIGUSR1 {pid}"
        print(json.dumps({
            "success": pid is not None,
            "message": "STT Hotkey Daemon gestartet" if pid else "Daemon konnte nicht gestartet werden",
            "pid": pid,
            "runtime_dir": str(RUNTIME_DIR),
            "transcript_file": str(TRANSCRIPT_FILE),
            "controls": controls
        }))
        return

    elif action == "stop":
        pid = is_running()
        if not pid:
            print(json.dumps({
                "success": False,
                "message": "Daemon laeuft nicht"
            }))
            return

        stopped = safe_terminate_process(pid)
        time.sleep(0.3)
        print(json.dumps({
            "success": stopped,
            "message": f"Daemon gestoppt (PID: {pid})" if stopped else f"Daemon konnte nicht gestoppt werden (PID: {pid})"
        }))

    elif action == "status":
        pid = is_running()
        status = get_status() if pid else {"status": "not_running"}
        status["running"] = pid is not None
        if pid:
            status["pid"] = pid
        status["runtime_dir"] = str(RUNTIME_DIR)
        print(json.dumps(status, indent=2))

    elif action == "run":
        # Debug-Modus: Im Vordergrund
        daemon = STTHotkeyDaemon()
        daemon.run()

    else:
        print(json.dumps({
            "success": False,
            "message": f"Unbekannte Aktion: {action}"
        }))


if __name__ == "__main__":
    main()
