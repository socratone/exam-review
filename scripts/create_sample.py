"""Generate a synthetic, non-confidential PDF for the Docker smoke test."""
from pathlib import Path

import pymupdf


# 실제 시험지 없이 실행을 확인할 수 있도록 텍스트 페이지와 도형 페이지를 가진 PDF를 만든다.
def main():
    path = Path("data/sample.pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    # 같은 이름으로 사용자가 저장한 파일을 실수로 덮어쓰지 않는다.
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
