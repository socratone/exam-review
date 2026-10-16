# Exam Checker

CLI 실행부터 로컬 전처리, Modal 추론, 결과 저장까지의 흐름과 Mermaid 차트는 [CLI 실행 흐름](docs/cli-flow.md)을 참고하세요.

시험지 PDF를 로컬 CPU에서 전처리하는 CLI입니다. 로컬 PDF 전처리, Modal GPU 연결 검사, Qwen 첫 페이지 AI 검토를 지원합니다.

- PDF 경로·형식·암호 보호 여부 검증
- 페이지별 텍스트 추출과 PNG 렌더링 (기본 160 DPI)
- 텍스트가 부족한 페이지 표시
- 성공·오류 종료 시 임시 이미지 정리

기본 실행은 전처리 요약만 출력합니다. `--review`로 첫 페이지를 Qwen으로 검토하고 JSON을 저장할 수 있습니다. 문항 분할, 정답 키 검증, 의심 항목 재검증, 전체 시험지 검토와 Markdown 보고서는 지원하지 않습니다. OCR은 실행하지 않습니다. 영숫자·한글 등 문자/숫자가 20자 미만인 페이지를 시각 검토 대상으로 표시하며, 이는 스캔 여부의 확정 판정은 아닙니다.

## Docker Compose 실행

Docker Desktop 또는 Docker Engine과 Compose가 필요합니다.

```bash
docker compose build
# PDF를 data/ 폴더에 넣은 뒤 실행
docker compose run --rm exam-checker /data/sample.pdf
```

호스트의 `data/`가 컨테이너의 `/data`에 읽기 전용으로 연결됩니다. 호스트 절대 경로 대신 `/data/...` 경로를 전달하세요. `.env` 없이도 기본값으로 실행됩니다.

```bash
cp .env.example .env
# .env에서 EXAM_CHECKER_RENDER_DPI 수정 (72–300)
docker compose run --rm exam-checker /data/sample.pdf --dpi 180 --verbose
docker compose run --rm exam-checker --help
```

`--dpi`가 환경변수보다 우선합니다. PNG는 컨테이너 임시 디렉터리에만 생성되며 종료 시 제거됩니다. `output/`에 연결 검사와 AI 검토 JSON을 저장할 수 있습니다. 로그에는 시험지 본문을 출력하지 않습니다. 처리 실패 시 종료 코드는 1이며 잘못된 CLI 옵션은 2입니다.

## 로컬 개발과 테스트

Python 3.12 이상과 [uv](https://docs.astral.sh/uv/)를 사용합니다. Docker 이미지는 Python 3.12로 실행합니다.

```bash
uv sync --frozen
uv run python scripts/create_sample.py
uv run exam-checker data/sample.pdf
uv run pytest
```

샘플 생성기는 실제 시험지 대신 텍스트 페이지와 도형만 있는 페이지를 생성합니다. 기존 `data/sample.pdf`는 덮어쓰지 않습니다. 테스트는 합성 PDF로 추출, 렌더 크기, 암호 보호, 잘못된 입력, DPI 설정, 오류 시 정리를 검증하며 외부 서비스가 필요하지 않습니다.

PyMuPDF의 공식 [텍스트 추출 및 이미지 렌더링 API](https://pymupdf.readthedocs.io/en/latest/page.html)를 사용합니다. 로컬 AI 모델은 실행하지 않습니다.

## Modal GPU 연결 검사

`--modal-check`는 첫 페이지의 텍스트와 PNG만 Modal로 보내고 실제 CUDA 연산 `2² = 4`를 실행합니다. 반환된 GPU 정보와 페이지 메타데이터를 Pydantic으로 검증하여 JSON에 저장합니다. **이 연결 검사 옵션은 Qwen 추론을 수행하지 않습니다. AI 검토에는 아래의 `--review`를 사용하세요.** 원본 PDF를 업로드하거나 시험지 데이터를 Volume에 저장하지 않으며, 본문과 이미지를 로그에 출력하지 않습니다.

### 사용자가 최초 1회 할 일

1. [Modal](https://modal.com/)에 가입하고 사용할 workspace에서 GPU 사용이 가능한지 확인합니다. 실행 시 계정의 크레딧/요금이 적용됩니다.
2. 프로젝트 디렉터리의 터미널에서 다음을 실행하고 브라우저에서 인증합니다. 토큰을 채팅에 전달할 필요는 없습니다.

```bash
.venv/bin/modal token new
```

새 환경이라면 먼저 `uv sync --frozen`을 실행하세요. 인증은 호스트의 `~/.modal.toml`에 저장됩니다. Docker용 추가 Compose 파일은 이 파일만 읽기 전용으로 마운트합니다.

3. 이미지를 빌드하고 Modal 함수를 배포합니다.

```bash
docker compose build
docker compose -f docker-compose.yml -f docker-compose.modal.yml run --rm \
  --entrypoint modal exam-checker deploy -m modal_app.app
```

4. 합성 샘플로 GPU 연결을 검사합니다.

```bash
docker compose -f docker-compose.yml -f docker-compose.modal.yml run --rm \
  exam-checker /data/sample.pdf --modal-check \
  --output /output/sample.gpu-check.json
```

샘플이 없으면 `uv run python scripts/create_sample.py`로 만듭니다. 성공하면 `GPU check passed`가 표시되고 호스트의 `output/sample.gpu-check.json`에 `cuda_available: true`, `computation_result: 4.0`, GPU 이름이 기록됩니다. 첫 배포는 클라우드 PyTorch 이미지 빌드로 시간이 걸릴 수 있습니다.

`.env`의 `EXAM_CHECKER_GPU`는 배포 시 적용되며 기본값은 `L4`입니다. 변경 후 재배포하세요. `EXAM_CHECKER_MODAL_APP`은 배포와 호출에 동일한 값을 사용해야 합니다. 기본은 `exam-checker`입니다. 여러 프로필을 쓰는 경우 호스트에서 `modal profile activate PROFILE`로 배포·호출에 사용할 프로필을 선택하세요.

인증 오류는 `modal token new`, 앱을 찾지 못하는 오류는 동일 workspace/environment로 재배포하여 해결합니다. 타임아웃 또는 GPU 오류는 Modal dashboard의 해당 실행 로그를 확인하세요. 실패 시 CLI는 1로 종료하며 임시 이미지는 삭제됩니다. 클라우드 컨테이너는 최소 0개·최대 1개, 짧은 유휴 종료 시간으로 설정했습니다.

구현은 공식 [배포된 함수 호출 및 인증](https://modal.com/docs/guide/trigger-deployed-functions), [GPU 설정](https://modal.com/docs/guide/gpu)을 따릅니다. 로컬 테스트의 모의 호출 통과는 실제 GPU 실행 성공을 의미하지 않습니다.


## Qwen 첫 페이지 검토

기존 Modal 인증을 그대로 사용합니다. 코드 업데이트 후 이미지를 빌드하고 재배포하세요.

```bash
docker compose build
docker compose -f docker-compose.yml -f docker-compose.modal.yml run --rm \
  --entrypoint modal exam-checker deploy -m modal_app.app

docker compose -f docker-compose.yml -f docker-compose.modal.yml run --rm \
  exam-checker /data/sample.pdf --review \
  --output /output/sample.page-review.json
```

기본 모델은 `Qwen/Qwen3-VL-8B-Instruct`, GPU는 L4입니다. **첫 페이지만** 검토하며 기본으로 네이티브 텍스트와 페이지 PNG를 함께 보냅니다. 결과의 `kind`는 `unverified_page_review`이고 각 의심 항목의 `verified`는 `null`입니다. 한 번의 모델 판단으로 정답 오류를 확정하지 않습니다. 빈 페이지·불완전한 문항은 `limitations`를 확인하세요.

텍스트만으로 검토하려면 다음과 같이 실행합니다. 추출된 텍스트가 없는 페이지는 이 모드로 검토할 수 없습니다.

```bash
docker compose -f docker-compose.yml -f docker-compose.modal.yml run --rm \
  exam-checker /data/sample.pdf --review --text-only \
  --output /output/sample.text-review.json
```

모델은 `--model` 또는 `.env`의 `EXAM_CHECKER_MODEL`로 변경할 수 있습니다. 현재 로더는 Qwen3-VL 계열을 지원합니다. GPU 메모리가 부족하면 `--model Qwen/Qwen3-VL-4B-Instruct`를 사용하거나 GPU 설정 변경 후 재배포하세요. `--review`와 `--modal-check`는 함께 사용할 수 없습니다.

모델 다운로드는 최초 캐시 미스 때 실행됩니다. Modal Volume `exam-checker-model-cache`에는 가중치·tokenizer·설정 등 모델 파일을 보관합니다. 시험지 텍스트·이미지는 캐시에 기록하지 않습니다. 각 컨테이너는 모델을 한 번 로딩하며 30초 유휴 후 종료 대상으로 전환됩니다. 첫 호출은 다운로드와 로딩으로 수 분 이상 걸릴 수 있습니다. GPU 실행과 Volume 저장에는 Modal 요금이 적용됩니다.

초기 검증용 제한: 텍스트 30,000자, PNG 20 MB, 모델 입력 8,192토큰, 생성 2,048토큰입니다. GPU 메모리를 제한하기 위해 이미지는 긴 변 최대 1,280픽셀로 축소하므로 작은 글씨·복잡한 도표는 누락될 수 있습니다. 한도를 넘기거나 모델 JSON이 스키마에 맞지 않으면 실패로 종료하고 새 보고서를 쓰지 않습니다. 기존 출력 파일이 있으면 실패 시 그대로 남으므로 종료 코드도 확인하세요. 원문 모델 응답은 로그에 출력하지 않습니다.

구현은 [Qwen 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)와 [Modal 모델 캐시 가이드](https://modal.com/docs/guide/model-weights)를 참고합니다. 모델 추론 라이브러리는 Modal 이미지에만 설치하며 로컬에서는 추론하지 않습니다.

### 현재 검증 상태와 품질 한계

- 로컬 테스트 44개 통과: JSON 스키마, 잘못된 응답, 전송 모드, CLI 오류와 임시 파일 정리.
- Modal L4에서 Qwen3-VL-8B-Instruct의 이미지 포함 및 텍스트 전용 호출과 JSON 저장을 실제 확인했습니다. 캐시 재사용 시 가중치를 다시 내려받지 않는 것도 확인했습니다.
- 정상 샘플 `2 + 2`, 선택지 `3 / 4 / 5`에서도 정답이 없거나 정답 표시가 필요하다는 오탐이 발생했습니다. 프롬프트 보강만으로 해결되지 않았으며 텍스트 모드에서도 재실행 시 오탐이 나타났습니다. **현재는 연결·추론 경로 검증 단계이며 판정 정확도가 검증된 도구가 아닙니다.** `confidence`는 모델의 자기 평가로 정확도를 보장하지 않습니다. 판정을 신뢰하려면 독립적인 재검증과 문항별 검증이 필요합니다.

- 정답이 없는 합성 샘플 `2 + 2`, 선택지 `3 / 5 / 6`에서는 `C. 6`이라고 잘못 계산하고 오류를 누락했습니다. 결과는 `output/sample-no-valid-answer.page-review.json`에 남겼습니다. 현재 검증은 추론 경로의 동작 확인이며 정확도 합격 판정이 아닙니다.
