"""Generate a synthetic, non-confidential PDF for the Docker smoke test."""
from pathlib import Path

import pymupdf


def main():
    path = Path("data/sample.pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"Refusing to overwrite {path}")
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "Sample exam\n\n1. What is 2 + 2?\nA. 3\nB. 4\nC. 5")
        page = doc.new_page()
        page.draw_rect(pymupdf.Rect(72, 72, 240, 180), color=(0, 0, 0))
        doc.save(path)
    print(f"Created {path} (2 pages; second page has no native text).")


if __name__ == "__main__":
    main()
