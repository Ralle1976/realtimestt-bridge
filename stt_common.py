#!/usr/bin/env python3
"""
Shared cross-platform security, validation, and runtime helpers for realtimestt-bridge.

Zero external dependencies (Python standard library only).
"""

import ctypes
import getpass
import math
import os
import re
import signal
import struct
import sys
import tempfile
from pathlib import Path
from typing import Optional

LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
PID_PATTERN = re.compile(r"^[1-9]\d*$")
MAX_PID = 2**31 - 1

# Windows OpenProcess / GetExitCodeProcess constants
_WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WIN_STILL_ACTIVE = 259
_WIN_ERROR_ACCESS_DENIED = 5


def validate_language(language: Optional[str]) -> Optional[str]:
    """Validate optional BCP-47 / ISO language code (e.g. 'de', 'en', 'de-DE')."""
    if language is None:
        return None
    if not isinstance(language, str):
        raise ValueError("Language must be a string.")
    cleaned = language.strip()
    if not cleaned:
        return None
    if not LANGUAGE_PATTERN.fullmatch(cleaned):
        raise ValueError(
            f"Invalid language code '{cleaned}'. Expected format like 'de', 'en', or 'en-US'."
        )
    return cleaned


def parse_positive_float_env(
    env_name: str,
    default: float,
    min_value: float = 0.05,
    max_value: float = 3600.0,
) -> float:
    """Parse and validate a positive finite float from an environment variable."""
    raw = os.getenv(env_name)
    if raw is None or not raw.strip():
        return float(default)
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value for {env_name}: '{raw}'") from exc
    if not math.isfinite(value) or value < min_value or value > max_value:
        raise ValueError(
            f"{env_name} must be a finite number between {min_value} and {max_value}, got {raw!r}"
        )
    return value


def get_hf_cache_dir() -> Path:
    """Resolve HuggingFace Hub cache directory respecting standard environment variables."""
    hub_cache = os.getenv("HUGGINGFACE_HUB_CACHE", "").strip()
    if hub_cache:
        return Path(hub_cache)
    hf_home = os.getenv("HF_HOME", "").strip()
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def is_path_within(child: Path, parent: Path) -> bool:
    """Return True if resolved child is strictly inside resolved parent."""
    try:
        resolved_parent = parent.resolve()
        resolved_child = child.resolve()
        return resolved_child != resolved_parent and resolved_child.is_relative_to(resolved_parent)
    except OSError:
        return False


def _sanitize_user_tag(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", raw or "").strip("._-")
    return cleaned or "user"


def get_runtime_dir() -> Path:
    """
    Return a private per-user runtime directory for PID, status, and trigger files.

    Avoids predictable world-writable files directly in /tmp (CWE-377/CWE-59)
    and works consistently on Linux, macOS, and Windows.
    """
    override = os.getenv("STT_RUNTIME_DIR", "").strip()
    if override:
        runtime_dir = Path(override)
    elif os.name == "posix":
        xdg = os.getenv("XDG_RUNTIME_DIR", "").strip()
        uid = os.getuid()
        use_xdg = False
        if xdg:
            xdg_path = Path(xdg)
            try:
                st = os.lstat(xdg_path)
                if xdg_path.is_dir() and not xdg_path.is_symlink() and st.st_uid == uid:
                    use_xdg = True
            except OSError:
                use_xdg = False
        if use_xdg:
            runtime_dir = Path(xdg) / "realtimestt-bridge"
        else:
            runtime_dir = Path(tempfile.gettempdir()) / f"realtimestt-bridge-{uid}"
    else:
        user_tag = _sanitize_user_tag(getpass.getuser())
        runtime_dir = Path(tempfile.gettempdir()) / f"realtimestt-bridge-{user_tag}"

    _ensure_private_dir(runtime_dir)
    return runtime_dir


def _ensure_private_dir(path: Path) -> None:
    """Create directory with owner-only permissions and reject symlinks/foreign owners."""
    if path.is_symlink():
        raise RuntimeError(f"Refusing to use symlink as runtime directory: {path}")

    path.mkdir(parents=True, exist_ok=True)

    st = os.lstat(path)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Runtime path is not a real directory: {path}")

    if os.name == "posix":
        if st.st_uid != os.getuid():
            raise RuntimeError(f"Runtime directory is not owned by current user: {path}")
        if (st.st_mode & 0o077) != 0:
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass


def atomic_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """Atomically write UTF-8 text to path, refusing to follow symlinks."""
    if path.is_symlink():
        raise RuntimeError(f"Refusing to overwrite symlink: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            if os.name == "posix":
                os.chmod(tmp_path, mode)
            tmp.write(content)
            tmp.flush()
        if path.is_symlink():
            raise RuntimeError(f"Refusing to overwrite symlink: {path}")
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def parse_pid(text: str) -> Optional[int]:
    """Parse a strictly positive integer PID; returns None for invalid/unsafe values."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not PID_PATTERN.fullmatch(stripped):
        return None
    pid = int(stripped)
    if pid <= 0 or pid > MAX_PID:
        return None
    return pid


def read_pid_file(pid_file: Path) -> Optional[int]:
    """Safely read a positive integer PID from pid_file, refusing symlinks."""
    try:
        if pid_file.is_symlink() or not pid_file.is_file():
            return None
        return parse_pid(pid_file.read_text(encoding="utf-8"))
    except OSError:
        return None


def is_process_running(pid: Optional[int]) -> bool:
    """
    Cross-platform safe check whether a process with positive PID exists.

    On Windows, uses OpenProcess + GetExitCodeProcess rather than os.kill(pid, 0)
    (which sends CTRL_C_EVENT on Windows).
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or pid > MAX_PID:
        return False

    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(_WIN_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ctypes.get_last_error() == _WIN_ERROR_ACCESS_DENIED
        try:
            exit_code = ctypes.c_ulong(0)
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == _WIN_STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False


def safe_terminate_process(pid: int) -> bool:
    """Safely send SIGTERM to a validated positive PID."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or pid > MAX_PID:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, OSError):
        return False


def calculate_rms(data: bytes) -> float:
    """Compute RMS amplitude for 16-bit signed PCM audio bytes safely."""
    sample_count = len(data) // 2
    if sample_count == 0:
        return 0.0
    usable = data[: sample_count * 2]
    shorts = struct.unpack(f"<{sample_count}h", usable)
    return math.sqrt(sum(s * s for s in shorts) / sample_count)
