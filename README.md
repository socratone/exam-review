# Exam Checker

시험지 PDF를 로컬 CPU에서 전처리하는 CLI입니다. 현재 `plan.md`의 첫 작업인 Phase 1·2를 구현했습니다.

- PDF 경로·형식·암호 보호 여부 검증
- 페이지별 텍스트 추출과 PNG 렌더링 (기본 160 DPI)
- 텍스트가 부족한 페이지 표시
- 성공·오류 종료 시 임시 이미지 정리

현재는 전처리 요약을 터미널에 출력합니다. 문항 분할, 정답 검증, Modal AI 추론, JSON/Markdown 검토 보고서는 후속 단계입니다. OCR은 실행하지 않습니다. 영숫자·한글 등 문자/숫자가 20자 미만인 페이지를 시각 검토 대상으로 표시하며, 이는 스캔 여부의 확정 판정은 아닙니다.

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

`--dpi`가 환경변수보다 우선합니다. PNG는 컨테이너 임시 디렉터리에만 생성되며 종료 시 제거됩니다. `output/`은 향후 보고서용으로 준비되어 있습니다. 로그에는 시험지 본문을 출력하지 않습니다. 처리 실패 시 종료 코드는 1이며 잘못된 CLI 옵션은 2입니다.

## 로컬 개발과 테스트

Python 3.12 이상과 [uv](https://docs.astral.sh/uv/)를 사용합니다. Docker 이미지는 Python 3.12로 실행합니다.

```bash
uv sync --frozen
uv run python scripts/create_sample.py
uv run exam-checker data/sample.pdf
uv run pytest
```

샘플 생성기는 실제 시험지 대신 텍스트 페이지와 도형만 있는 페이지를 생성합니다. 기존 `data/sample.pdf`는 덮어쓰지 않습니다. 테스트는 합성 PDF로 추출, 렌더 크기, 암호 보호, 잘못된 입력, DPI 설정, 오류 시 정리를 검증하며 외부 서비스가 필요하지 않습니다.

PyMuPDF의 공식 [텍스트 추출 및 이미지 렌더링 API](https://pymupdf.readthedocs.io/en/latest/page.html)를 사용합니다. 로컬 AI 모델이나 클라우드 호출은 아직 없습니다.
