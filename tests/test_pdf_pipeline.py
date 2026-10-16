import pymupdf
import pytest
from typer.testing import CliRunner

from exam_checker.cli import app
from exam_checker.config import Settings
from exam_checker.pdf.extractor import PDFError, open_pdf
from exam_checker.pdf.pipeline import process_pdf


# pytest의 임시 폴더에 텍스트 페이지와 빈 페이지를 만들어 테스트끼리 파일이 섞이지 않게 한다.
@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "sample.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=144, height=144)
        page.insert_text((10, 30), "1. What is two plus two?\nChoose the correct answer.", fontsize=8)
        doc.new_page(width=144, height=144)
        doc.save(path)
    return path


# 텍스트 추출·빈 페이지 표시·DPI에 따른 이미지 크기·컨텍스트 종료 후 삭제를 확인한다.
def test_extract_render_and_cleanup(sample):
    with process_pdf(sample, Settings(render_dpi=160)) as pages:
        assert len(pages) == 2
        assert "two plus two" in pages[0].text
        assert not pages[0].needs_visual_review
        assert pages[1].needs_visual_review
        paths = [page.image_path for page in pages]
        for path in paths:
            pix = pymupdf.Pixmap(path)
            # PDF의 144포인트는 2인치이므로 160 DPI에서는 320픽셀이어야 한다.
            assert (pix.width, pix.height) == (320, 320)
    assert all(not path.exists() for path in paths)
    assert not paths[0].parent.exists()


# 전처리 이후 호출자에서 실패해도 임시 이미지가 정리되는지 확인한다.
def test_cleanup_when_consumer_fails(sample):
    with pytest.raises(RuntimeError, match="downstream"):
        with process_pdf(sample, Settings()) as pages:
            directory = pages[0].image_path.parent
            raise RuntimeError("downstream")
    assert not directory.exists()


# 일부 PNG를 만든 뒤 렌더링이 실패하는 상황을 재현해 중간 파일 정리를 확인한다.
def test_cleanup_when_render_fails(sample, monkeypatch):
    from exam_checker.pdf import pipeline

    original = pipeline.render_page
    paths = []

    def fail_second(page, directory, dpi):
        if paths:
            raise RuntimeError("render failed")
        path = original(page, directory, dpi)
        paths.append(path)
        return path

    monkeypatch.setattr(pipeline, "render_page", fail_second)
    with pytest.raises(RuntimeError, match="render failed"):
        with process_pdf(sample, Settings()):
            pytest.fail("Must not yield after rendering failure")
    assert not paths[0].parent.exists()


# 동일한 검사를 손상 파일·빈 파일·잘못된 확장자에 반복 적용한다.
@pytest.mark.parametrize("filename,content", [("bad.pdf", b"not a pdf"), ("empty.pdf", b""), ("wrong.txt", b"text")])
def test_invalid_input(tmp_path, filename, content):
    path = tmp_path / filename
    path.write_bytes(content)
    with pytest.raises(PDFError):
        with open_pdf(path):
            pytest.fail("Invalid input accepted")


# 존재하지 않는 경로를 명확한 PDFError로 처리하는지 확인한다.
def test_missing_input(tmp_path):
    with pytest.raises(PDFError, match="does not exist"):
        with open_pdf(tmp_path / "missing.pdf"):
            pass


# 합성 PDF에 암호를 설정해 암호가 필요한 입력을 거부하는지 확인한다.
def test_password_protected(sample, tmp_path):
    path = tmp_path / "locked.pdf"
    with pymupdf.open(sample) as doc:
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    with pytest.raises(PDFError, match="Password-protected"):
        with open_pdf(path):
            pass


# CliRunner로 CLI를 호출해 환경변수 적용과 요약 출력, 본문 미출력을 확인한다.
def test_cli_success(sample, monkeypatch):
    monkeypatch.setenv("EXAM_CHECKER_RENDER_DPI", "100")
    result = CliRunner().invoke(app, [str(sample)])
    assert result.exit_code == 0, result.output
    assert "Pages: 2" in result.output
    assert "at 100 DPI" in result.output
    assert "Temporary images cleaned up" in result.output
    assert "two plus two" not in result.output


# 잘못된 환경변수는 실패하지만 명시적인 --dpi가 있으면 우선 적용되는지 확인한다.
def test_cli_invalid_environment_and_override(sample, monkeypatch):
    monkeypatch.setenv("EXAM_CHECKER_RENDER_DPI", "bad")
    result = CliRunner().invoke(app, [str(sample)])
    assert result.exit_code == 1
    assert "must be an integer" in result.output
    override = CliRunner().invoke(app, [str(sample), "--dpi", "72"])
    assert override.exit_code == 0
    assert "at 72 DPI" in override.output


# 파일 오류가 CLI의 비정상 종료 코드와 사용자 안내로 연결되는지 확인한다.
def test_cli_failure(tmp_path):
    result = CliRunner().invoke(app, [str(tmp_path / "missing.pdf")])
    assert result.exit_code == 1
    assert "Error:" in result.output


# 허용 범위를 벗어난 DPI를 설정 단계에서 거부하는지 확인한다.
@pytest.mark.parametrize("dpi", [0, 71, 301])
def test_dpi_bounds(dpi):
    with pytest.raises(ValueError):
        Settings(render_dpi=dpi)
