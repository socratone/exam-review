"""Single-page, unverified AI review contracts (Phase 5)."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PageReviewRequest(StrictModel):
    page_number: int = Field(ge=1)
    text: str = Field(max_length=30_000)
    image_png: bytes | None = Field(default=None, max_length=20_000_000)


class Finding(StrictModel):
    question_number: str | None
    type: Literal["INVALID_ANSWER", "MULTIPLE_ANSWER", "NO_VALID_ANSWER",
                  "AMBIGUOUS_WORDING", "CONTRADICTION", "SPELLING_OR_GRAMMAR",
                  "IMAGE_MISMATCH", "TABLE_MISMATCH", "GRAPH_MISMATCH", "OTHER"]
    severity: Literal["low", "medium", "high"]
    description: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    suggestion: str | None
    confidence: float = Field(ge=0, le=1)
    verified: None = None


class PageFindings(StrictModel):
    summary: str = Field(min_length=1)
    issues: list[Finding] = Field(max_length=30)
    limitations: list[str]


class PageReviewResult(StrictModel):
    kind: Literal["unverified_page_review"] = "unverified_page_review"
    scope: Literal["first_page_only"] = "first_page_only"
    model: str
    page_number: int = Field(ge=1)
    image_used: bool
    review: PageFindings


def parse_findings(raw: str) -> PageFindings:
    """Accept JSON or one enclosing JSON fence; never guess at broken JSON."""
    raw = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", raw, flags=re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    return PageFindings.model_validate_json(raw)
