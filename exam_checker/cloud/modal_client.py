import os

import modal
from pydantic import ValidationError

from exam_checker.cloud.schema import GPUProbeRequest, GPUProbeResult
from exam_checker.pdf.pipeline import PageData


# 원격 오류를 CLI에 전달한다. 안내 메시지에는 시험 내용이나 인증 정보를 포함하지 않는다.
class CloudError(RuntimeError):
    """Cloud errors safe to display without exposing payloads or credentials."""


# 배포된 gpu_probe를 호출해 데이터 전송과 CUDA 연산을 검사한다. Qwen 추론은 하지 않는다.
def check_gpu(page: PageData) -> GPUProbeResult:
    try:
        request = GPUProbeRequest(
            page_number=page.page_number,
            text=page.text,
            image_png=page.image_path.read_bytes(),
        )
    except ValidationError as exc:
        raise CloudError("First-page payload exceeds the GPU check limits (200,000 characters / 20 MB PNG).") from exc
    try:
        # 이미 배포된 함수를 조회한다. 이 호출이 배포를 수행하지는 않는다.
        function = modal.Function.from_name(
            os.getenv("EXAM_CHECKER_MODAL_APP", "exam-checker"), "gpu_probe"
        )
        raw = function.remote(request.model_dump())
    except modal.exception.AuthError as exc:
        raise CloudError("Modal authentication failed. Run modal token new and mount the credentials; see README.") from exc
    except modal.exception.NotFoundError as exc:
        raise CloudError("Modal app/function not found. Deploy modal_app.app in the same workspace/environment first.") from exc
    except (TimeoutError, modal.exception.FunctionTimeoutError) as exc:
        raise CloudError("Modal GPU check timed out. Check the Modal dashboard and retry.") from exc
    except Exception as exc:
        raise CloudError(f"Modal GPU check failed ({type(exc).__name__}). Check the Modal dashboard logs.") from exc
    try:
        result = GPUProbeResult.model_validate(raw)
    except ValidationError as exc:
        raise CloudError("Modal returned an invalid GPU check response; redeploy the matching app version.") from exc
    if result.page_number != page.page_number or result.text_characters != len(page.text):
        raise CloudError("Modal response does not match the submitted page.")
    return result


# 첫 페이지의 텍스트·선택적 이미지를 보내고, 검증된 AI 결과 또는 CloudError를 반환한다.
def review_page(page: PageData, model: str, text_only: bool = False):
    from exam_checker.cloud.review_schema import PageReviewRequest, PageReviewResult

    if text_only and not page.text.strip():
        raise CloudError("Text-only review requires extracted text; use image review for scanned pages.")
    try:
        request = PageReviewRequest(
            page_number=page.page_number, text=page.text,
            image_png=None if text_only else page.image_path.read_bytes(),
        )
    except ValidationError:
        raise CloudError("Review payload exceeds limits (30,000 characters / 20 MB PNG).") from None
    try:
        # 로컬 모델 객체가 아니라 원격 클래스 핸들이다. GPU 로딩은 Modal에서 수행한다.
        reviewer = modal.Cls.from_name(
            os.getenv("EXAM_CHECKER_MODAL_APP", "exam-checker"), "PageReviewer",
        )(model_id=model)
        # dict 안의 PNG bytes는 SDK가 전송한다. 원본 PDF 파일은 업로드하지 않는다.
        raw = reviewer.review.remote(request.model_dump())
    except modal.exception.AuthError:
        raise CloudError("Modal authentication failed. Run modal token new; see README.") from None
    except modal.exception.NotFoundError:
        raise CloudError("PageReviewer not found. Redeploy modal_app.app first.") from None
    except (TimeoutError, modal.exception.FunctionTimeoutError):
        raise CloudError("Modal review timed out; inspect the Modal dashboard.") from None
    except Exception as exc:
        raise CloudError(f"Modal model load/call failed ({type(exc).__name__}); inspect the dashboard for model load or memory errors.") from None
    # 원격 오류 코드만 안내로 바꿔 시험지나 원시 응답이 예외 메시지에 섞이지 않게 한다.
    errors = {
        "GPU_OOM": "GPU memory exhausted. Try Qwen/Qwen3-VL-4B-Instruct with --model or deploy to a larger GPU.",
        "INVALID_JSON": "Model response did not match the review JSON schema; no report was saved.",
        "INVALID_INPUT": "Invalid image or page exceeds the 8192-token input limit.",
        "INFERENCE_FAILED": "Cloud inference failed. Check model/Transformers compatibility.",
    }
    if isinstance(raw, dict) and "error" in raw:
        code = raw["error"]
        raise CloudError(errors.get(code, "Unknown cloud inference error.") if isinstance(code, str) else "Invalid cloud error response.")
    try:
        result = PageReviewResult.model_validate(raw["result"])
    except (ValidationError, KeyError, TypeError):
        raise CloudError("Invalid page review response; redeploy the matching app version.") from None
    # 스키마가 맞더라도 다른 페이지·모델의 응답이면 해당 요청의 결과로 받아들이지 않는다.
    if result.page_number != page.page_number or result.model != model or result.image_used != (not text_only):
        raise CloudError("Modal review response does not match the submitted page/model.")
    return result
