from exam_checker.tracing import traced
from pathlib import Path

import pymupdf


# 페이지를 임시 PNG로 저장하고 파일 경로를 반환한다. 이미지 전송은 클라이언트가 담당한다.
@traced("pdf.render_page")
def render_page(page: pymupdf.Page, directory: Path, dpi: int) -> Path:
    # PyMuPDF는 0부터 세지만 사용자에게 보여줄 파일 번호는 1부터 시작한다.
    path = directory / f"page-{page.number + 1}.png"
    # 투명 채널을 만들지 않아 페이지 이미지의 메모리 사용을 줄인다.
    page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False).save(path)
    return path
