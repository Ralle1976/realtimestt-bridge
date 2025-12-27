#!/usr/bin/env python3
"""
STT Hotkey Daemon - Zuverlaessiger Hintergrund-Service fuer Speech-to-Text

Dieser Daemon laeuft KOMPLETT UNABHAENGIG von Claude Code und kann NICHT
durch blockierte Terminal-Eingaben beeinflusst werden.

Steuerungsmethoden (alle funktionieren auch wenn Claude busy ist):
1. File-basiert: touch /tmp/stt_start, touch /tmp/stt_stop
2. Signal-basiert: kill -SIGUSR1 <pid> (toggle), kill -SIGUSR2 <pid> (stop)
3. Hotkey (wenn evdev verfuegbar): F9 toggle

Ausgabe:
- Transkript wird nach /tmp/stt_transcript.txt geschrieben
- Status wird nach /tmp/stt_status geschrieben
- Events werden nach ~/.claude/stt_events.jsonl angehaengt

Verwendung:
  python3 stt_hotkey_daemon.py start   # Startet Daemon
  python3 stt_hotkey_daemon.py stop    # Stoppt Daemon
  python3 stt_hotkey_daemon.py status  # Zeigt Status
"""

import json
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Pfade
PID_FILE = Path("/tmp/stt_daemon.pid")
STATUS_FILE = Path("/tmp/stt_status")
TRANSCRIPT_FILE = Path("/tmp/stt_transcript.txt")
START_TRIGGER = Path("/tmp/stt_start")
STOP_TRIGGER = Path("/tmp/stt_stop")
EVENTS_FILE = Path.home() / ".claude" / "stt_events.jsonl"
LOG_FILE = Path.home() / ".claude" / "stt_hotkey.log"

# Konfiguration
MODEL = os.getenv("STT_MODEL", "distil-de")
LANGUAGE = os.getenv("STT_LANGUAGE", "de")
SAMPLE_RATE = 16000


def log(msg):
    """Thread-safe logging"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {msg}"
    print(log_msg, file=sys.stderr)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(log_msg + "\n")
    except:
        pass


def write_status(status: str, extra: dict = None):
    """Schreibt Status-Datei fuer externe Abfrage"""
    data = {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "pid": os.getpid(),
        "model": MODEL,
        **(extra or {})
    }
    STATUS_FILE.write_text(json.dumps(data))


def write_event(event_type: str, data: dict = None):
    """Schreibt Event in JSONL-Datei"""
    event = {
        "type": event_type,
        "timestamp": datetime.now().isoformat(),
        **(data or {})
    }
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")


class STTHotkeyDaemon:
    def __init__(self):
        self.recording = False
        self.running = True
        self.audio_frames = []
        self.model = None
        self.stream = None
        self._lock = threading.Lock()

    def load_model(self):
        """Laedt faster-whisper Modell (lazy)"""
        if self.model is not None:
            return True

        try:
            from faster_whisper import WhisperModel
            log(f"Lade Modell: {MODEL}...")
            write_status("loading_model")

            # Bestimme Modell-Pfad
            if MODEL.startswith("distil"):
                model_name = f"Systran/faster-{MODEL}-whisper-large-v3"
            else:
                model_name = MODEL

            self.model = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8"
            )
            log(f"Modell geladen: {MODEL}")
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

                transcript = " ".join([seg.text.strip() for seg in segments])

                if transcript:
                    log(f"Transkript: {transcript}")
                    TRANSCRIPT_FILE.write_text(transcript)
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
        """SIGUSR1 - Toggle Recording"""
        log("Signal SIGUSR1 empfangen - Toggle")
        self.toggle_recording()

    def handle_signal_stop(self, signum, frame):
        """SIGUSR2 - Force Stop Recording"""
        log("Signal SIGUSR2 empfangen - Force Stop")
        if self.recording:
            self.stop_recording()

    def handle_signal_term(self, signum, frame):
        """SIGTERM/SIGINT - Daemon beenden"""
        log("Beende Daemon...")
        self.running = False
        if self.recording:
            self.stop_recording()

    def file_watcher(self):
        """Ueberwacht Trigger-Dateien"""
        while self.running:
            try:
                if START_TRIGGER.exists():
                    START_TRIGGER.unlink()
                    log("Start-Trigger erkannt")
                    if not self.recording:
                        self.start_recording()

                if STOP_TRIGGER.exists():
                    STOP_TRIGGER.unlink()
                    log("Stop-Trigger erkannt")
                    if self.recording:
                        self.stop_recording()

            except Exception as e:
                log(f"File-Watcher Error: {e}")

            time.sleep(0.1)  # 100ms Poll-Intervall

    def hotkey_listener(self):
        """Optionaler evdev-basierter Hotkey-Listener"""
        try:
            import evdev
            from evdev import InputDevice, categorize, ecodes

            # Finde Tastatur
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
            keyboard = None
            for dev in devices:
                if "keyboard" in dev.name.lower() or "kbd" in dev.name.lower():
                    keyboard = dev
                    break

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

    def run(self):
        """Hauptschleife"""
        # PID speichern
        PID_FILE.write_text(str(os.getpid()))

        # Signal-Handler
        signal.signal(signal.SIGUSR1, self.handle_signal_toggle)
        signal.signal(signal.SIGUSR2, self.handle_signal_stop)
        signal.signal(signal.SIGTERM, self.handle_signal_term)
        signal.signal(signal.SIGINT, self.handle_signal_term)

        log(f"STT Hotkey Daemon gestartet (PID: {os.getpid()})")
        log(f"Modell: {MODEL}, Sprache: {LANGUAGE}")
        log("Steuerung:")
        log("  - File: touch /tmp/stt_start, touch /tmp/stt_stop")
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
                time.sleep(0.5)
        finally:
            # Cleanup
            if PID_FILE.exists():
                PID_FILE.unlink()
            write_status("stopped")
            log("Daemon beendet")


def get_status():
    """Liest aktuellen Status"""
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except:
            pass
    return {"status": "not_running"}


def is_running():
    """Prueft ob Daemon laeuft"""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)  # Prueft ob Prozess existiert
            return pid
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink()
    return None


def main():
    if len(sys.argv) < 2:
        print("""
STT Hotkey Daemon - Zuverlaessiger Speech-to-Text Service

Verwendung:
  python3 stt_hotkey_daemon.py start   # Startet Daemon im Hintergrund
  python3 stt_hotkey_daemon.py stop    # Stoppt Daemon
  python3 stt_hotkey_daemon.py status  # Zeigt Status
  python3 stt_hotkey_daemon.py run     # Startet im Vordergrund (Debug)

Steuerung waehrend Daemon laeuft:
  touch /tmp/stt_start    # Aufnahme starten
  touch /tmp/stt_stop     # Aufnahme stoppen
  kill -SIGUSR1 <pid>     # Toggle Start/Stop
  kill -SIGUSR2 <pid>     # Force Stop

Transkript wird nach /tmp/stt_transcript.txt geschrieben.
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

        # Fork in Hintergrund
        if os.fork() > 0:
            time.sleep(0.5)  # Kurz warten bis Daemon gestartet
            pid = is_running()
            print(json.dumps({
                "success": True,
                "message": "STT Hotkey Daemon gestartet",
                "pid": pid,
                "controls": {
                    "start": "touch /tmp/stt_start",
                    "stop": "touch /tmp/stt_stop",
                    "toggle": f"kill -SIGUSR1 {pid}",
                    "hotkey": "F9 (falls evdev verfuegbar)"
                }
            }))
            return

        # Daemon-Prozess
        os.setsid()
        daemon = STTHotkeyDaemon()
        daemon.run()

    elif action == "stop":
        pid = is_running()
        if not pid:
            print(json.dumps({
                "success": False,
                "message": "Daemon laeuft nicht"
            }))
            return

        os.kill(pid, signal.SIGTERM)
        time.sleep(0.3)
        print(json.dumps({
            "success": True,
            "message": f"Daemon gestoppt (PID: {pid})"
        }))

    elif action == "status":
        pid = is_running()
        status = get_status()
        status["running"] = pid is not None
        if pid:
            status["pid"] = pid
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
