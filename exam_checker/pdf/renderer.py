from pathlib import Path

import pymupdf


def render_page(page: pymupdf.Page, directory: Path, dpi: int) -> Path:
    path = directory / f"page-{page.number + 1}.png"
    page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False).save(path)
    return path
