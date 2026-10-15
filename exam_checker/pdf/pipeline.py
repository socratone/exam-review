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


class PageData(BaseModel):
    page_number: int
    text: str
    image_path: Path
    needs_visual_review: bool


@contextmanager
def process_pdf(path: Path, settings: Settings) -> Iterator[list[PageData]]:
    """Images exist only inside this context, including on processing failure."""
    with open_pdf(path) as document, TemporaryDirectory(prefix="exam-checker-") as temp:
        logger.info("pdf opened pages=%d", document.page_count)
        pages = []
        for page in document:
            text = extract_text(page)
            # A conservative signal, not a claim that OCR or segmentation succeeded.
            usable_characters = sum(character.isalnum() for character in text)
            pages.append(PageData(
                page_number=page.number + 1,
                text=text,
                image_path=render_page(page, Path(temp), settings.render_dpi),
                needs_visual_review=usable_characters < 20,
            ))
            logger.info("page processed page=%d text_chars=%d", page.number + 1, len(text))
        yield pages
