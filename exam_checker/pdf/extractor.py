from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pymupdf


# PDF 입력 문제를 CLI에서 사용자용 오류로 처리하기 위한 예외다.
class PDFError(ValueError):
    """An input PDF cannot be processed."""


# yield로 열린 문서를 빌려주고, 호출자의 with 블록이 끝나면 문서를 닫는다.
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
    # 확장자뿐 아니라 실제 문서 형식도 확인한다. 검사 실패 시에도 문서는 닫힌다.
    with document:
        if not document.is_pdf:
            raise PDFError("Input is not a PDF document.")
        if document.needs_pass:
            raise PDFError("Password-protected PDFs are not supported.")
        if document.page_count == 0:
            raise PDFError("PDF contains no pages.")
        yield document


# PDF에 저장된 텍스트만 추출한다. 스캔 이미지에 OCR을 수행하지는 않는다.
def extract_text(page: pymupdf.Page) -> str:
    return page.get_text("text", sort=True)
