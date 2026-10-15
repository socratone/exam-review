# Exam Checker — Implementation Plan

## 1. Goal

개인용 시험지 검증 도구를 만든다.

사용자는 로컬 PC에서 PDF 파일 경로를 CLI로 전달하고, Docker Compose 환경에서 PDF를 전처리한다. AI 추론은 로컬 GPU를 사용하지 않고 Modal의 클라우드 GPU에서 수행한다.

최종 목표는 시험지 PDF에서 문항별 문제를 찾아 다음과 같은 결과를 반환하는 것이다.

- 문항 누락 / 번호 중복
- 보기 누락 / 보기 번호 중복
- 정답 오류 가능성
- 복수 정답 가능성
- 문제 자체가 성립하지 않는 경우
- 문제와 보기 사이의 모순
- 표현 / 맞춤법 / 문장 오류
- 그림, 표, 그래프와 문제의 불일치
- 시험지 전체 수준의 중복 / 불일치 / 이상 패턴

현재는 개인용 CLI 도구이므로 웹 UI, DB, 사용자 인증, 장기 저장 기능은 만들지 않는다.

---

## 2. Core Architecture

```text
Local PC
┌────────────────────────────────────┐
│ Docker Compose                     │
│                                    │
│  exam-checker service              │
│                                    │
│  Python CLI                        │
│       ↓                            │
│  PyMuPDF                           │
│       ↓                            │
│  PDF text extraction               │
│  page image rendering              │
│  basic deterministic validation    │
│       ↓                            │
│  Modal Python SDK                  │
└───────────────┬────────────────────┘
                │
                │ text + selected images
                ▼
Cloud
┌────────────────────────────────────┐
│ Modal                              │
│                                    │
│ NVIDIA Cloud GPU                   │
│       ↓                            │
│ Qwen Vision-Language Model         │
│       ↓                            │
│ question review                    │
│ suspicious issue verification      │
│ global review                      │
└───────────────┬────────────────────┘
                │
                ▼
Local PC

exam.review.json
exam.review.md
```

### Responsibilities

#### Local

- CLI argument 처리
- PDF 파일 존재 여부 검증
- PDF 텍스트 추출
- PDF 페이지 이미지 생성
- 가능한 범위에서 문항 구조 분석
- 코드로 검출 가능한 오류 검사
- Modal 호출
- 결과 JSON / Markdown 저장

#### Modal

- 클라우드 GPU에서 VLM 로딩
- 문항별 의미 기반 검증
- 의심 항목 재검증
- 전체 시험지 수준 검증
- JSON 형식 결과 반환

---

## 3. Important Constraints

### Do not add yet

현재 MVP에서는 아래 기능을 넣지 않는다.

- Next.js
- 웹 UI
- PostgreSQL / SQLite 등 DB
- Supabase
- S3 / R2
- Redis
- Kafka
- Kubernetes
- 별도 API 서버
- 사용자 로그인
- 시험지 이력 관리
- Vector DB
- Fine-tuning

필요성이 생긴 시점에 추가한다.

### No local AI inference

로컬 머신에서는 AI 모델을 실행하지 않는다.

로컬에서는 CPU 기반 PDF 처리만 수행한다.

```text
Local CPU
  → PDF parsing
  → image rendering
  → deterministic validation

Modal Cloud GPU
  → VLM inference
```

---

## 4. Technology Stack

### Local

- Python 3.12
- Docker
- Docker Compose
- uv preferred
- Typer
- PyMuPDF
- Pillow
- Pydantic
- Modal Python SDK

### Cloud

- Modal
- NVIDIA GPU
- PyTorch
- Transformers or vLLM
- Qwen Vision-Language Model

### Initial model candidate

Start with a Qwen Vision-Language model suitable for document/image understanding.

Preferred starting point:

```text
Qwen3-VL-8B-Instruct
```

If VRAM or compatibility becomes an issue, evaluate a quantized variant or another Qwen VL checkpoint.

Do not hard-code the model throughout the codebase. Keep model ID configurable.

---

## 5. Docker Compose Strategy

Docker Compose is used to make local execution reproducible.

Only the local CLI runs in Docker Compose.

Modal GPU execution remains in Modal cloud.

### docker-compose.yml concept

```yaml
services:
  exam-checker:
    build:
      context: .
      dockerfile: Dockerfile
    working_dir: /app
    volumes:
      - ./:/app
      - ./data:/data
      - ./output:/output
    env_file:
      - .env
    entrypoint: ["python", "-m", "exam_checker.cli"]
```

Expected usage:

```bash
docker compose run --rm exam-checker /data/exam.pdf
```

With answer file:

```bash
docker compose run --rm exam-checker \
  /data/exam.pdf \
  --answer /data/answers.json
```

With explicit output path:

```bash
docker compose run --rm exam-checker \
  /data/exam.pdf \
  --output /output/exam-review
```

---

## 6. Proposed Project Structure

```text
exam-checker/
│
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── README.md
├── plan.md
│
├── exam_checker/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   │
│   ├── pdf/
│   │   ├── __init__.py
│   │   ├── extractor.py
│   │   ├── renderer.py
│   │   └── parser.py
│   │
│   ├── validation/
│   │   ├── __init__.py
│   │   └── deterministic.py
│   │
│   ├── cloud/
│   │   ├── __init__.py
│   │   └── modal_client.py
│   │
│   ├── output/
│   │   ├── __init__.py
│   │   ├── markdown.py
│   │   └── json_writer.py
│   │
│   └── schemas/
│       ├── __init__.py
│       ├── exam.py
│       └── review.py
│
├── modal_app/
│   ├── __init__.py
│   ├── app.py
│   ├── model.py
│   ├── reviewer.py
│   ├── verifier.py
│   ├── global_reviewer.py
│   └── prompts.py
│
├── data/
│   └── .gitkeep
│
├── output/
│   └── .gitkeep
│
└── tests/
    ├── test_pdf_parser.py
    ├── test_deterministic_validation.py
    └── test_output.py
```

---

## 7. CLI UX

### Basic usage

```bash
docker compose run --rm exam-checker /data/exam.pdf
```

Expected terminal output:

```text
Exam Checker
============

PDF: exam.pdf
Pages: 8
Questions detected: 25

[1/4] Extracting PDF...
[2/4] Running deterministic checks...
[3/4] Reviewing questions on Modal GPU...
[4/4] Writing report...

Summary
-------
OK: 22
Warning: 2
Error: 1

Output:
/output/exam.review.json
/output/exam.review.md
```

### CLI options

Initial options:

```text
PDF_PATH                 required
--answer PATH            optional answer key
--output PATH            output base path
--model MODEL_ID         optional model override
--pages RANGE            optional page range
--verbose                verbose logging
--no-global-review       skip whole-exam review
```

Potential later options:

```text
--only QUESTION_NUMBERS
--confidence-threshold
--save-page-images
--keep-temp
```

---

## 8. PDF Processing Strategy

### Step 1 — Validate input

- file exists
- extension is `.pdf`
- file can be opened by PyMuPDF
- page count > 0

### Step 2 — Extract native text

Use PyMuPDF first.

```python
import pymupdf

doc = pymupdf.open(pdf_path)

for page in doc:
    text = page.get_text()
```

Do not run OCR by default.

If native text extraction is empty or unusable, mark the page as image-heavy / scanned.

OCR support can be added later only if necessary.

### Step 3 — Render pages to images

Render pages locally with PyMuPDF.

Initial target:

```text
150–180 DPI
```

Avoid sending extremely large page images unless required.

### Step 4 — Build page payload

Each page should be represented approximately as:

```python
PageData(
    page_number=1,
    text="...",
    image_path="/tmp/page-1.png",
)
```

### Step 5 — Detect questions

Initial strategy should be simple and replaceable.

Try to detect patterns such as:

```text
1.
2.
3.

1)
2)
3)

문제 1
문항 1
```

Do not over-engineer question segmentation initially.

If question segmentation confidence is low, Modal VLM can receive the full page and identify question boundaries.

---

## 9. Deterministic Validation

Run local validation before invoking AI.

Examples:

- duplicated question number
- missing question number
- duplicated choice number
- missing choice number
- empty stem
- invalid answer index
- duplicate provided answers
- question without choices when expected

Example:

```text
1
2
3
5
6
```

Detect:

```text
Question 4 appears to be missing.
```

Example choices:

```text
①
②
④
⑤
```

Detect:

```text
Choice ③ appears to be missing.
```

Principle:

```text
Can be proven with normal code
→ do not spend GPU tokens on it

Requires semantic judgment
→ send to VLM
```

---

## 10. AI Review Pipeline

Do not submit the whole PDF with one prompt and trust one answer.

Use a staged pipeline.

```text
PDF
 ↓
Local extraction
 ↓
Question/page structure
 ↓
Deterministic validation
 ↓
Question review
 ↓
Suspicious issue verification
 ↓
Global exam review
 ↓
Final report
```

### Stage A — Question review

For each question, inspect:

1. Does the question make sense?
2. Is at least one valid answer possible?
3. Could multiple choices be correct?
4. Is the wording ambiguous?
5. Is there contradiction between stem and choices?
6. Is there a spelling / expression issue?
7. Does the referenced image/table/graph match the question?
8. If an answer key exists, does the supplied answer appear valid?

Return structured JSON only.

### Stage B — Suspicious issue verification

Do not run a second full review for every question.

Only verify questions that Stage A flags.

```text
25 questions
 ↓
Stage A
 ↓
22 normal
3 suspicious
 ↓
Stage B only for 3 suspicious questions
```

Verifier must evaluate the reviewer's claim independently.

### Stage C — Global exam review

Run once for the entire exam.

Check:

- duplicated questions
- nearly identical questions
- answer distribution anomaly
- inconsistent terminology
- one question revealing another answer
- numbering inconsistency
- subject/title mismatch
- inconsistent instructions

Allow `--no-global-review` to disable this stage.

---

## 11. Suggested Review Schema

### IssueType

Possible enum values:

```text
MISSING_QUESTION
DUPLICATE_QUESTION
MISSING_CHOICE
DUPLICATE_CHOICE
INVALID_ANSWER
MULTIPLE_ANSWER
NO_VALID_ANSWER
AMBIGUOUS_WORDING
CONTRADICTION
SPELLING_OR_GRAMMAR
IMAGE_MISMATCH
TABLE_MISMATCH
GRAPH_MISMATCH
DUPLICATE_CONTENT
GLOBAL_INCONSISTENCY
OTHER
```

### Pydantic models

```python
class ReviewIssue(BaseModel):
    type: IssueType
    severity: Literal["low", "medium", "high"]
    description: str
    evidence: str
    suggestion: str | None = None
    confidence: float
    verified: bool | None = None


class QuestionReview(BaseModel):
    question_number: int | str
    page_number: int
    status: Literal["ok", "warning", "error"]
    issues: list[ReviewIssue]


class ExamSummary(BaseModel):
    total_questions: int
    ok_count: int
    warning_count: int
    error_count: int


class ExamReview(BaseModel):
    filename: str
    model: str
    summary: ExamSummary
    questions: list[QuestionReview]
    global_issues: list[ReviewIssue]
```

---

## 12. Modal Design

Modal owns all AI inference.

### app.py

Responsibilities:

- define Modal app
- define GPU image
- configure model cache
- expose remote functions

Concept:

```python
import modal

app = modal.App("exam-checker")

image = (
    modal.Image.debian_slim()
    .pip_install(
        "torch",
        "transformers",
        "accelerate",
        "pillow",
        "pydantic",
    )
)

@app.function(
    image=image,
    gpu="L4",
    timeout=1800,
)
def review_question(payload: dict) -> dict:
    ...
```

Do not assume exact Modal SDK syntax without checking current documentation during implementation.

### GPU

Start with:

```text
L4 24GB
```

If the selected model does not fit or performance is insufficient, evaluate:

- quantization
- larger GPU
- smaller VLM

Do not optimize before measuring.

---

## 13. Model Loading / Cold Start

Avoid downloading the model weights on every invocation.

Use one of the supported Modal caching approaches.

Desired behavior:

```text
First deployment / cache miss
  → download model
  → cache model weights

Later invocation
  → load cached weights
  → move model to GPU
  → infer
```

Cold start is acceptable because usage is rare.

Cost efficiency is more important than always-on latency.

---

## 14. Data Sent to Cloud

The original PDF does not need to be uploaded as a persistent cloud file.

Preferred data flow:

```text
Local PDF
 ↓
local parsing
 ↓
text + required page image
 ↓
Modal
 ↓
result JSON
```

Minimize cloud payload where possible.

Do not persist the PDF in Modal storage unless a concrete implementation need appears.

Temporary page images should be deleted after completion.

---

## 15. Answer Key Support

Answer key support is optional but valuable.

Initial supported formats can be JSON only.

Example:

```json
{
  "1": "3",
  "2": "2",
  "3": "5"
}
```

Later support may include:

- txt
- csv
- separate answer PDF

When an answer exists:

```text
VLM solves question
       ↓
model answer
       ↓
compare with provided answer
       ↓
if mismatch
       ↓
verification pass
```

Do not mark a provided answer as wrong based on a single LLM pass.

---

## 16. Output Format

Always produce machine-readable JSON.

Optionally produce a human-friendly Markdown report.

### JSON

```text
output/exam.review.json
```

### Markdown

```text
output/exam.review.md
```

Markdown should prioritize problematic questions.

Example:

```markdown
# Exam Review

- Questions: 25
- OK: 22
- Warning: 2
- Error: 1

## Question 3 — Warning

**Issue:** Multiple answers may be valid.

**Evidence:** ...

**Confidence:** 0.91

**Suggestion:** ...
```

Normal questions do not need verbose output.

---

## 17. Environment Variables

Create `.env.example`.

Possible values:

```env
MODAL_PROFILE=
EXAM_CHECKER_MODEL=Qwen/Qwen3-VL-8B-Instruct
EXAM_CHECKER_GPU=L4
EXAM_CHECKER_RENDER_DPI=160
EXAM_CHECKER_CONFIDENCE_THRESHOLD=0.7
```

Modal authentication secrets must not be committed.

Add `.env` and credential files to `.gitignore`.

---

## 18. Logging

Use simple structured logs.

Avoid excessive logging of actual exam content.

Good:

```text
INFO pdf opened pages=8
INFO page rendered page=1
INFO questions detected count=25
INFO modal review started question=3
INFO verification started question=3
```

Avoid:

```text
INFO full_question_text="..."
```

unless `--verbose` explicitly requests debugging output.

---

## 19. Error Handling

Handle these cases explicitly:

- invalid PDF
- password-protected PDF
- zero text extraction
- scanned PDF
- Modal authentication failure
- Modal timeout
- GPU OOM
- model load failure
- invalid model JSON response
- answer file parse failure

CLI should exit with a non-zero code on fatal errors.

Partial review results may still be written when some questions fail.

---

## 20. Testing Strategy

### Unit tests

Test locally without Modal whenever possible.

Focus on:

- PDF input validation
- question-number parser
- choice-number parser
- missing number detection
- duplicate detection
- output formatting
- answer key parser
- Pydantic validation

### Fixtures

Add synthetic small PDF fixtures if practical.

Do not commit real confidential exam files.

### Modal tests

Keep cloud integration tests separate.

Potential command:

```bash
pytest -m "not modal"
```

and optionally:

```bash
pytest -m modal
```

---

## 21. Implementation Phases

### Phase 1 — CLI + Docker Compose

Create:

- `Dockerfile`
- `docker-compose.yml`
- `pyproject.toml`
- basic Typer CLI

Acceptance criteria:

```bash
docker compose run --rm exam-checker /data/sample.pdf
```

opens the file and prints metadata.

### Phase 2 — Local PDF pipeline

Implement:

- text extraction
- page rendering
- temporary directory handling
- basic question detection

Acceptance criteria:

- prints page count
- prints extracted text length
- renders page images
- removes temporary data after run

### Phase 3 — Deterministic validation

Implement:

- missing question number
- duplicate question number
- missing choice
- duplicate choice
- answer-key range validation

Acceptance criteria:

Can validate synthetic cases without any AI call.

### Phase 4 — Modal connection

Implement:

- Modal app
- cloud image
- remote hello/inference test
- local Modal client

Acceptance criteria:

Local Docker CLI can invoke Modal and receive structured JSON.

### Phase 5 — VLM inference

Implement model loading and single-question review.

Acceptance criteria:

- text-only question can be reviewed
- image-supported question can be reviewed
- response validates against Pydantic schema

### Phase 6 — Reviewer + Verifier

Implement:

- first review
- verification only for flagged issues
- confidence handling

Acceptance criteria:

Normal questions use one inference path.
Flagged questions receive a second independent validation.

### Phase 7 — Global review

Implement one whole-exam consistency pass.

Acceptance criteria:

Can detect at least one deliberately duplicated question in a fixture.

### Phase 8 — Reports

Implement:

- `.review.json`
- `.review.md`
- summary counts

Acceptance criteria:

CLI produces both reports by default.

---

## 22. MVP Definition of Done

The MVP is complete when this works:

```bash
docker compose run --rm exam-checker \
  /data/exam.pdf \
  --answer /data/answers.json
```

and the program:

1. opens the local PDF
2. extracts text locally
3. renders required pages locally
4. runs deterministic checks locally
5. sends only required text/images to Modal
6. performs VLM inference on cloud GPU
7. verifies suspicious AI findings
8. optionally performs global exam review
9. returns results to local container
10. writes:

```text
/output/exam.review.json
/output/exam.review.md
```

No DB, web server, object storage, or local AI model is required.

---

## 23. Codex Working Instructions

When continuing this project in Codex:

1. Read this `plan.md` first.
2. Inspect the current repository before changing files.
3. Implement one phase at a time.
4. Do not introduce infrastructure excluded in section 3 without a concrete requirement.
5. Keep PDF processing local.
6. Keep AI inference on Modal cloud GPU.
7. Prefer deterministic validation over AI when possible.
8. Keep AI responses schema-driven with Pydantic.
9. Do not trust a single AI judgment for serious errors; use verifier logic.
10. Avoid persisting exam data in cloud services.
11. Keep model, GPU type, DPI, and thresholds configurable.
12. Add tests for each deterministic parser/validator before expanding AI complexity.
13. If current Modal / Transformers APIs differ from examples in this document, use current official APIs and preserve the architecture rather than blindly copying pseudocode.
14. Do not start by implementing every planned feature. Build the smallest end-to-end path first.

Recommended first vertical slice:

```text
CLI
 ↓
PDF open
 ↓
first page render
 ↓
Modal GPU call
 ↓
Qwen VLM simple review
 ↓
JSON result
```

After that path works reliably, add question segmentation, deterministic validators, verifier, and global review.

---

## 24. First Codex Task

Start with Phase 1 and Phase 2 only.

Create a runnable Docker Compose based Python project where:

```bash
docker compose run --rm exam-checker /data/sample.pdf
```

will:

- validate the supplied path
- open the PDF with PyMuPDF
- print filename and page count
- extract text per page
- render each page to a temporary PNG at configurable DPI
- print a short summary
- clean temporary files on exit

Do not integrate Modal yet in the first task.

Once the local PDF pipeline is confirmed, proceed to Phase 4 with the smallest possible Modal cloud GPU proof-of-concept.
