import os

import modal

from exam_checker.tracing import load_environment, remote_traced, traced

# 배포 명령도 CLI와 같은 .env 설정을 사용한다. 키는 이미지에 넣지 않는다.
load_environment()
secret_name = os.getenv("EXAM_CHECKER_LANGSMITH_SECRET")
tracing_secrets = [modal.Secret.from_name(secret_name)] if secret_name else []

# 배포할 앱과 실행 환경을 정의한다. GPU 종류는 배포 시 환경변수로 결정된다.
app = modal.App(os.getenv("EXAM_CHECKER_MODAL_APP", "exam-checker"))
base_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.9.0", "pillow==12.0.0", "pydantic==2.14.1", "langsmith==0.14.11", "python-dotenv==1.2.4")
    # 원격 import에서도 같은 앱·GPU·Secret 의존성을 선언하도록 비밀이 아닌 설정을 전달한다.
    .env({
        "EXAM_CHECKER_LANGSMITH_SECRET": secret_name or "",
        "EXAM_CHECKER_GPU": os.getenv("EXAM_CHECKER_GPU", "L4"),
        "EXAM_CHECKER_MODAL_APP": os.getenv("EXAM_CHECKER_MODAL_APP", "exam-checker"),
    })
)
# 로컬 소스 연결은 이미지 빌드 작업 뒤에 둬야 Modal의 빌드 순서 제약을 지킨다.
image = base_image.add_local_python_source("exam_checker")


# 이 함수 본문은 Modal GPU에서 실행된다. 로컬에서 앱을 import해도 GPU 연산은 시작되지 않는다.
@app.function(
    image=image,
    secrets=tracing_secrets,
    gpu=os.getenv("EXAM_CHECKER_GPU", "L4"),
    timeout=180,
    startup_timeout=600,
    min_containers=0,
    max_containers=1,
    scaledown_window=2,
    retries=0,
)
@remote_traced("gpu.check")
def gpu_probe(payload: dict, trace_headers: dict | None = None) -> dict:
    """Validate page transport and execute a real CUDA operation; no AI review."""
    from io import BytesIO

    import torch
    from PIL import Image

    from exam_checker.cloud.schema import GPUProbeRequest, GPUProbeResult

    request = GPUProbeRequest.model_validate(payload)
    with Image.open(BytesIO(request.image_png)) as page:
        if page.format != "PNG":
            raise ValueError("Expected a PNG page image")
        page.load()
        width, height = page.size
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable in the GPU worker")
    value = (torch.tensor([2.0], device="cuda") ** 2).item()
    return GPUProbeResult(
        page_number=request.page_number,
        text_characters=len(request.text),
        image_width=width,
        image_height=height,
        gpu_name=torch.cuda.get_device_name(0),
        cuda_available=True,
        computation_result=value,
    ).model_dump()


# 이 Volume에는 모델 파일만 저장한다. 시험지 요청은 워커 메모리에서 처리한다.
model_cache = modal.Volume.from_name("exam-checker-model-cache", create_if_missing=True)
vlm_image = (
    base_image.pip_install("transformers==4.57.6", "accelerate==1.12.0", "torchvision==0.24.0")
    .env({"HF_HOME": "/model-cache", "HF_HUB_DISABLE_TELEMETRY": "1"})
    .add_local_python_source("exam_checker", "modal_app")
)


# 모델을 컨테이너 메모리에 유지하여 같은 컨테이너의 요청마다 다시 로딩하지 않도록 한다.
@app.cls(
    image=vlm_image,
    secrets=tracing_secrets,
    gpu=os.getenv("EXAM_CHECKER_GPU", "L4"),
    volumes={"/model-cache": model_cache},
    timeout=600,
    startup_timeout=1800,
    min_containers=0,
    max_containers=1,
    scaledown_window=30,
    retries=0,
)
class PageReviewer:
    # 클라이언트의 PageReviewer(model_id=...)에서 전달받는 원격 클래스 파라미터다.
    model_id: str = modal.parameter()

    # 새 GPU 컨테이너에서 한 번 실행한다. 요청마다 실행되는 review와 수명이 다르다.
    @modal.enter()
    @traced("model.load", root=True)
    def load(self):
        from modal_app.model import load_model

        try:
            self.model, self.processor = load_model(self.model_id, model_cache)
        except Exception as exc:
            raise RuntimeError(f"MODEL_LOAD_FAILED ({type(exc).__name__}): check model ID, dependencies, cache access and GPU memory") from None

    # 요청마다 입력 검증·추론·결과 포장을 수행한다. 원시 모델 응답 대신 결과 또는 오류 코드를 돌려준다.
    @modal.method()
    @remote_traced("gpu.review")
    def review(self, payload: dict, trace_headers: dict | None = None) -> dict:
        import torch
        from pydantic import ValidationError

        from exam_checker.cloud.review_schema import PageReviewRequest, PageReviewResult
        from modal_app.model import infer

        try:
            request = PageReviewRequest.model_validate(payload)
            findings = infer(self.model, self.processor, request)
            # 실행 정보는 모델에게 생성시키지 않고 실제 요청과 설정에서 가져온다.
            result = PageReviewResult(
                model=self.model_id, page_number=request.page_number,
                image_used=request.image_png is not None, review=findings,
            )
            return {"result": result.model_dump()}
        except torch.cuda.OutOfMemoryError:
            return {"error": "GPU_OOM"}
        except ValidationError:
            return {"error": "INVALID_JSON"}
        except ValueError:
            return {"error": "INVALID_INPUT"}
        except Exception:
            return {"error": "INFERENCE_FAILED"}
