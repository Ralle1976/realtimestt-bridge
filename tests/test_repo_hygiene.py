"""Repository security, hygiene, and plugin metadata validation tests (100% offline)."""

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PII_PATTERNS = {
    "unix_home_path": re.compile(r"/home/[A-Za-z0-9._-]+"),
    "windows_user_path": re.compile(r"[A-Za-z]:\\Users\\[^\\'\"]+"),
}

SECRET_PATTERNS = {
    "openai_key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "github_pat": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "hf_token": re.compile(r"hf_[A-Za-z0-9]{20,}"),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private_key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
}


def _repo_source_files():
    """Return tracked/non-test source, doc, and config files in the repository."""
    files = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        parts = rel.parts
        if any(p in {".git", "__pycache__", ".pytest_cache", "node_modules", "tests"} for p in parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    return sorted(files)


def test_plugin_json_valid_and_complete():
    plugin_file = REPO_ROOT / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin_file.read_text(encoding="utf-8"))

    assert data["name"] == "realtimestt-bridge"
    assert isinstance(data["commands"], list) and len(data["commands"]) >= 4
    command_names = {cmd["name"] for cmd in data["commands"]}
    assert {"stt-once", "stt-models", "stt-arm", "stt-disarm"}.issubset(command_names)

    for cmd_name in command_names:
        assert (REPO_ROOT / "commands" / f"{cmd_name}.cjs").is_file()

    for agent in data.get("agents", []):
        assert (REPO_ROOT / agent["path"]).is_file()


def test_no_hardcoded_user_paths_or_secrets():
    findings = []
    for file_path in _repo_source_files():
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        rel = file_path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(content.splitlines(), start=1):
            for name, pattern in {**PII_PATTERNS, **SECRET_PATTERNS}.items():
                if pattern.search(line):
                    findings.append(f"{name} at {rel}:{lineno}")
    assert findings == [], f"Detected PII/secret patterns: {findings}"


def test_no_unsafe_shell_execution_or_hardcoded_tmp_ipc():
    unsafe_hits = []
    for file_path in _repo_source_files():
        rel = file_path.relative_to(REPO_ROOT).as_posix()
        content = file_path.read_text(encoding="utf-8", errors="ignore")

        if file_path.suffix == ".py":
            tree = ast.parse(content, filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if (
                            kw.arg == "shell"
                            and isinstance(kw.value, ast.Constant)
                            and kw.value.value is True
                        ):
                            unsafe_hits.append(f"shell=True at {rel}:{node.lineno}")
            if "/tmp/stt_" in content:
                unsafe_hits.append(f"hardcoded /tmp/stt_ in {rel}")

        if file_path.suffix == ".cjs":
            if re.search(r"\bexecSync\s*\(", content):
                unsafe_hits.append(f"execSync in {rel}")
            if '"/tmp/stt_' in content or "'/tmp/stt_" in content:
                unsafe_hits.append(f"hardcoded /tmp/stt_ in {rel}")

    assert unsafe_hits == [], f"Unsafe patterns detected: {unsafe_hits}"
