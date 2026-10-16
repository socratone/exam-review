import os

import modal

app = modal.App(os.getenv("EXAM_CHECKER_MODAL_APP", "exam-checker"))
base_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.9.0", "pillow==12.0.0", "pydantic==2.14.1")
)
image = base_image.add_local_python_source("exam_checker")


@app.function(
    image=image,
    gpu=os.getenv("EXAM_CHECKER_GPU", "L4"),
    timeout=180,
    startup_timeout=600,
    min_containers=0,
    max_containers=1,
    scaledown_window=2,
    retries=0,
)
def gpu_probe(payload: dict) -> dict:
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


# Only model files are cached; page payloads remain in worker memory.
model_cache = modal.Volume.from_name("exam-checker-model-cache", create_if_missing=True)
vlm_image = (
    base_image.pip_install("transformers==4.57.6", "accelerate==1.12.0", "torchvision==0.24.0")
    .env({"HF_HOME": "/model-cache", "HF_HUB_DISABLE_TELEMETRY": "1"})
    .add_local_python_source("exam_checker", "modal_app")
)


@app.cls(
    image=vlm_image,
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
    model_id: str = modal.parameter()

    @modal.enter()
    def load(self):
        from modal_app.model import load_model

        try:
            self.model, self.processor = load_model(self.model_id, model_cache)
        except Exception as exc:
            raise RuntimeError(f"MODEL_LOAD_FAILED ({type(exc).__name__}): check model ID, dependencies, cache access and GPU memory") from None

    @modal.method()
    def review(self, payload: dict) -> dict:
        import torch
        from pydantic import ValidationError

        from exam_checker.cloud.review_schema import PageReviewRequest, PageReviewResult
        from modal_app.model import infer

        try:
            request = PageReviewRequest.model_validate(payload)
            findings = infer(self.model, self.processor, request)
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
