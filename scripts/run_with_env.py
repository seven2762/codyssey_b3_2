"""기존 .env의 AI 설정만 환경변수로 전달해 실행. 키를 복사·출력하지 않는다.

python scripts/run_with_env.py /path/to/backend/.env all
"""
from pathlib import Path
import sys

# 분석 대상은 현재 작업 디렉토리이며 모듈만 이 도구의 경로에서 로드한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gitdraft.cli import main
from gitdraft.env import load_ai_env


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python scripts/run_with_env.py /path/to/.env {commit,pr,all} [옵션]", file=sys.stderr)
        raise SystemExit(2)
    try:
        load_ai_env(Path(sys.argv[1]))
    except OSError:
        print("[ERROR] AI 설정 파일을 읽을 수 없습니다.", file=sys.stderr)
        raise SystemExit(1)
    except ValueError as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[2:], load_local_env=False))
