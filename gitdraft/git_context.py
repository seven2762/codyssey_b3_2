"""읽기 전용 Git 수집과 API 전송 전 안전 처리."""
import os
import re
import subprocess
from pathlib import Path


class DraftError(Exception):
    """사용자가 해결할 수 있는 실행 오류."""


def mask(text: str) -> str:
    for name in ("AI_API_KEY", "OPENAI_API_KEY"):
        key = os.getenv(name, "")
        if key:
            text = text.replace(key, "[REDACTED]")
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                  "[REDACTED PRIVATE KEY]", text, flags=re.S)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+|AKIA[A-Z0-9]{16})\b",
                  "[REDACTED KEY]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED EMAIL]", text)
    text = re.sub(r"(?im)((?:api[_-]?key|access[_-]?token|secret|password|authorization)\s*[\"']?\s*[:=]\s*)[^\r\n]+",
                  r"\1[REDACTED]", text)
    return text


def sensitive(path: str) -> bool:
    p = Path(path)
    return (p.name == ".env" or p.name.startswith(".env.")
            or p.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}
            or p.name.lower() in {"credentials", "credentials.json", "id_rsa", "id_ed25519"}
            or any(part in {".aws", ".ssh"} for part in p.parts))


def git(*args: str) -> str:
    try:
        result = subprocess.run(["git", "-c", "core.quotePath=false", *args],
                                capture_output=True, encoding="utf-8", errors="replace",
                                timeout=30, check=False)
    except FileNotFoundError as exc:
        raise DraftError("Git이 설치되어 있지 않습니다.") from exc
    except subprocess.TimeoutExpired as exc:
        raise DraftError("Git 명령이 30초 내에 완료되지 않았습니다.") from exc
    if result.returncode:
        raise DraftError("Git 명령 실패: " + mask(result.stderr.strip()))
    return result.stdout


def parse_status(raw: str) -> tuple[str, list[dict]]:
    entries = raw.split("\0")
    branch = entries.pop(0).removeprefix("## ").split("...")[0]
    files = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry:
            continue
        state, path = entry[:2], entry[3:]
        item = {"status": state, "path": path}
        if "R" in state or "C" in state:
            item["old_path"] = entries[i]
            i += 1
        files.append(item)
    return branch, files


def collect(safe: bool, max_files: int, max_lines: int) -> dict:
    if not (Path.cwd() / ".git").exists():
        raise DraftError("Git이 초기화된 프로젝트 루트 디렉토리에서 실행하세요.")
    branch, files = parse_status(git("status", "--porcelain=v1", "--branch", "-z",
                                    "--untracked-files=all"))
    if not files:
        return {}
    selected = [f for f in files if not safe or
                not any(sensitive(f[p]) for p in ("path", "old_path") if p in f)]
    excluded = len(files) - len(selected)
    omitted = max(0, len(selected) - max_files)
    selected = selected[:max_files]
    if not selected:
        raise DraftError("모든 변경 파일이 안전 모드에서 제외되었습니다. 전송할 변경이 없습니다.")
    paths = list(dict.fromkeys(p for f in selected if f["status"] != "??"
                              for p in (f["path"], f.get("old_path", f["path"]))))
    chunks = []
    if paths:
        for label, options in (("STAGED", ["--cached"]), ("UNSTAGED", [])):
            patch = git("--literal-pathspecs", "diff", *options, "--no-ext-diff",
                        "--no-textconv", "--no-color", "--", *paths)
            if patch:
                chunks.append(f"[{label}]\n{patch}")
    diff = "\n".join(chunks)
    if safe:
        diff = mask(diff)
    lines = diff.splitlines()
    clipped = len(lines) > max_lines or len(diff) > 24000
    diff = "\n".join(lines[:max_lines])[:24000]
    clean = (lambda value: mask(value) if safe else value)
    return {"branch": clean(branch), "files": [
        {key: clean(value) for key, value in f.items()} for f in selected],
        "diff": diff, "changed_files": len(files), "excluded_files": excluded,
        "omitted_files": omitted, "diff_lines": len(lines), "truncated": clipped,
        "untracked_files": sum(f["status"] == "??" for f in selected)}
