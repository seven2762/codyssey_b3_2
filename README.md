# AI Git 커밋 / PR 초안 생성기

Git 변경 사항을 읽고 AI API를 한 번 호출해 변경 요약, 커밋 메시지, Pull Request 제목과 본문을 터미널에 출력하는 Python CLI입니다. 생성된 초안을 검토하고 복사해 사용하는 도구입니다.

## 1. 개발 환경과 설치

- Python **3.10 이상**, Git, 인터넷 연결, OpenAI API Key
- 웹 화면 및 추가 Python 패키지 없이 표준 라이브러리로 실행
- macOS / Linux / Windows의 터미널 사용

```bash
git clone -b feature/commit-pr-generator https://github.com/seven2762/codyssey_b3_2.git
cd codyssey_b3_2
python3 -m venv .venv
source .venv/bin/activate
python --version
python main.py --help
```

Windows PowerShell에서는 `python -m venv .venv`, `.\.venv\Scripts\Activate.ps1`을 사용합니다. macOS 기본 `python3`이 3.9라면 Python 3.10 이상을 설치한 뒤 해당 실행 파일로 가상환경을 만드세요. `pip install`은 필요하지 않습니다.

다른 프로젝트의 변경을 분석하려면 **분석할 Git 프로젝트의 루트**로 이동한 뒤 이 저장소의 `main.py`를 절대 경로로 실행합니다.

```bash
cd /path/to/your-project
python /path/to/codyssey_b3_2/main.py commit
```

## 2. API Key 환경변수

macOS / Linux:

```bash
export AI_API_KEY="YOUR_KEY"
```

Windows PowerShell:

```powershell
$env:AI_API_KEY = "YOUR_KEY"
```

`OPENAI_API_KEY`도 지원하며, 둘 다 있으면 `AI_API_KEY`를 우선합니다. 키는 환경변수에서만 읽습니다. `.env` 파일은 자동 로드하지 않으며 키를 소스나 Git에 저장하지 마세요. 이 프로그램은 OpenAI API의 별도 사용 권한과 잔액이 필요합니다.

## 3. 명령과 옵션

```bash
# 변경 파일과 전송할 내용을 먼저 검토 (키/비용 없이 실행)
python main.py all --preview

# 커밋 메시지 생성
python main.py commit

# PR 제목 및 본문 생성
python main.py pr --context "빈 입력에서 예외가 발생해 입력 검증을 추가했습니다."

# 요약 + 커밋 + PR을 한 번의 API 요청으로 생성
python main.py all --context "요구사항: 오류 원인 안내. 실행한 테스트: unittest 통과."

# 모델, 생성 다양성, 최대 출력 토큰 변경
python main.py commit -model gpt-4o-mini -temperature 0.2 -max-tokens 1200 -safe-mode
```

| 옵션 | 기본값 | 의미 |
| --- | --- | --- |
| `--model`, `-model` | `gpt-4o-mini` | 사용할 Chat Completions 모델 |
| `--temperature`, `-temperature` | `0.2` | 0~2, 낮을수록 표현의 변동이 줄어드는 경향 |
| `--max-tokens`, `-max-tokens` | `1200` | 양의 정수, 최대 생성 토큰 수 |
| `--context` | 빈 문자열 | 변경 이유, 요구사항, 실제 실행한 테스트; 최대 4,000자 |
| `--safe-mode`, `-safe-mode` | 활성 | 패턴 마스킹 및 민감 파일 제외 |
| `--no-safe-mode` | 비활성 | 명시적으로 마스킹과 민감 파일 제외를 해제 |
| `--max-files` | `10` | 전송할 최대 변경 파일 수 |
| `--max-lines` | `200` | 전송할 최대 diff 줄 수 |
| `--preview` | 비활성 | API를 호출하지 않고 전송 컨텍스트 출력 |

CLI의 `max-tokens`는 REST 요청의 `max_completion_tokens`로 전달합니다. 출력 한도가 너무 작으면 JSON이 잘릴 수 있어 완성되지 않은 응답은 오류로 처리합니다. 모든 모델이 `temperature`와 JSON 모드를 지원하는 것은 아닙니다. 모델을 바꾼 뒤 HTTP 400이 발생하면 지원 파라미터를 확인하세요. 파라미터와 응답 형식의 근거는 [OpenAI Chat Completions 공식 문서](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)입니다.

## 4. 입력과 자동화 흐름

1. 현재 디렉토리에 `.git`이 있는지 검사합니다. 하위 디렉토리에서 실행하면 안내하고 종료합니다.
2. `git status --porcelain=v1 --branch -z --untracked-files=all`로 브랜치 및 변경 파일을 수집합니다.
3. `git diff --cached`와 `git diff`로 staged / unstaged 변경을 각각 수집합니다. 외부 diff 도구 및 textconv는 실행하지 않습니다.
4. 민감 파일 제외, 패턴 마스킹, 파일·줄·문자 제한을 적용합니다.
5. 시스템 프롬프트에 길이·JSON·템플릿 규칙을 넣고, 사용자 입력에는 Git 정보와 변경 배경을 JSON으로 전달합니다.
6. HTTPS REST `POST /v1/chat/completions` 요청에 인증 헤더, 모델, temperature, 출력 토큰 한도를 넣습니다.
7. 응답 JSON을 파싱하고 제목을 한 줄로 정리합니다. 제목 길이를 제한하고 PR 섹션과 불릿을 구성한 뒤 출력합니다.

변경 배경을 diff만으로 추측하지 않도록 `--context`를 제공하세요. 테스트 정보가 없으면 권장 절차를 작성하도록 프롬프트에 지시하며 실행 성공을 만들어 내지 않도록 합니다. diff 안의 지시문은 분석할 데이터로 취급하도록 설계했습니다.

**새 파일(untracked)**은 Git diff에 내용이 없으므로 이름만 전달하고 경고합니다. 파일 내용까지 분석하려면 사용자가 먼저 `git add <파일>`을 실행하세요. 무시된 파일은 수집하지 않습니다. 바이너리, 서브모듈 변경은 Git이 제공한 정보만 분석할 수 있습니다. PR 초안도 현재 작업 디렉토리의 변경을 기준으로 하며 이미 커밋한 브랜치 전체의 diff는 수집하지 않습니다.

프로그램은 Git 조회 명령인 **status / diff만** 실행합니다. 자동 `git add`, 커밋, push, GitHub PR 생성 기능은 없습니다.

## 5. 생성 결과 예시

아래는 **설명용 예시**이며 실제 API 응답은 변경 사항과 모델에 따라 달라집니다.

```text
[INFO] Git status 수집 완료: 1개 파일 변경 감지
[INFO] 현재 브랜치: feature/input-validation
[INFO] Git diff 수집 완료: 12줄
--- Changed Files ---
 M app.py
[INFO] AI API 요청 중...
[DONE] 초안 생성 및 형식 검증 완료

--- Change Summary ---
app.py에서 빈 입력을 처리하도록 검증을 추가했습니다.

--- Commit Message ---
fix: 빈 입력 검증 추가

- app.py에서 빈 입력을 감지하고 오류 메시지를 반환하도록 수정

--- PR Title ---
fix: 빈 입력 검증 추가

--- PR Body ---
## Why
- 빈 입력에서 발생하는 예외를 처리하기 위해 변경했습니다.

## What
- app.py에서 빈 입력을 감지하고 오류 메시지를 반환하도록 수정

## How to Test
- 권장 절차 (미실행): 빈 입력과 정상 입력을 전달해 응답을 확인하세요.

----------------------
[INFO] 초안입니다. 검토 후 직접 적용하세요.
[INFO] AI API 호출 횟수: 1
```

커밋 제목은 50자 이내를 권장하고 최대 72자, PR 제목은 최대 80자로 다듬습니다. 길이는 Python 문자열의 문자 수로 계산합니다. 긴 제목은 말줄임표로 끝나므로 의미를 검토하세요. 제목·요약이 없으면 오류로 종료합니다. 섹션 내용이 비어 있으면 사실을 만들어 넣는 대신 **확인 필요 안내**를 불릿으로 넣고 경고합니다. 커밋 본문에는 핵심 변경 불릿 또는 변경 파일 1~3개를 표시합니다.

사용자는 `Commit Message` 구역을 복사해 커밋하고, `PR Title` / `PR Body`를 GitHub 작성 화면에 붙여 넣습니다. 로그와 구분선은 복사 대상에서 제외하세요.

## 6. 오류 처리

```text
[INFO] 변경 사항이 없습니다. 생성하지 않고 종료합니다.
[INFO] AI API 호출 횟수: 0
```

```text
[ERROR] AI_API_KEY 환경변수가 설정되지 않았습니다. 예: export AI_API_KEY="YOUR_KEY"
[INFO] AI API 호출 횟수: 0
```

- HTTP 400: 모델·파라미터 호환성 확인
- HTTP 401: API Key 인증 실패
- HTTP 403 / 404: 권한 또는 모델 이름 확인
- HTTP 429: 요청 한도 또는 잔액 확인
- DNS / 연결 / TLS / 타임아웃: 네트워크 오류 원인 출력, 요청 타임아웃 45초
- 손상되거나 잘린 JSON: 형식 오류 안내, 자동 재요청 없음
- 모든 파일이 안전 모드에서 제외되면 전송하지 않고 종료

오류는 stderr에, 결과와 호출 횟수는 stdout에 출력합니다. 성공 및 변경 없음은 종료 코드 0, 실행 오류는 1, 옵션 오류는 2, 사용자 중단은 130입니다. 오류 응답 원문은 키나 입력 내용을 반사할 수 있어 출력하지 않습니다.

## 7. 보안 및 비용

안전 모드는 기본 활성입니다. `.env*`, 키·인증서 파일, 알려진 자격증명 파일을 제외하고 API 키 형태, GitHub 토큰, AWS 액세스 키, 이메일, password/secret 등 할당문, PEM 개인키를 마스킹합니다. 환경변수에 설정된 실제 API Key도 제거합니다. `--context`, 파일명, 브랜치 이름에도 마스킹을 적용합니다.

기본 최대 **10개 파일, diff 200줄**, 추가로 diff 24,000자 제한을 적용합니다. 파일은 Git status 순서로 선택하고 staged diff를 먼저 넣으므로 큰 변경에서는 일부 변경이 빠질 수 있습니다. 이 경우 요약에 부분 분석임을 표시합니다. 필요하면 변경을 작게 나누거나 제한을 조정하세요.

패턴 마스킹은 모든 개인정보·회사 기밀을 검출하지 못합니다. 실행 전 `--preview`로 입력을 직접 확인하고, 민감한 변경은 외부 API로 전송하지 마세요. 안전 모드를 해제하면 입력의 민감 파일·문자열이 전송될 수 있습니다. 응답 문자열의 키 마스킹은 항상 적용합니다.

`commit`, `pr`, `all` 모두 **실행당 최대 1회** API 요청을 하고 자동 재시도하지 않습니다. API 호출을 시도한 횟수를 마지막 로그에 출력합니다. 실패한 요청도 1회로 집계합니다. 입력 미리보기, 변경 없음, 키 누락은 0회입니다. `all`을 사용하면 커밋·PR을 따로 실행할 때보다 요청 수를 줄일 수 있습니다. `store: false`로 요청하며, 이 옵션만으로 제공업체의 모든 데이터 보관을 차단하는 것은 아닙니다.

## 8. 테스트 및 제출 확인

```bash
python -m unittest discover -s tests -v
```

테스트는 실제 임시 Git 저장소와 모의 HTTP 응답을 이용합니다. API Key나 비용 없이 변경 없음, staged/unstaged, 신규·삭제·이름 변경, 파일·줄 제한, 민감정보 제외·마스킹, 옵션, REST 요청 구성, 출력 형식 및 API 오류를 검증합니다. **모의 API 테스트는 실제 AI 응답의 의미적 품질을 보장하지 않습니다.**

실제 연동 확인은 키 설정 후 분석할 프로젝트에 변경을 만들고 수행합니다.

```bash
python main.py all --preview
python main.py all --context "이번 변경 이유와 요구사항"
```

출력에서 호출 횟수 1회, 변경 요약, 커밋 제목, PR 제목, 세 섹션 및 불릿을 확인하세요. 이 프로젝트를 커밋한 직후에는 변경이 없어 API 호출이 생략됩니다.

GitHub 업로드는 개발자가 별도로 수행합니다. 다음 명령은 CLI 기능에 포함되지 않습니다.

```bash
git switch -c feature/my-change
git add main.py gitdraft tests README.md pyproject.toml .gitignore
git commit -m "feat: add AI Git commit and PR draft CLI"
git push -u origin feature/my-change
```

## 파일 구조

```text
main.py                  터미널 진입점
gitdraft/
  cli.py                 옵션·후처리·출력
  git_context.py         Git 수집·민감정보 처리
  ai.py                  프롬프트·REST 요청·응답·오류 처리
tests/test_gitdraft.py    자동 테스트
pyproject.toml           Python 3.10+ 및 의존성 정보
.gitignore               환경·키·캐시 제외
README.md                사용 및 운영 가이드
```
