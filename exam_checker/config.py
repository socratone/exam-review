import os

from pydantic import BaseModel, Field


class Settings(BaseModel):
    render_dpi: int = Field(default=160, ge=72, le=300)

    @classmethod
    def from_env(cls, dpi: int | None = None) -> "Settings":
        return cls(render_dpi=dpi if dpi is not None else os.getenv("EXAM_CHECKER_RENDER_DPI", "160"))
