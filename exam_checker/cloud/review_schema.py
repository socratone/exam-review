"""Single-page, unverified AI review contracts."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"


# 예상하지 않은 필드를 거부하고 암묵적 타입 변환을 제한하는 공통 스키마다.
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# AI 검토 입력이다. image_png=None이면 텍스트 전용 요청이다.
class PageReviewRequest(StrictModel):
    page_number: int = Field(ge=1)
    text: str = Field(max_length=30_000)
    image_png: bytes | None = Field(default=None, max_length=20_000_000)


# 모델이 보고한 의심 항목 하나다. confidence는 모델의 자기 평가이며 검증된 정확도가 아니다.
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
    # 아직 독립 검증이 없으므로 모델이 true/false를 임의로 반환할 수 없게 한다.
    verified: None = None


# 모델이 직접 생성해야 하는 내용이다. 실행 정보는 PageReviewResult에서 별도로 붙인다.
class PageFindings(StrictModel):
    summary: str = Field(min_length=1)
    issues: list[Finding] = Field(max_length=30)
    limitations: list[str]


# 실제 호출의 모델·페이지·이미지 사용 여부와 검토 내용을 묶어 로컬에 반환한다.
class PageReviewResult(StrictModel):
    kind: Literal["unverified_page_review"] = "unverified_page_review"
    scope: Literal["first_page_only"] = "first_page_only"
    model: str
    page_number: int = Field(ge=1)
    image_used: bool
    review: PageFindings


# 응답 전체가 JSON 또는 하나의 JSON 코드 블록인 경우만 허용하고 내용을 스키마로 검사한다.
def parse_findings(raw: str) -> PageFindings:
    """Accept JSON or one enclosing JSON fence; never guess at broken JSON."""
    raw = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", raw, flags=re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    # 형식·필드 제약만 검증한다. 설명이나 수학적 계산의 진위까지 검사하는 것은 아니다.
    return PageFindings.model_validate_json(raw)
