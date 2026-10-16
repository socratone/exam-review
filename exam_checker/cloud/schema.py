from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GPUProbeRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    page_number: int = Field(ge=1)
    text: str = Field(max_length=200_000)
    image_png: bytes = Field(min_length=1, max_length=20_000_000)


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
