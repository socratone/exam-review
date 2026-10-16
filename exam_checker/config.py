import os

from pydantic import BaseModel, Field


# Pydantic이 DPI를 정수로 변환하고 72–300 범위를 검사한다.
class Settings(BaseModel):
    render_dpi: int = Field(default=160, ge=72, le=300)

    # 명시한 --dpi가 환경변수보다 우선하며, 둘 다 없으면 기본값 160을 사용한다.
    @classmethod
    def from_env(cls, dpi: int | None = None) -> "Settings":
        return cls(render_dpi=dpi if dpi is not None else os.getenv("EXAM_CHECKER_RENDER_DPI", "160"))
