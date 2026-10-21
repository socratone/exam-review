# Exam Checker

시험지 PDF를 로컬 CPU에서 전처리하고, 첫 페이지를 Modal GPU의 Qwen으로 검토하는 Python CLI입니다. LangSmith로 처리 단계와 모델 입출력을 추적할 수 있습니다.

[CLI 실행 흐름과 Mermaid 차트](docs/cli-flow.md) · [실행 순서로 읽는 코드](docs/code-walkthrough.md) · [LangSmith 설정과 디버깅](docs/langsmith.md)

## 설치와 로컬 실행

Python 3.12 이상과 [uv](https://docs.astral.sh/uv/)를 사용합니다. 프로젝트 디렉터리에서 실행하세요.

```bash
uv sync --frozen
cp .env.example .env  # 처음 설정할 때만 실행; 기존 .env는 덮어쓰지 마세요.
uv run python scripts/create_sample.py
uv run exam-checker data/sample.pdf --verbose
```

샘플 생성기는 기존 `data/sample.pdf`를 덮어쓰지 않습니다. 실제 PDF의 상대 경로나 절대 경로도 전달할 수 있습니다. CLI와 Modal 배포 코드는 실행 디렉터리의 `.env`를 읽으며 셸 환경변수가 우선합니다.

기본 실행은 모든 페이지의 텍스트 추출·임시 PNG 렌더링·요약 출력까지만 수행합니다. 기본 DPI는 160이며 `--dpi`로 72–300 범위에서 변경합니다. 임시 이미지는 처리 종료 시 정리합니다. OCR은 실행하지 않으며 문자·숫자가 20자 미만인 페이지는 시각 검토 대상으로 표시합니다.

추출 텍스트와 PNG를 남기려면 `uv run exam-checker data/sample.pdf --keep-files`를 실행합니다. `output/sample.pages-<고유값>/`에 페이지별 `page-1.txt`, `page-1.png` 등이 저장되며, 실제 경로는 터미널에 출력됩니다. `--review`, `--modal-check`와 함께 사용할 수도 있습니다.

## Modal 인증과 배포

최초 인증은 브라우저에서 진행하며 `~/.modal.toml`을 사용합니다. L4 GPU 사용을 위해 Modal 계정의 결제 설정이 필요할 수 있습니다.

```bash
uv run modal token new
uv run modal deploy -m modal_app.app
```

`.env`의 `EXAM_CHECKER_GPU`는 배포 시 적용됩니다. 기본은 L4입니다. `EXAM_CHECKER_MODAL_APP`은 배포와 호출에 같은 값을 사용하며 기본은 `exam-checker`입니다. GPU 연산과 모델 캐시 Volume에는 Modal 요금이 적용됩니다.

```bash
# 모델 추론 없이 첫 페이지 전송과 CUDA 연산을 확인
uv run exam-checker data/sample.pdf --modal-check \
  --output output/sample.gpu-check.json

# 첫 페이지 텍스트 + PNG로 AI 검토
uv run exam-checker data/sample.pdf --review \
  --output output/sample.page-review.json

# 첫 페이지 텍스트만 전송
uv run exam-checker data/sample.pdf --review --text-only \
  --output output/sample.text-review.json
```

기본 모델은 `Qwen/Qwen3-VL-8B-Instruct`입니다. `--model`이나 `EXAM_CHECKER_MODEL`로 Qwen3-VL 계열 모델을 변경할 수 있습니다. 첫 호출은 모델 다운로드·GPU 로딩으로 시간이 걸립니다. 모델 파일만 Modal Volume에 캐시하고 시험지 요청을 별도 파일로 저장하지 않습니다.

## LangSmith 추적

`.env`에 다음 값을 설정하면 로컬 추적을 활성화합니다.

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=발급받은_API_키
LANGSMITH_PROJECT=exam-checker
EXAM_CHECKER_TRACE_CONTENT=false
EXAM_CHECKER_LANGSMITH_SECRET=exam-checker-langsmith
```

클라우드 추적에도 같은 설정을 적용하고 앱을 재배포합니다. 아래 스크립트는 LangSmith 관련 값만 Modal Secret에 저장하고 기존 같은 이름의 Secret 값을 갱신합니다. 키를 화면에 출력하지 않습니다.

```bash
uv run python scripts/configure_tracing.py
uv run modal deploy -m modal_app.app
uv run exam-checker data/sample.pdf --review --verbose
```

LangSmith의 `exam-checker` 프로젝트에서 `exam_checker.run`을 열면 로컬·클라우드 단계를 연결해 볼 수 있습니다. 모델 초기 로딩은 요청 처리 전 수행되므로 별도의 `model.load` trace입니다. 키가 없거나 `LANGSMITH_TRACING=false`이면 추적 없이 실행합니다.

기본으로 단계별 시간·오류 타입·페이지와 토큰 수 등의 메타데이터만 전송합니다. **프롬프트·추출 텍스트·원시 응답까지 보려면 `EXAM_CHECKER_TRACE_CONTENT=true`를 설정하세요. 이 내용은 LangSmith에 저장됩니다.** 클라우드 설정 변경 시 Secret 갱신과 재배포도 필요합니다. PNG 바이트는 추적에 포함하지 않습니다. 자세한 설정과 trace 트리는 [LangSmith 문서](docs/langsmith.md)를 참고하세요.

## 결과와 한계

`--output`은 정확한 파일 경로이며 확장자를 자동 보정하지 않습니다. 생략하면 `output/<이름>.page-review.json` 또는 `output/<이름>.gpu-check.json`에 저장합니다. 같은 파일은 성공 시 덮어쓰며, 추론 실패 시 이전 파일이 남을 수 있습니다. 파일 쓰기는 원자적 교체 방식이 아닙니다.

- 모든 페이지를 전처리하지만 AI는 **첫 페이지만** 검토합니다.
- 결과는 `unverified_page_review`, 각 의심 항목의 `verified`는 `null`입니다.
- 문항 분할·정답 키 검증·독립 재검증·전체 시험지 검토·Markdown 보고서는 지원하지 않습니다.
- 정상 샘플 `2 + 2`, 선택지 `3 / 4 / 5`에서 오탐이, 정답을 뺀 `3 / 5 / 6`에서 계산 오류와 오류 누락이 관찰됐습니다. `issues: []`나 높은 `confidence`는 정확성을 보장하지 않습니다.
- AI 요청 한도는 텍스트 30,000자, PNG 20 MB, 입력 8,192토큰, 생성 2,048토큰입니다. 이미지는 긴 변 최대 1,280픽셀로 축소하므로 작은 글씨를 놓칠 수 있습니다.

## 테스트와 로그

```bash
uv run pytest -q
uv run exam-checker --help
uv run modal app logs exam-checker -f --timestamps
```

로컬 테스트는 합성 PDF와 모의 원격 응답을 사용하며 GPU나 LangSmith API 키가 필요하지 않습니다. 추적 테스트는 SDK의 실제 RunTree와 모의 클라이언트로 분산 연결·본문 기록 제어·오류 가림을 검사합니다. 테스트 통과가 모델 판정 정확도를 뜻하지 않습니다.

처리 실패 시 종료 코드 1, 잘못된 옵션은 2입니다. 모델 로딩·추론 문제는 Modal 로그에서, 단계별 실행 시간과 선택한 입출력은 LangSmith에서 확인합니다.
