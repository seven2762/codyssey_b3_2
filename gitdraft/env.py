"""AI 설정 파일을 읽어 현재 프로세스의 환경변수로 전달한다."""
import os
from pathlib import Path
import re
import shlex


def load_ai_env(path: Path) -> None:
    allowed = {"AI_API_KEY", "OPENAI_API_KEY", "AI_BASE_URL", "AI_MODEL", "AI_API_FORMAT"}
    settings = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)", raw)
        if not match or match[1] not in allowed:
            continue
        try:
            words = shlex.split(match[2], comments=True)
        except ValueError:
            raise ValueError(f"{match[1]} 설정의 따옴표 형식이 잘못되었습니다.") from None
        if len(words) != 1 or not words[0].strip():
            raise ValueError(f"{match[1]} 설정이 비어 있거나 형식이 잘못되었습니다.")
        settings[match[1]] = words[0]
    if not (settings.get("AI_API_KEY") or settings.get("OPENAI_API_KEY")):
        raise ValueError("설정 파일에 AI API Key가 없습니다.")
    if "AI_BASE_URL" not in settings:
        raise ValueError("키가 잘못된 제공업체로 전송되지 않도록 AI_BASE_URL도 설정하세요.")
    settings.setdefault("AI_API_FORMAT", "compatible")
    # 명시적으로 선택한 파일의 키를 사용한다. 상속된 다른 제공업체 키를 섞지 않는다.
    os.environ.pop("AI_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.update(settings)

