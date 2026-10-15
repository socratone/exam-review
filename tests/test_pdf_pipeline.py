import pymupdf
import pytest
from typer.testing import CliRunner

from exam_checker.cli import app
from exam_checker.config import Settings
from exam_checker.pdf.extractor import PDFError, open_pdf
from exam_checker.pdf.pipeline import process_pdf


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "sample.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=144, height=144)
        page.insert_text((10, 30), "1. What is two plus two?\nChoose the correct answer.", fontsize=8)
        doc.new_page(width=144, height=144)
        doc.save(path)
    return path


def test_extract_render_and_cleanup(sample):
    with process_pdf(sample, Settings(render_dpi=160)) as pages:
        assert len(pages) == 2
        assert "two plus two" in pages[0].text
        assert not pages[0].needs_visual_review
        assert pages[1].needs_visual_review
        paths = [page.image_path for page in pages]
        for path in paths:
            pix = pymupdf.Pixmap(path)
            assert (pix.width, pix.height) == (320, 320)
    assert all(not path.exists() for path in paths)
    assert not paths[0].parent.exists()


def test_cleanup_when_consumer_fails(sample):
    with pytest.raises(RuntimeError, match="downstream"):
        with process_pdf(sample, Settings()) as pages:
            directory = pages[0].image_path.parent
            raise RuntimeError("downstream")
    assert not directory.exists()


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


@pytest.mark.parametrize("filename,content", [("bad.pdf", b"not a pdf"), ("empty.pdf", b""), ("wrong.txt", b"text")])
def test_invalid_input(tmp_path, filename, content):
    path = tmp_path / filename
    path.write_bytes(content)
    with pytest.raises(PDFError):
        with open_pdf(path):
            pytest.fail("Invalid input accepted")


def test_missing_input(tmp_path):
    with pytest.raises(PDFError, match="does not exist"):
        with open_pdf(tmp_path / "missing.pdf"):
            pass


def test_password_protected(sample, tmp_path):
    path = tmp_path / "locked.pdf"
    with pymupdf.open(sample) as doc:
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    with pytest.raises(PDFError, match="Password-protected"):
        with open_pdf(path):
            pass


def test_cli_success(sample, monkeypatch):
    monkeypatch.setenv("EXAM_CHECKER_RENDER_DPI", "100")
    result = CliRunner().invoke(app, [str(sample)])
    assert result.exit_code == 0, result.output
    assert "Pages: 2" in result.output
    assert "at 100 DPI" in result.output
    assert "Temporary images cleaned up" in result.output
    assert "two plus two" not in result.output


def test_cli_invalid_environment_and_override(sample, monkeypatch):
    monkeypatch.setenv("EXAM_CHECKER_RENDER_DPI", "bad")
    result = CliRunner().invoke(app, [str(sample)])
    assert result.exit_code == 1
    assert "must be an integer" in result.output
    override = CliRunner().invoke(app, [str(sample), "--dpi", "72"])
    assert override.exit_code == 0
    assert "at 72 DPI" in override.output


def test_cli_failure(tmp_path):
    result = CliRunner().invoke(app, [str(tmp_path / "missing.pdf")])
    assert result.exit_code == 1
    assert "Error:" in result.output


@pytest.mark.parametrize("dpi", [0, 71, 301])
def test_dpi_bounds(dpi):
    with pytest.raises(ValueError):
        Settings(render_dpi=dpi)
