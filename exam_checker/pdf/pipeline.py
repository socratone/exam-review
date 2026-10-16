import logging
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from pydantic import BaseModel

from exam_checker.config import Settings
from exam_checker.pdf.extractor import extract_text, open_pdf
from exam_checker.pdf.renderer import render_page

logger = logging.getLogger(__name__)


# 페이지별 중간 결과다. image_path는 process_pdf의 with 블록 안에서만 유효하다.
class PageData(BaseModel):
    page_number: int
    text: str
    image_path: Path
    needs_visual_review: bool


# 모든 페이지를 전처리한다. 정상 종료와 예외 전파 시 문서와 임시 디렉터리를 정리한다.
@contextmanager
def process_pdf(path: Path, settings: Settings) -> Iterator[list[PageData]]:
    """Images exist only inside this context, including on processing failure."""
    with open_pdf(path) as document, TemporaryDirectory(prefix="exam-checker-") as temp:
        logger.info("pdf opened pages=%d", document.page_count)
        pages = []
        for page in document:
            text = extract_text(page)
            # 문자·숫자(한글 포함)가 적으면 시각 검토 대상으로 표시한다. 스캔 여부의 확정 판정은 아니다.
            usable_characters = sum(character.isalnum() for character in text)
            pages.append(PageData(
                page_number=page.number + 1,
                text=text,
                image_path=render_page(page, Path(temp), settings.render_dpi),
                needs_visual_review=usable_characters < 20,
            ))
            logger.info("page processed page=%d text_chars=%d", page.number + 1, len(text))
        # 여기서 CLI로 제어를 넘긴다. CLI의 with 블록이 끝날 때 자원 정리가 이어진다.
        yield pages
