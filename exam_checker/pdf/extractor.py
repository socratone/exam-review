from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pymupdf


class PDFError(ValueError):
    """An input PDF cannot be processed."""


@contextmanager
def open_pdf(path: Path) -> Iterator[pymupdf.Document]:
    if not path.is_file():
        raise PDFError(f"PDF file does not exist: {path}")
    if path.suffix.lower() != ".pdf":
        raise PDFError("Input must have a .pdf extension.")
    try:
        document = pymupdf.open(path)
    except (RuntimeError, ValueError, OSError) as exc:
        raise PDFError("Cannot open PDF; the file may be damaged or invalid.") from exc
    with document:
        if not document.is_pdf:
            raise PDFError("Input is not a PDF document.")
        if document.needs_pass:
            raise PDFError("Password-protected PDFs are not supported.")
        if document.page_count == 0:
            raise PDFError("PDF contains no pages.")
        yield document


def extract_text(page: pymupdf.Page) -> str:
    return page.get_text("text", sort=True)
