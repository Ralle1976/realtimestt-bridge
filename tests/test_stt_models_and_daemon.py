"""100% offline mocked tests for stt_models, stt_model_downloader, and stt_hotkey_daemon."""

import json
import os
import sys
import types
from pathlib import Path

import pytest

import stt_hotkey_daemon
import stt_model_downloader
import stt_models


class TestSttModels:
    def test_selected_model_roundtrip_and_corrupt_fallback(self, monkeypatch, tmp_path):
        cfg = tmp_path / "cfg"
        sel_file = cfg / "selected_model"
        monkeypatch.setattr(stt_models, "CONFIG_DIR", cfg)
        monkeypatch.setattr(stt_models, "SELECTED_MODEL_FILE", sel_file)

        assert stt_models.get_selected_model() == "tiny"
        assert stt_models.set_selected_model("distil-de") is True
        assert stt_models.get_selected_model() == "distil-de"

        # Corrupt / unknown content falls back cleanly
        sel_file.write_text("../../../evil_model", encoding="utf-8")
        assert stt_models.get_selected_model() == "tiny"

    def test_lifecycle_select_and_remove_model(self, monkeypatch, tmp_path):
        cache = tmp_path / "hf_hub"
        cfg = tmp_path / "cfg"
        monkeypatch.setattr(stt_models, "HF_CACHE_DIR", cache)
        monkeypatch.setattr(stt_models, "CONFIG_DIR", cfg)
        monkeypatch.setattr(stt_models, "SELECTED_MODEL_FILE", cfg / "selected_model")

        # Create fake downloaded distil-de snapshot
        snap = cache / "models--primeline--whisper-large-v3-turbo-german" / "snapshots" / "rev1"
        snap.mkdir(parents=True)
        (snap / "model.bin").write_bytes(b"fake")

        assert stt_models.is_model_downloaded("distil-de") is True
        assert stt_models.is_model_downloaded("tiny") is False

        sel = stt_models.select_model("distil-de")
        assert sel["success"] is True
        assert stt_models.get_selected_model() == "distil-de"

        rem = stt_models.remove_model("distil-de")
        assert rem["success"] is True
        assert not (cache / "models--primeline--whisper-large-v3-turbo-german").exists()
        assert stt_models.get_selected_model() == "tiny"

    def test_main_handles_non_dict_and_unhashable_model(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(stt_models, "HF_CACHE_DIR", tmp_path / "hub")
        monkeypatch.setattr(stt_models, "CONFIG_DIR", tmp_path / "cfg")
        monkeypatch.setattr(stt_models, "SELECTED_MODEL_FILE", tmp_path / "cfg" / "selected_model")

        # Non-dict JSON list should not raise AttributeError
        monkeypatch.setattr(sys, "argv", ["stt_models.py", '["not", "a", "dict"]'])
        stt_models.main()
        assert "STT-MODELLE" in capsys.readouterr().out

        # Unhashable list model must not raise TypeError
        monkeypatch.setattr(sys, "argv", ["stt_models.py", '{"action": "select", "model": ["x"]}'])
        stt_models.main()
        out = json.loads(capsys.readouterr().out)
        assert out["success"] is False and out["error"] == "missing_model"


class TestSttModelDownloader:
    def test_get_free_disk_space_mb_cross_platform_nonexistent_cache(self, monkeypatch, tmp_path):
        nested = tmp_path / "does" / "not" / "exist" / "yet"
        monkeypatch.setattr(stt_model_downloader, "HF_CACHE_DIR", nested)
        free_mb = stt_model_downloader.get_free_disk_space_mb()
        assert isinstance(free_mb, int)
        assert free_mb >= 0

    def test_check_internet_connection_closes_socket(self, monkeypatch):
        closed = {"exited": False}

        class FakeSocket:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                closed["exited"] = True
                return False

        monkeypatch.setattr(
            stt_model_downloader.socket,
            "create_connection",
            lambda addr, timeout=5: FakeSocket(),
        )
        assert stt_model_downloader.check_internet_connection(timeout=1) is True
        assert closed["exited"] is True

        def fail_connect(addr, timeout=5):
            raise OSError("offline")

        monkeypatch.setattr(stt_model_downloader.socket, "create_connection", fail_connect)
        assert stt_model_downloader.check_internet_connection(timeout=1) is False

    def test_download_model_offline_guards_and_success(self, monkeypatch, tmp_path):
        cache = tmp_path / "hub"
        monkeypatch.setattr(stt_model_downloader, "HF_CACHE_DIR", cache)

        assert stt_model_downloader.download_model("unknown")["error"] == "invalid_model"

        # No internet
        monkeypatch.setattr(stt_model_downloader, "check_internet_connection", lambda timeout=5: False)
        assert stt_model_downloader.download_model("tiny")["error"] == "no_internet"

        # Insufficient disk space
        monkeypatch.setattr(stt_model_downloader, "check_internet_connection", lambda timeout=5: True)
        monkeypatch.setattr(stt_model_downloader, "get_free_disk_space_mb", lambda: 10)
        assert stt_model_downloader.download_model("tiny")["error"] == "insufficient_space"

        # Successful mocked download creates model.bin
        monkeypatch.setattr(stt_model_downloader, "get_free_disk_space_mb", lambda: 10000)

        class FakeWhisperModel:
            def __init__(self, hf_id, device=None, compute_type=None):
                snap = cache / f"models--Systran--faster-whisper-{hf_id}" / "snapshots" / "abc"
                snap.mkdir(parents=True, exist_ok=True)
                (snap / "model.bin").write_bytes(b"weights")

        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = FakeWhisperModel
        monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)

        res = stt_model_downloader.download_model("tiny")
        assert res["success"] is True
        assert stt_model_downloader.is_model_downloaded("tiny") is True

    def test_clean_cli_rejects_unknown_model(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["stt_model_downloader.py", "clean", "nope"])
        stt_model_downloader.main()
        out = json.loads(capsys.readouterr().out)
        assert out["success"] is False and out["error"] == "invalid_model"


class TestSttHotkeyDaemon:
    def _isolate_daemon_paths(self, monkeypatch, tmp_path):
        rt = tmp_path / "rt"
        rt.mkdir()
        monkeypatch.setattr(stt_hotkey_daemon, "RUNTIME_DIR", rt)
        monkeypatch.setattr(stt_hotkey_daemon, "PID_FILE", rt / "stt_daemon.pid")
        monkeypatch.setattr(stt_hotkey_daemon, "STATUS_FILE", rt / "stt_status")
        monkeypatch.setattr(stt_hotkey_daemon, "TRANSCRIPT_FILE", rt / "stt_transcript.txt")
        monkeypatch.setattr(stt_hotkey_daemon, "START_TRIGGER", rt / "stt_start")
        monkeypatch.setattr(stt_hotkey_daemon, "STOP_TRIGGER", rt / "stt_stop")
        monkeypatch.setattr(stt_hotkey_daemon, "EVENTS_FILE", tmp_path / "events.jsonl")
        monkeypatch.setattr(stt_hotkey_daemon, "LOG_FILE", tmp_path / "hotkey.log")
        return rt

    def test_load_model_maps_distil_de_correctly(self, monkeypatch, tmp_path):
        self._isolate_daemon_paths(monkeypatch, tmp_path)
        monkeypatch.setattr(stt_hotkey_daemon, "MODEL", "distil-de")

        loaded = []

        class FakeWhisperModel:
            def __init__(self, model_name, device=None, compute_type=None):
                loaded.append(model_name)

        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = FakeWhisperModel
        monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)

        daemon = stt_hotkey_daemon.STTHotkeyDaemon()
        assert daemon.load_model() is True
        assert loaded == ["large-v3-turbo"]

    def test_is_running_rejects_dangerous_pids_and_cleans_stale(self, monkeypatch, tmp_path):
        rt = self._isolate_daemon_paths(monkeypatch, tmp_path)
        pid_file = rt / "stt_daemon.pid"

        for bad in ["-1", "0", "not_a_pid", "99999999"]:
            pid_file.write_text(bad, encoding="utf-8")
            assert stt_hotkey_daemon.is_running() is None
            assert not pid_file.exists()

        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        assert stt_hotkey_daemon.is_running() == os.getpid()

    def test_signal_handlers_are_lock_free_and_drain_safely(self, monkeypatch, tmp_path):
        self._isolate_daemon_paths(monkeypatch, tmp_path)
        daemon = stt_hotkey_daemon.STTHotkeyDaemon()
        actions = []
        monkeypatch.setattr(daemon, "toggle_recording", lambda: actions.append("toggle"))
        monkeypatch.setattr(daemon, "stop_recording", lambda: actions.append("stop"))

        # Even while _lock is held, signal handlers must NOT deadlock!
        with daemon._lock:
            daemon.handle_signal_toggle(None, None)
            daemon.handle_signal_stop(None, None)
            daemon.handle_signal_term(None, None)

        assert daemon.running is False
        daemon.recording = True
        daemon._drain_signals()
        assert actions == ["toggle", "stop", "stop"]

    def test_recording_and_transcription_roundtrip_utf8(self, monkeypatch, tmp_path):
        rt = self._isolate_daemon_paths(monkeypatch, tmp_path)

        class FakeInputStream:
            def __init__(self, samplerate, channels, dtype, callback):
                self.callback = callback
                self.stopped = False
                self.closed = False

            def start(self):
                # Push synthetic audio frame
                self.callback([0.1, 0.2], 2, None, None)

            def stop(self):
                self.stopped = True

            def close(self):
                self.closed = True

        fake_sd = types.ModuleType("sounddevice")
        fake_sd.InputStream = FakeInputStream
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

        class FakeArray(list):
            def flatten(self):
                return self

        fake_np = types.ModuleType("numpy")
        fake_np.concatenate = lambda frames, axis=0: FakeArray([x for f in frames for x in f])
        monkeypatch.setitem(sys.modules, "numpy", fake_np)

        class FakeModel:
            def transcribe(self, audio, language=None, beam_size=5, vad_filter=True):
                return [types.SimpleNamespace(text=" Grüße aus München ")], types.SimpleNamespace(language="de")

        daemon = stt_hotkey_daemon.STTHotkeyDaemon()
        daemon.model = FakeModel()
        daemon.start_recording()
        assert daemon.recording is True

        daemon.stop_recording()
        assert daemon.recording is False
        assert (rt / "stt_transcript.txt").read_text(encoding="utf-8") == "Grüße aus München"
        status = json.loads((rt / "stt_status").read_text(encoding="utf-8"))
        assert status["status"] == "ready"
        assert status["last_transcript"] == "Grüße aus München"

    def test_hotkey_listener_closes_all_evdev_handles(self, monkeypatch, tmp_path):
        self._isolate_daemon_paths(monkeypatch, tmp_path)
        closed_devices = []

        class FakeDevice:
            def __init__(self, path):
                self.path = path
                self.name = "USB Mouse" if path == "/dev/input/event0" else "USB Keyboard"

            def read_loop(self):
                return iter([])

            def close(self):
                closed_devices.append(self.path)

        fake_evdev = types.ModuleType("evdev")
        fake_evdev.InputDevice = FakeDevice
        fake_evdev.list_devices = lambda: ["/dev/input/event0", "/dev/input/event1"]
        fake_evdev.categorize = lambda e: e
        fake_evdev.ecodes = types.SimpleNamespace(EV_KEY=1)
        monkeypatch.setitem(sys.modules, "evdev", fake_evdev)

        daemon = stt_hotkey_daemon.STTHotkeyDaemon()
        daemon.hotkey_listener()
        assert closed_devices == ["/dev/input/event0", "/dev/input/event1"]

    def test_cli_status_and_stop_when_not_running(self, monkeypatch, capsys, tmp_path):
        self._isolate_daemon_paths(monkeypatch, tmp_path)

        monkeypatch.setattr(sys, "argv", ["stt_hotkey_daemon.py", "status"])
        stt_hotkey_daemon.main()
        st = json.loads(capsys.readouterr().out)
        assert st["running"] is False and st["status"] == "not_running"

        monkeypatch.setattr(sys, "argv", ["stt_hotkey_daemon.py", "stop"])
        stt_hotkey_daemon.main()
        stopped = json.loads(capsys.readouterr().out)
        assert stopped["success"] is False
