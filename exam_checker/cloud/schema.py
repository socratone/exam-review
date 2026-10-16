from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# 연결 검사 요청: 페이지 번호·텍스트·필수 PNG 바이트의 타입과 크기를 제한한다.
class GPUProbeRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    page_number: int = Field(ge=1)
    text: str = Field(max_length=200_000)
    image_png: bytes = Field(min_length=1, max_length=20_000_000)


# CUDA 사용 여부와 계산값까지 검사하지만 시험지 내용의 정확성은 검사하지 않는다.
class GPUProbeResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    kind: Literal["gpu_connection_check"] = "gpu_connection_check"
    page_number: int = Field(ge=1)
    text_characters: int = Field(ge=0)
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    gpu_name: str = Field(min_length=1)
    cuda_available: Literal[True]
    computation_result: Literal[4.0]
