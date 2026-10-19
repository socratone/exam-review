# 실행 순서로 읽는 코드

이 문서는 **사용자가 CLI를 실행한 뒤 실제로 호출되는 순서**에 맞춰 파일, 함수, 데이터 구조를 설명합니다. 전체 동작과 사용법은 [CLI 실행 흐름](cli-flow.md)을 참고하세요. 여기서는 `--review` 경로를 중심으로 읽고, GPU 연결 검사 경로는 별도로 설명합니다.

## 1. 실행 환경 준비: uv와 패키지 설정

[pyproject.toml](../pyproject.toml)은 Python 버전, 의존성, pytest 설정, `exam-checker` 명령을 정의합니다. [uv.lock](../uv.lock)은 구체적인 버전을 고정합니다.

```bash
uv sync --frozen
uv run exam-checker data/sample.pdf --review
```

`uv run`이 가상환경에서 `exam_checker.cli:app`을 실행합니다. `python -m exam_checker.cli`도 같은 앱을 호출합니다. 로컬 의존성에는 PyMuPDF, Typer, Pydantic, Modal SDK, LangSmith, python-dotenv가 포함되며 PyTorch와 Transformers는 Modal 이미지에만 설치합니다.

[.env.example](../.env.example)은 실행 설정 예시입니다. API 키를 가진 `.env`는 버전 관리에서 제외됩니다.

## 2. 진입점: `cli.py`의 `app`과 `main()`

파일: [exam_checker/cli.py](../exam_checker/cli.py)

```python
app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)

@app.command()
@traced("exam_checker.run", root=True)
def main(...):
    ...

if __name__ == "__main__":
    app()
```

`app()`이 Typer의 인자 해석을 시작하고 `main()`으로 넘깁니다. 명령이 하나이므로 별도의 `main` 하위 명령 없이 PDF 경로를 바로 전달합니다.

`Annotated[Path, typer.Argument(...)]`는 필수 PDF 경로를, `typer.Option(...)`은 `--dpi`, `--review` 등의 옵션을 정의합니다. `Path`는 파일 경로 객체이며 이 타입으로 변환됐다는 사실만으로 파일 존재가 보장되지는 않습니다. 실제 PDF 검증은 뒤의 `open_pdf()`가 수행합니다.

`@traced` 래퍼가 `.env`를 읽고 루트 trace를 시작한 뒤 `main()`을 실행합니다. 종료 시 LangSmith 전송을 flush합니다. `main()`의 첫 작업은 다음과 같습니다.

1. `--verbose`에 따라 로그 수준을 정합니다.
2. 함께 사용할 수 없는 옵션을 거부합니다. 예를 들어 `--review`와 `--modal-check`는 동시에 사용할 수 없습니다.
3. 모드에 맞는 기본 JSON 경로를 계산합니다. `--output`이 있으면 해당 경로를 그대로 사용합니다.
4. 출력 경로가 입력 PDF를 덮어쓰는 경로인지 확인합니다.
5. `Settings.from_env(dpi)`로 설정을 읽습니다.

옵션 조합 오류는 `typer.BadParameter`로 전달되어 종료 코드 2가 됩니다. 이후 PDF 처리·클라우드 호출·저장 과정은 `try` 블록 안에서 실행됩니다.

## 3. 설정 읽기: `Settings.from_env()`

파일: [exam_checker/config.py](../exam_checker/config.py)

`Settings`는 Pydantic 모델이며 현재 `render_dpi`를 관리합니다.

```python
render_dpi: int = Field(default=160, ge=72, le=300)
```

`ge`, `le`는 각각 최솟값과 최댓값입니다. `from_env()`는 `--dpi`가 있으면 그 값을 선택하고, 없으면 `EXAM_CHECKER_RENDER_DPI`를 읽습니다. 환경변수도 없으면 문자열 `"160"`을 사용합니다. Pydantic이 정수로 변환하고 범위를 검사합니다.

모델 ID는 이 클래스에서 관리하지 않습니다. AI 검토 분기에서 `--model`, `EXAM_CHECKER_MODEL`, `DEFAULT_MODEL` 순으로 선택합니다. Modal 앱 이름은 클라이언트에서, GPU 종류는 배포 코드에서 환경변수로 읽습니다.

## 4. 전처리 시작: `process_pdf()`와 `open_pdf()`

파일: [exam_checker/pdf/pipeline.py](../exam_checker/pdf/pipeline.py), [exam_checker/pdf/extractor.py](../exam_checker/pdf/extractor.py)

CLI는 다음 블록에 진입합니다.

```python
with process_pdf(pdf_path, settings) as pages:
    # 요약 출력, 선택적 원격 호출, 결과 저장
    ...
```

`process_pdf()`는 `@contextmanager`가 붙은 함수입니다. 단순히 목록을 반환하는 함수와 달리, `yield` 전후로 자원을 확보하고 정리하는 범위를 제공합니다.

실제 진입 순서는 다음과 같습니다.

```text
main()
  → process_pdf() 진입
    → open_pdf() 진입
      → 경로·PDF 검사
    → TemporaryDirectory 생성
    → 페이지별 처리
    → yield pages
  → main()의 with 블록 본문 실행
```

`open_pdf(path)`는 파일 존재와 확장자를 확인한 뒤 `pymupdf.open(path)`를 호출합니다. 열린 문서가 PDF인지, 암호가 필요한지, 페이지가 있는지도 검사합니다. 실패 시 `PDFError`를 발생시켜 CLI가 사용자에게 오류를 안내할 수 있도록 합니다.

`with document:`는 `yield document` 이후 호출자 처리가 끝나거나 예외가 전파되면 문서를 닫습니다. `process_pdf()`의 임시 디렉터리도 같은 방식으로 정리됩니다. 따라서 원격 호출이 진행되는 동안에는 문서와 PNG가 유지되고, 호출·저장이 끝난 뒤 정리됩니다.

## 5. 모든 페이지 처리: 텍스트, 이미지, `PageData`

관련 파일: [pipeline.py](../exam_checker/pdf/pipeline.py), [extractor.py](../exam_checker/pdf/extractor.py), [renderer.py](../exam_checker/pdf/renderer.py)

`process_pdf()`는 문서의 **모든 페이지**를 순회하며 다음 작업을 합니다.

### `extract_text(page)`

`page.get_text("text", sort=True)`로 네이티브 텍스트를 추출합니다. OCR 호출은 없습니다. 이미지로만 구성된 페이지는 텍스트가 비어 있을 수 있으며, 빈 텍스트 자체를 PDF 처리 실패로 간주하지 않습니다.

### `render_page(page, directory, dpi)`

`page.get_pixmap()`으로 지정 DPI의 RGB 이미지를 만들고 `alpha=False`로 투명 채널 없이 저장합니다. 파일 이름은 `page-1.png`처럼 1부터 시작합니다. PyMuPDF의 `page.number`는 0부터 시작하므로 코드에서 1을 더합니다.

함수 반환값은 이미지 바이트가 아니라 **생성한 파일의 `Path`**입니다.

### `PageData`

| 필드 | 값 |
| --- | --- |
| `page_number` | 1부터 시작하는 페이지 번호 |
| `text` | 추출한 텍스트 |
| `image_path` | 임시 PNG 파일 경로 |
| `needs_visual_review` | 문자·숫자가 20자 미만인지 여부 |

`str.isalnum()`으로 문자·숫자를 셉니다. 한글도 포함되며 공백·문장부호는 제외됩니다. 이 표시는 텍스트 부족을 알릴 뿐, 자동 OCR이나 추가 클라우드 호출을 일으키지 않습니다.

페이지 목록이 완성되면 `yield pages`로 CLI에 제어를 넘깁니다. 목록 안의 이미지 경로는 `with process_pdf(...)` 블록 안에서만 유효합니다. `--text-only`여도 이 공통 전처리에서는 PNG를 생성합니다.

## 6. CLI로 복귀: 요약과 모드 분기

파일: [exam_checker/cli.py](../exam_checker/cli.py)

`main()`은 페이지 수, 페이지별 텍스트 길이, 렌더링 수, 시각 검토 대상 수를 출력합니다. 시험지 본문을 터미널에 출력하지는 않습니다.

- 원격 옵션이 없으면 `with` 블록을 끝내고 정리·종료합니다.
- `--modal-check`이면 `check_gpu(pages[0])`를 호출합니다.
- `--review`이면 모델 ID를 선택하고 `review_page(pages[0], model_id, text_only=...)`를 호출합니다.

두 원격 분기 모두 `pages[0]`을 사용합니다. 전처리한 나머지 페이지를 자동으로 검토하지 않습니다.

## 7. AI 요청 만들기: `review_page()`와 요청 스키마

파일: [exam_checker/cloud/modal_client.py](../exam_checker/cloud/modal_client.py), [review_schema.py](../exam_checker/cloud/review_schema.py)

`review_page()`가 로컬 전처리와 클라우드 추론 사이를 연결합니다.

1. 텍스트 전용 모드인데 첫 페이지 텍스트가 비어 있으면 `CloudError`를 발생시킵니다.
2. `PageReviewRequest`를 생성합니다. 이미지 포함 모드에서는 `image_path.read_bytes()`로 PNG를 읽습니다.
3. 요청을 `model_dump()`로 Python 딕셔너리로 바꿉니다.
4. Modal SDK로 원격 메서드를 호출합니다.

```python
reviewer = modal.Cls.from_name(app_name, "PageReviewer")(model_id=model)
raw = reviewer.review.remote(request.model_dump(), trace_headers=trace_headers)
```

`from_name()`은 이미 배포된 클래스를 찾습니다. 여기서 로컬에 Qwen 모델을 생성하는 것이 아닙니다. `model_id`는 원격 클래스의 파라미터이며, `.remote()`가 데이터를 보내고 원격 결과를 기다립니다. 추적이 켜진 경우 부모 trace 헤더도 별도 인자로 보내며 API 키는 포함하지 않습니다. PDF 파일 경로 자체가 아니라 텍스트와 PNG 바이트를 보냅니다.

`PageReviewRequest`는 페이지 번호, 최대 30,000자의 텍스트, 선택적인 PNG 바이트를 정의합니다. PNG는 최대 20,000,000바이트입니다. 공통 부모 `StrictModel`의 `extra="forbid"`는 정의하지 않은 필드를 거부하고 `strict=True`는 암묵적 타입 변환을 엄격히 제한합니다.

## 8. 클라우드 실행 준비: `modal_app/app.py`

파일: [modal_app/app.py](../modal_app/app.py)

이 파일은 **별도 배포 명령을 실행할 때** Modal 앱과 실행 환경을 정의합니다. 일반 CLI의 `review_page()`가 이 파일을 로컬에서 호출해 즉석 배포하는 구조는 아닙니다.

| 정의 | 역할 |
| --- | --- |
| `app` | 앱 이름을 가진 `modal.App` |
| `base_image` | Python·PyTorch·Pillow·Pydantic 환경 |
| `image` | GPU 연결 검사용 환경과 로컬 소스 연결 |
| `model_cache` | `exam-checker-model-cache` Volume 핸들 |
| `vlm_image` | Transformers·Accelerate·torchvision, 캐시 환경변수, 추론 코드 추가 |
| `@app.cls(...)` | GPU·Volume·시간 제한·컨테이너 수를 지정해 `PageReviewer` 등록 |

`add_local_python_source()`는 의존성 설치와 환경변수 설정 뒤에 적용됩니다. 이 순서를 뒤집으면 Modal 이미지 빌드가 실패할 수 있습니다.

`PageReviewer.model_id`는 `modal.parameter()`로 정의되어 원격 클래스 생성 시 전달받습니다. `load()`는 `@modal.enter()`가 붙어 **새 컨테이너에서 한 번**, `review()`는 `@modal.method()`가 붙어 **각 요청마다** 실행됩니다. `@remote_traced`가 부모 trace 헤더를 복원하여 로컬 실행 아래에 연결하고 요청 종료 전에 전송을 flush합니다.

## 9. 최초 모델 로딩: `load()` → `load_model()`

파일: [modal_app/app.py](../modal_app/app.py), [modal_app/model.py](../modal_app/model.py)

`load()`는 `load_model(self.model_id, model_cache)`의 결과를 `self.model`, `self.processor`에 보관합니다.

`load_model()`은 다음 순서로 동작합니다.

1. 클라우드에서 PyTorch와 Hugging Face 관련 라이브러리를 import합니다.
2. `snapshot_download(model_id)`로 모델 파일 경로를 얻습니다. `HF_HOME=/model-cache` 설정으로 캐시 Volume을 사용합니다.
3. `cache_volume.commit()`을 호출합니다. 이후 GPU 로딩에 실패해도 받은 모델 파일을 재사용할 수 있도록 합니다.
4. `AutoProcessor.from_pretrained(path)`로 이미지·텍스트 전처리기를 생성합니다.
5. `Qwen3VLForConditionalGeneration.from_pretrained(...)`로 모델을 CUDA에 로딩합니다.
6. `.eval()`로 추론 모드로 바꾸고 모델과 processor를 반환합니다.

현재 로딩 설정은 `bfloat16`, `device_map="cuda"`, `attn_implementation="sdpa"`입니다. 모델 ID를 바꿀 수 있지만 로더 자체는 Qwen3-VL 계열을 대상으로 합니다.

캐시 재사용은 **파일 다운로드 재사용**입니다. 새 GPU 컨테이너에서는 파일을 GPU 메모리에 다시 로딩해야 합니다. 이미 모델을 로딩한 컨테이너를 재사용하면 `load()`를 다시 실행하지 않습니다.

## 10. 요청별 추론: `review()` → `infer()`

파일: [modal_app/app.py](../modal_app/app.py), [modal_app/model.py](../modal_app/model.py)

`PageReviewer.review(payload)`는 클라우드에서도 `PageReviewRequest.model_validate()`로 요청을 검사한 뒤 `infer()`를 호출합니다.

`infer()` 내부의 실행 순서는 다음과 같습니다.

1. **시스템 지시 구성**: 수학적 성립, 표현, 모호함, 시각 자료와의 일치를 검토하도록 지시합니다. 시험지 안의 문장은 지시가 아닌 검토 대상으로 취급하도록 하고, 응답에 `PageFindings.model_json_schema()` 형식을 요구합니다.
2. **이미지 준비**: PNG가 있으면 `BytesIO`로 열어 PNG 형식을 확인하고 RGB로 변환합니다. 긴 변이 최대 1,280픽셀이 되도록 축소합니다.
3. **메시지 구성**: 시스템 지시와 사용자 데이터 메시지를 만들고, 이미지가 있을 때에는 이미지 위치를 나타내는 항목을 넣습니다.
4. **프롬프트 구성**: `processor.apply_chat_template(..., tokenize=False)`로 모델의 대화 형식에 맞는 문자열을 만듭니다.
5. **텐서 생성**: `processor(text=[prompt], images=..., return_tensors="pt")`로 텍스트와 이미지를 함께 처리하고 모델 장치로 옮깁니다.
6. **입력 길이 검사**: `input_ids`가 8,192토큰을 넘으면 실패합니다.
7. **생성**: `torch.inference_mode()` 안에서 최대 2,048토큰을 생성합니다. `do_sample=False`로 샘플링을 사용하지 않습니다.
8. **응답 분리**: 생성 결과에서 입력 프롬프트에 해당하는 토큰을 잘라내고, 새로 생성한 토큰만 문자열로 디코딩합니다.
9. **응답 검사**: `parse_findings(raw)`로 JSON을 검증한 뒤 `PageFindings`를 반환합니다.

정답을 코드로 계산하는 함수는 이 경로에 없습니다. JSON 스키마를 프롬프트에 넣는 것도 모델 출력의 정확성이나 형식을 강제로 보장하는 장치가 아니므로 생성 후 검증이 별도로 필요합니다.

## 11. AI 응답 해석: `parse_findings()`와 결과 모델

파일: [exam_checker/cloud/review_schema.py](../exam_checker/cloud/review_schema.py)

| 모델·함수 | 역할 |
| --- | --- |
| `Finding` | 의심 항목 한 개: 문항 번호, 유형, 심각도, 설명, 근거, 제안, 신뢰도 |
| `PageFindings` | 모델이 작성할 내용: 요약, 최대 30개의 의심 항목, 한계 목록 |
| `PageReviewResult` | 코드가 붙이는 실행 정보와 `PageFindings`를 묶은 최종 결과 |
| `parse_findings()` | 모델 응답 문자열을 `PageFindings`로 변환 |

`parse_findings()`는 양끝 공백을 제거하고, 응답 전체가 하나의 JSON 코드 블록이면 바깥 코드 블록만 벗깁니다. 이어서 `model_validate_json()`을 호출합니다. 설명 문장 속에서 JSON 일부를 찾아 추출하거나 잘못된 JSON을 임의로 고치지는 않습니다.

`Finding.confidence`는 0–1 범위이며 `verified`는 `None`만 허용합니다. 모델이 독립 검증을 받지 않았는데 `verified: true`라고 주장하면 스키마 검증에 실패합니다. 다만 올바른 형식으로 잘못된 근거·계산을 내놓는 것은 이 스키마로 검출할 수 없습니다.

`review()`는 성공한 `PageFindings`에 실제 모델 ID, 페이지 번호, 이미지 사용 여부를 붙여 `PageReviewResult`를 생성합니다. `kind`는 `unverified_page_review`, `scope`는 `first_page_only`입니다. 모델에게 이 실행 정보를 추측하게 하지 않고 코드에서 지정합니다.

성공 시 `{"result": ...}`, 실패 시 `{"error": ...}` 형태로 반환합니다. 오류 코드는 `GPU_OOM`, `INVALID_JSON`, `INVALID_INPUT`, `INFERENCE_FAILED`이며, 모델 로딩 오류는 `load()`에서 별도 예외가 됩니다.

## 12. 로컬 응답 검증과 JSON 저장

파일: [exam_checker/cloud/modal_client.py](../exam_checker/cloud/modal_client.py), [cli.py](../exam_checker/cli.py)

원격 호출이 끝나면 제어가 로컬 `review_page()`로 돌아옵니다.

1. 인증·앱 조회·타임아웃 등의 예외를 사용자용 `CloudError`로 바꿉니다.
2. 원격 응답의 오류 코드를 확인하고 해당 오류 안내를 만듭니다.
3. 성공 응답을 `PageReviewResult.model_validate()`로 다시 검증합니다.
4. 페이지 번호, 모델 ID, 이미지 사용 여부가 실제 요청과 일치하는지 확인합니다.
5. 검증된 객체를 `main()`에 반환합니다.

`main()`은 출력 폴더를 만들고 `result.model_dump_json(indent=2)`로 직렬화한 문자열을 UTF-8 파일에 씁니다. `--output`은 정확한 파일 경로이며 확장자를 자동 보정하지 않습니다. 같은 경로의 파일은 덮어쓰며 원자적 교체 방식은 아닙니다.

서버와 클라이언트의 이중 검증은 잘못된 형식이나 요청과 다른 결과를 거르는 역할입니다. 모델이 시험 문제를 올바르게 풀었는지 판정하는 독립 검토는 아닙니다.

## 13. 대체 경로: `check_gpu()` → `gpu_probe()`

파일: [modal_client.py](../exam_checker/cloud/modal_client.py), [schema.py](../exam_checker/cloud/schema.py), [modal_app/app.py](../modal_app/app.py)

`--modal-check`일 때에는 앞의 모델 로딩·추론 경로 대신 다음 순서로 실행됩니다.

```text
main()
  → check_gpu(pages[0])
    → GPUProbeRequest 생성
    → modal.Function.from_name(app_name, "gpu_probe")
    → gpu_probe.remote(payload)
      → 요청 검증·PNG 열기
      → CUDA 확인·2² 계산
      → GPUProbeResult 반환
    → 로컬 응답 검증
  → JSON 저장
```

`GPUProbeRequest`는 텍스트 최대 200,000자와 필수 PNG 바이트를 허용합니다. PNG는 1–20,000,000바이트입니다. AI 요청보다 텍스트 한도가 크지만 이 모드에서는 모델 토큰화를 하지 않습니다.

`gpu_probe()`는 `torch.cuda.is_available()`을 확인한 뒤 GPU에서 텐서를 만들어 제곱합니다. `GPUProbeResult`의 `cuda_available`은 `True`, `computation_result`는 `4.0`만 허용합니다. 이외에 이미지 크기와 GPU 이름 등을 반환합니다.

로컬 `check_gpu()`는 응답 형식 외에 페이지 번호와 텍스트 길이도 검사합니다. Qwen은 로딩하지 않고 `PageReviewer`의 모델 캐시도 사용하지 않습니다.

## 14. 정리와 종료: 다시 `main()`으로

성공하거나 처리 중 예외가 발생하여 컨텍스트를 빠져나가면 `process_pdf()`의 임시 디렉터리와 `open_pdf()`의 문서가 정리됩니다. 정상 경로에서는 CLI가 정리 완료 메시지를 출력하고 종료 코드 0으로 끝납니다.

`main()`의 `except`는 DPI 설정 오류, `CloudError`, PDF 오류, 파일·실행 관련 오류를 안내하고 종료 코드 1을 반환합니다. 클라우드 호출이나 응답 검증에서 실패하면 새 JSON을 쓰지 않으므로 이전 출력 파일이 남아 있을 수 있습니다. 저장 도중 실패했다면 부분 파일이 남을 수도 있습니다.

`@contextmanager`의 정리는 일반적인 성공·예외 종료에 대한 동작입니다. 프로세스 강제 종료까지 보장하는 것은 아닙니다.

## 15. 보조 코드와 테스트

다음 코드는 일반 CLI 실행 순서에 자동으로 들어가지 않습니다.

| 파일 | 설명 |
| --- | --- |
| [scripts/create_sample.py](../scripts/create_sample.py) | `main()`이 텍스트 문항 페이지와 도형 페이지를 가진 합성 PDF를 생성. 기존 샘플은 덮어쓰지 않음 |
| [tests/test_pdf_pipeline.py](../tests/test_pdf_pipeline.py) | PDF 추출·렌더 크기·오류 입력·암호 보호·DPI·성공 및 실패 시 정리 검사 |
| [tests/test_modal_client.py](../tests/test_modal_client.py) | GPU 연결 검사 요청·응답, 오류 안내, 요청 불일치, CLI 저장·정리 검사 |
| [tests/test_page_review.py](../tests/test_page_review.py) | AI JSON 파싱·제약, 전송 모드, 오류 응답, CLI 옵션·저장·정리 검사 |

테스트는 `pytest.fixture`로 임시 파일과 예시 응답을 만들고, `Mock`과 `monkeypatch`로 원격 호출을 대체합니다. `CliRunner`는 실제 터미널 프로세스를 새로 띄우지 않고 Typer 명령을 실행하여 출력과 종료 코드를 확인합니다. 따라서 로컬 테스트 통과만으로 실제 GPU 실행이나 모델 판정 품질이 검증되지는 않습니다.

각 패키지의 `__init__.py`는 패키지 설명을 담고 있으며 별도 실행 로직이 없습니다. `.gitignore`는 의존성 폴더, 데이터, 인증 파일의 버전 관리 제외 대상을 정의합니다.

## 코드 읽기 순서 요약

```text
uv / pyproject.toml / .env
  → cli.py: main()
  → config.py: Settings.from_env()
  → pipeline.py: process_pdf()
    → extractor.py: open_pdf(), extract_text()
    → renderer.py: render_page()
  → cli.py: 모드 선택
    → 기본: 정리 후 종료
    → GPU 검사: check_gpu() → gpu_probe() → 응답 검증
    → AI 검토: review_page() → PageReviewer
      → 새 컨테이너: load() → load_model()
      → 요청별: review() → infer() → parse_findings()
      → 로컬 응답 검증
  → cli.py: JSON 저장
  → contextmanager 정리
  → 종료
```


## LangSmith 추적을 담당하는 코드

[tracing.py](../exam_checker/tracing.py)의 `load_environment()`는 현재 디렉터리의 `.env`를 읽습니다. `enabled()`는 추적 설정과 API 키가 모두 있을 때만 활성화합니다. `span()`은 단계별 실행 시간을 기록하고 오류는 타입만 남깁니다. `record()`는 명시적으로 선택한 메타데이터를 기록하며, 본문 기록이 켜진 경우에만 텍스트·프롬프트·모델 응답도 저장합니다.

`traced()`는 일반 함수를 감싸며 `root=True`이면 환경변수 로딩과 종료 전 flush를 수행합니다. `headers()`는 현재 RunTree의 분산 추적 헤더를 생성하고 `remote_traced()`는 Modal에서 이를 부모로 복원합니다. 원격 호출에 헤더가 없으면 요청 추적을 비활성화합니다. 모델 초기 로딩은 부모 요청이 없으므로 별도 trace입니다.

[configure_tracing.py](../scripts/configure_tracing.py)는 선택한 LangSmith 설정을 Modal Secret에 생성·갱신합니다. [test_tracing.py](../tests/test_tracing.py)는 실제 SDK RunTree와 모의 클라이언트로 부모 연결, 본문 기록 제어, 오류 가림과 전송 실패 처리를 검사합니다. 설정 방법은 [LangSmith 문서](langsmith.md)를 참고하세요.
