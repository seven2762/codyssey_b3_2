"""터미널 진입점: Python 3.10 이상."""
from gitdraft.cli import main

if __name__ == "__main__":
    # 터미널에서 이 파일을 실행하면 CLI를 시작하고 반환값을 종료 코드로 사용한다.
    raise SystemExit(main())
