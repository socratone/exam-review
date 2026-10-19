# LangSmith 설정과 디버깅

이 프로젝트는 LangChain으로 추론을 변경하지 않고 LangSmith SDK로 기존 Python 처리 단계를 추적합니다. 로컬 추론은 없으며 Qwen은 Modal GPU에서 실행합니다.

## 1. 설정

[LangSmith](https://smith.langchain.com/)에서 API 키를 발급받아 로컬 `.env`에 입력하세요. 실제 키는 저장소나 채팅에 올리지 않습니다.

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=발급받은_API_키
LANGSMITH_PROJECT=exam-checker
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
EXAM_CHECKER_TRACE_CONTENT=false
EXAM_CHECKER_LANGSMITH_SECRET=exam-checker-langsmith
```

다른 리전이나 자체 서버를 사용하는 경우 계정에 맞는 `LANGSMITH_ENDPOINT`를 사용하세요. 파일은 실행 디렉터리에서 읽으며 기존 셸 환경변수를 덮어쓰지 않습니다.

```bash
uv sync --frozen
uv run python scripts/configure_tracing.py
uv run modal deploy -m modal_app.app
uv run exam-checker data/sample.pdf --review --verbose
```

`configure_tracing.py`는 지정된 이름의 Modal Secret을 생성하거나 갱신합니다. 로컬 API 키를 원격 함수 인자로 전달하지 않고 Secret을 통해 GPU 워커에 주입합니다. 프로젝트·엔드포인트·본문 기록 여부를 바꾸면 이 스크립트를 다시 실행하고 재배포하세요.

키가 없으면 프로그램은 경고 후 추적 없이 실행합니다. `LANGSMITH_TRACING=false`로 로컬 추적을 끄면 원격 호출에 부모 trace를 전달하지 않으며, 원격 요청 trace도 생성하지 않습니다. 모델 초기 로딩 trace까지 끄려면 Modal Secret 설정도 갱신해야 합니다.

## 2. 화면에서 보는 순서

LangSmith의 지정 프로젝트에서 `exam_checker.run`을 찾습니다. 실행마다 별도 trace가 생성됩니다.

```text
exam_checker.run
├── pdf.preprocess
│   ├── pdf.extract_text  (페이지별)
│   ├── pdf.page          (텍스트 길이 및 선택적 원문)
│   └── pdf.render_page   (페이지별)
├── modal.review
│   └── gpu.review
│       ├── model.generate
│       └── response.parse
└── report.write

model.load                (새 GPU 컨테이너의 별도 trace)
└── model.download
```

`--modal-check`는 `modal.review → gpu.review` 대신 `modal.gpu_check → gpu.check`가 나타납니다. 전처리 모드에는 원격 단계가 없습니다. 실패한 요청에서는 실행되지 않은 뒤쪽 단계도 없습니다.

로컬 SDK의 `to_headers()`로 만든 추적 헤더만 원격 요청에 전달합니다. 워커는 이 헤더를 부모로 사용해 로컬 호출 아래에 연결합니다. **키와 프로젝트가 로컬·Modal 양쪽에서 설정되어야 전체 연결이 보입니다.** `model.load`는 Modal의 컨테이너 시작 훅이라 요청 헤더를 받기 전에 실행되며 별도 trace로 남습니다.

## 3. 기록하는 데이터

| 항목 | 기본 | `EXAM_CHECKER_TRACE_CONTENT=true` |
| --- | --- | --- |
| 단계 이름·실행 시간·성공/오류 | 기록 | 기록 |
| 페이지 수·DPI·텍스트 길이·출력 파일명 | 기록 | 기록 |
| 입력·생성·전체 토큰 수 | 기록 | 기록 |
| 추출한 페이지 텍스트 | 미기록 | 기록 |
| 실제 프롬프트·원시 모델 응답 | 미기록 | 기록 |
| 파싱된 검토 결과 | 미기록 | 기록 |
| PNG 바이트·모델 가중치·API 키 | 미기록 | 미기록 |

현재 입력 프롬프트와 원시 응답은 `model.generate` 실행의 Outputs에 기록합니다. `usage_metadata`에는 토큰 수가 들어가며 비용은 자동 계산하지 않습니다. `pdf.page`는 모든 전처리 페이지에 생성되므로 본문 기록을 켜면 첫 페이지뿐 아니라 **모든 페이지의 추출 텍스트**가 LangSmith로 전송됩니다.

오류는 예외 타입이나 고정 오류 코드로 기록합니다. Pydantic의 원문 포함 오류나 traceback을 자동 전송하지 않습니다. 이미지 자체를 확인하려면 별도 이미지 보존 기능이 필요하며 현재 추적에는 이미지를 첨부하지 않습니다.

## 4. 문제 찾기

- 느린 실행: `modal.review`가 길고 `model.generate`가 짧으면 GPU 기동·모델 로딩·네트워크 대기를 먼저 확인합니다. `model.load` trace도 함께 봅니다.
- 잘못 읽은 문제: 본문 기록을 켜고 `pdf.page`의 추출 텍스트와 `model.generate`의 프롬프트를 확인합니다.
- 잘못된 판정: 원시 응답과 `response.parse`의 결과를 비교합니다. 스키마 통과는 정답 검증이 아닙니다.
- 로컬만 보임: Secret 이름, 앱 재배포 여부, 양쪽 키·프로젝트·엔드포인트를 확인합니다.
- 아무 trace도 없음: `LANGSMITH_TRACING=true`, 유효한 API 키, 프로젝트 접근 권한과 네트워크를 확인합니다.

CLI와 원격 요청은 종료 전에 SDK의 대기 중 전송을 flush합니다. 추적 초기화·기록 오류는 경고하고 본 작업을 계속합니다. LangSmith 전송이 불가능해도 JSON 검토 결과는 별도로 저장됩니다. 현재 저장된 로그를 나중에 재전송하는 오프라인 큐는 없습니다.

## 5. 관련 코드

- [tracing.py](../exam_checker/tracing.py): 추적 활성화, span, 본문 기록, 헤더 전달, flush.
- [configure_tracing.py](../scripts/configure_tracing.py): Modal Secret 생성·갱신.
- [modal_client.py](../exam_checker/cloud/modal_client.py): 부모 trace 헤더를 원격 호출에 전달.
- [modal_app/app.py](../modal_app/app.py): Secret 연결과 원격 trace 복원.
- [modal_app/model.py](../modal_app/model.py): 다운로드·생성·응답 파싱 추적.

공식 참고: [사용자 코드 추적](https://docs.langchain.com/langsmith/annotate-code), [분산 추적](https://docs.langchain.com/langsmith/distributed-tracing).
