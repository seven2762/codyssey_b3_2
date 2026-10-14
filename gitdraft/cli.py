"""옵션, 결과 후처리, 터미널 출력."""
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path
from .ai import generate
from .env import load_ai_env
from .git_context import DraftError, collect, mask


def positive(value: str) -> int:
    """CLI 옵션의 문자열을 정수로 바꾸고, 0 이하이면 입력 오류를 발생시킨다."""
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("양의 정수를 입력하세요.")
    return number


def temperature(value: str) -> float:
    """CLI 입력을 실수로 바꾸고, 유한한 0~2 범위의 temperature인지 확인한다."""
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 2:
        raise argparse.ArgumentTypeError("temperature는 0~2 사이여야 합니다.")
    return number


def parser() -> argparse.ArgumentParser:
    """CLI에서 허용할 명령·옵션·기본값·입력 검증 규칙을 정의한 파서를 반환한다."""
    p = argparse.ArgumentParser(description="Git 변경 사항으로 검토용 커밋/PR 초안을 생성합니다.")
    p.add_argument("command", choices=("commit", "pr", "all"))
    p.add_argument("--model", "-model", default=os.getenv("AI_MODEL") or "gpt-4o-mini")
    p.add_argument("--base-url", default=os.getenv("AI_BASE_URL") or "https://api.openai.com/v1",
                   help="OpenAI 호환 HTTPS 게이트웨이 주소 (AI_BASE_URL 지원)")
    p.add_argument("--api-format", choices=("openai", "compatible"),
                   default=os.getenv("AI_API_FORMAT") or "openai",
                   help="compatible은 고급 JSON 옵션 없이 max_tokens를 사용")
    p.add_argument("--temperature", "-temperature", type=temperature, default=0.2)
    p.add_argument("--max-tokens", "-max-tokens", type=positive, default=1200)
    p.add_argument("--context", default="", help="변경 이유·요구사항·실행한 테스트 정보")
    safety = p.add_mutually_exclusive_group()
    safety.add_argument("--safe-mode", "-safe-mode", dest="safe_mode", action="store_true",
                        help="키/이메일 마스킹 및 민감 파일 제외 (기본값)")
    safety.add_argument("--no-safe-mode", dest="safe_mode", action="store_false",
                        help="마스킹·민감 파일 제외를 비활성화")
    p.set_defaults(safe_mode=True)
    p.add_argument("--max-files", type=positive, default=10)
    p.add_argument("--max-lines", type=positive, default=200)
    p.add_argument("--preview", action="store_true", help="전송 컨텍스트만 확인 (API 호출 없음)")
    return p


def line(value) -> str:
    """문자열에서 제어문자와 불필요한 공백·끝 장식을 정리해 한 줄로 반환한다.

    문자열이 아닌 값은 빈 문자열로 처리한다.
    """
    if not isinstance(value, str):
        return ""
    value = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", value)
    return " ".join(value.split()).strip("` #")


def bullets(value, fallback: str) -> list[str]:
    """AI의 배열 값을 불릿용 문장 최대 6개로 정리하고, 비어 있으면 안내문을 넣는다."""
    items = [line(x).lstrip("-* ") for x in value] if isinstance(value, list) else []
    return [x for x in items if x][:6] or [fallback]


def normalize(result: dict, context: dict) -> tuple[dict, list[str]]:
    """AI 초안의 필수 제목·요약, 제목 길이와 섹션 내용을 검증하고 다듬는다.

    출력할 데이터와 경고 목록을 반환하며, 일부 diff만 분석했으면 요약에 표시한다.
    """
    title, summary = line(result.get("title")), line(result.get("summary"))
    if not title or not summary:
        raise DraftError("AI 응답에 필수 제목 또는 변경 요약이 없습니다.")
    notices = []
    if len(title) > 80:
        title = title[:79].rstrip() + "…"
        notices.append("PR 제목을 80자 이내로 다듬었습니다.")
    commit_title = title if len(title) <= 72 else title[:71].rstrip() + "…"
    if len(title) > 72:
        notices.append("커밋 제목을 72자 이내로 다듬었습니다.")
    if len(commit_title) > 50:
        notices.append("커밋 제목이 권장 길이 50자를 초과합니다. 검토 후 줄여 주세요.")
    normalized = {"summary": summary, "title": title, "commit_title": commit_title}
    filenames = ", ".join(line(f["path"]) for f in context.get("files", [])[:3])
    fallbacks = {"why": "변경 배경 확인 필요: 작성자가 변경 목적을 보완하세요.",
                 "what": f"변경 파일 {filenames or '(확인 필요)'}: 실제 변경 내용을 검토하세요.",
                 "how_to_test": "권장 절차 (미실행): 변경 파일을 검토하고 관련 테스트를 실행하세요."}
    for key, fallback in fallbacks.items():
        normalized[key] = bullets(result.get(key), fallback)
        if normalized[key] == [fallback]:
            notices.append(f"{key} 내용이 없어 확인 필요 안내를 넣었습니다.")
    if context["truncated"] or context["omitted_files"]:
        normalized["summary"] += " (입력 제한으로 일부 변경만 분석했습니다.)"
    return normalized, notices


def show(data: dict, command: str) -> None:
    """정리된 초안을 터미널에 출력한다. commit/pr/all에 따라 표시할 구역을 선택한다."""
    print("\n--- Change Summary ---\n" + data["summary"])
    if command in {"commit", "all"}:
        print("\n--- Commit Message ---\n" + data["commit_title"] + "\n")
        print("\n".join("- " + item for item in data["what"]))
    if command in {"pr", "all"}:
        print("\n--- PR Title ---\n" + data["title"] + "\n\n--- PR Body ---")
        for heading, key in (("Why", "why"), ("What", "what"), ("How to Test", "how_to_test")):
            print(f"## {heading}")
            print("\n".join("- " + item for item in data[key]) + "\n")
    print("----------------------\n[INFO] 초안입니다. 검토 후 직접 적용하세요.")


def main() -> int:
    """.env 로드부터 Git 수집·AI 호출·검증·출력까지 CLI 전체 흐름을 실행한다.

    parse_args()는 터미널 입력인 sys.argv를 읽는다. 변경 없음과 미리보기에서는
    API를 호출하지 않으며, 실행 결과를 프로세스 종료 코드로 반환한다.
    """
    try:
        env_path = Path.cwd() / ".env"
        if env_path.exists():
            load_ai_env(env_path)
    except OSError:
        print("[ERROR] 현재 작업 폴더의 .env 파일을 읽을 수 없습니다.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return 1
    args = parser().parse_args()
    calls = 0
    try:
        context = collect(args.safe_mode, args.max_files, args.max_lines)
        if not context:
            print("[INFO] 변경 사항이 없습니다. 생성하지 않고 종료합니다.")
            return 0
        print(f"[INFO] Git status 수집 완료: {context['changed_files']}개 파일 변경 감지")
        print("[INFO] 현재 브랜치: " + line(context["branch"]))
        print(f"[INFO] Git diff 수집 완료: {context['diff_lines']}줄")
        print("--- Changed Files ---")
        for item in context["files"]:
            print(f"{item['status']} {line(item['path'])}")
        if context["excluded_files"]:
            print(f"[INFO] 민감 파일 {context['excluded_files']}개 제외")
        if context["truncated"] or context["omitted_files"]:
            print("[WARN] 입력 제한으로 일부 변경만 전송합니다.")
        if context["untracked_files"]:
            print("[WARN] 새 파일은 이름만 반영됩니다. 내용을 분석하려면 먼저 git add 하세요.")
        reason = mask(args.context) if args.safe_mode else args.context
        if len(reason) > 4000:
            raise DraftError("--context는 4,000자 이내로 입력하세요.")
        if args.preview:
            print(json.dumps({"command": args.command, "context": reason, **context},
                             ensure_ascii=False, indent=2))
            return 0
        key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not key or not key.strip():
            raise DraftError('AI_API_KEY 환경변수가 설정되지 않았습니다. 예: export AI_API_KEY="YOUR_KEY"')
        print("[INFO] AI API 요청 중...", flush=True)
        calls = 1
        result = generate(context, args.command, reason, key, args.model,
                          args.temperature, args.max_tokens, args.base_url, args.api_format)
        result = redact_result(result, key)
        data, notices = normalize(result, context)
        for notice in notices:
            print("[WARN] " + notice)
        print("[DONE] 초안 생성 및 형식 검증 완료")
        show(data, args.command)
        return 0
    except DraftError as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[ERROR] 실행을 취소했습니다.", file=sys.stderr)
        return 130
    finally:
        print(f"[INFO] AI API 호출 횟수: {calls}", flush=True)


def redact_result(value, key):
    """응답의 문자열 값을 재귀적으로 찾아 민감정보와 API 키를 가린다.

    딕셔너리와 리스트의 구조는 유지하고 문자열이 아닌 값은 그대로 반환한다.
    """
    # JSON 직렬화 텍스트를 마스킹하면 구문이 손상될 수 있어 문자열 값마다 처리한다.
    if isinstance(value, str):
        return mask(value).replace(key, "[REDACTED]")
    if isinstance(value, list):
        return [redact_result(item, key) for item in value]
    if isinstance(value, dict):
        return {name: redact_result(item, key) for name, item in value.items()}
    return value
