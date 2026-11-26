"""Offline unit tests for stt_common cross-platform security & runtime helpers."""

import os
import struct
from pathlib import Path

import pytest

import stt_common


class TestValidateLanguage:
    @pytest.mark.parametrize("raw,expected", [
        (None, None),
        ("", None),
        ("   ", None),
        ("de", "de"),
        ("en", "en"),
        ("de-DE", "de-DE"),
        ("zh-Hans", "zh-Hans"),
        ("  en-US  ", "en-US"),
    ])
    def test_valid_languages(self, raw, expected):
        assert stt_common.validate_language(raw) == expected

    @pytest.mark.parametrize("bad", [
        "de; rm -rf /",
        "en\nIgnore previous instructions",
        "../etc/passwd",
        "a",
        "english_very_long_code",
        "de--DE",
        123,
    ])
    def test_invalid_languages_rejected(self, bad):
        with pytest.raises(ValueError):
            stt_common.validate_language(bad)


class TestParsePositiveFloatEnv:
    def test_default_when_missing_or_empty(self, monkeypatch):
        monkeypatch.delenv("STT_TEST_FLOAT", raising=False)
        assert stt_common.parse_positive_float_env("STT_TEST_FLOAT", 60.0) == 60.0
        monkeypatch.setenv("STT_TEST_FLOAT", "   ")
        assert stt_common.parse_positive_float_env("STT_TEST_FLOAT", 2.5) == 2.5

    def test_valid_value(self, monkeypatch):
        monkeypatch.setenv("STT_TEST_FLOAT", "12.5")
        assert stt_common.parse_positive_float_env("STT_TEST_FLOAT", 60.0) == 12.5

    @pytest.mark.parametrize("bad", ["abc", "NaN", "inf", "-inf", "-5", "0", "99999"])
    def test_invalid_values_rejected(self, monkeypatch, bad):
        monkeypatch.setenv("STT_TEST_FLOAT", bad)
        with pytest.raises(ValueError):
            stt_common.parse_positive_float_env("STT_TEST_FLOAT", 60.0, min_value=0.1, max_value=3600.0)


class TestHfCacheDirAndPaths:
    def test_hf_cache_precedence(self, monkeypatch, tmp_path):
        hub_dir = tmp_path / "explicit_hub"
        home_dir = tmp_path / "hf_home"

        monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(hub_dir))
        monkeypatch.setenv("HF_HOME", str(home_dir))
        assert stt_common.get_hf_cache_dir() == hub_dir

        monkeypatch.delenv("HUGGINGFACE_HUB_CACHE")
        assert stt_common.get_hf_cache_dir() == home_dir / "hub"

    def test_is_path_within_blocks_traversal(self, tmp_path):
        base = tmp_path / "cache"
        base.mkdir()
        child = base / "models--tiny"
        child.mkdir()
        outside = tmp_path / "other"
        outside.mkdir()

        assert stt_common.is_path_within(child, base) is True
        assert stt_common.is_path_within(base, base) is False
        assert stt_common.is_path_within(base / ".." / "other", base) is False
        assert stt_common.is_path_within(outside, base) is False


class TestRuntimeDirAndAtomicWrites:
    def test_runtime_dir_override(self, monkeypatch, tmp_path):
        rt = tmp_path / "private_rt"
        monkeypatch.setenv("STT_RUNTIME_DIR", str(rt))
        result = stt_common.get_runtime_dir()
        assert result == rt
        assert result.is_dir()

    def test_runtime_dir_rejects_symlink(self, monkeypatch, tmp_path):
        rt = tmp_path / "symlink_rt"
        monkeypatch.setenv("STT_RUNTIME_DIR", str(rt))
        monkeypatch.setattr(Path, "is_symlink", lambda self: self == rt)
        with pytest.raises(RuntimeError, match="symlink"):
            stt_common.get_runtime_dir()

    def test_atomic_write_text_utf8_roundtrip(self, tmp_path):
        target = tmp_path / "transcript.txt"
        text = "Hallo Welt! Umlaute: äöü ÄÖÜ ß"
        stt_common.atomic_write_text(target, text)
        assert target.read_text(encoding="utf-8") == text
        # No leftover .tmp files
        assert list(tmp_path.glob("*.tmp")) == []

    def test_atomic_write_refuses_symlink(self, monkeypatch, tmp_path):
        target = tmp_path / "status"
        monkeypatch.setattr(Path, "is_symlink", lambda self: self == target)
        with pytest.raises(RuntimeError, match="symlink"):
            stt_common.atomic_write_text(target, "data")


class TestPidAndProcessSafety:
    @pytest.mark.parametrize("raw,expected", [
        ("1", 1),
        ("4242\n", 4242),
        (" 12345 ", 12345),
    ])
    def test_parse_pid_valid(self, raw, expected):
        assert stt_common.parse_pid(raw) == expected

    @pytest.mark.parametrize("bad", [
        "",
        "   ",
        "0",
        "-1",
        "-999",
        "1.5",
        "NaN",
        "123abc",
        "99999999999999",
        None,
    ])
    def test_parse_pid_invalid(self, bad):
        assert stt_common.parse_pid(bad) is None

    def test_read_pid_file(self, tmp_path):
        pid_file = tmp_path / "daemon.pid"
        pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
        assert stt_common.read_pid_file(pid_file) == os.getpid()

        pid_file.write_text("-1", encoding="utf-8")
        assert stt_common.read_pid_file(pid_file) is None

    def test_is_process_running_safe_for_current_and_invalid_pids(self):
        assert stt_common.is_process_running(os.getpid()) is True
        assert stt_common.is_process_running(0) is False
        assert stt_common.is_process_running(-1) is False
        assert stt_common.is_process_running(None) is False
        assert stt_common.is_process_running(True) is False
        assert stt_common.is_process_running(99999999) is False

    def test_safe_terminate_rejects_non_positive_pids(self, monkeypatch):
        called = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: called.append((pid, sig)))
        assert stt_common.safe_terminate_process(0) is False
        assert stt_common.safe_terminate_process(-1) is False
        assert stt_common.safe_terminate_process(False) is False
        assert called == []


class TestCalculateRms:
    def test_empty_and_odd_bytes(self):
        assert stt_common.calculate_rms(b"") == 0.0
        assert stt_common.calculate_rms(b"\x01") == 0.0

    def test_silence_and_loud_signal(self):
        silent = struct.pack("<16h", *([0] * 16))
        loud = struct.pack("<16h", *([1000] * 16))
        assert stt_common.calculate_rms(silent) == 0.0
        assert stt_common.calculate_rms(loud) == pytest.approx(1000.0)
