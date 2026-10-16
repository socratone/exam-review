import json
from unittest.mock import Mock

import modal
import pymupdf
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from exam_checker.cli import app
from exam_checker.cloud.modal_client import CloudError, review_page
from exam_checker.cloud.review_schema import DEFAULT_MODEL, PageReviewResult, parse_findings
from exam_checker.pdf.pipeline import PageData


@pytest.fixture
def findings():
    return {"summary": "검토 완료", "issues": [], "limitations": ["첫 페이지만 검토함"]}


@pytest.fixture
def page(tmp_path):
    png = tmp_path / "page.png"
    png.write_bytes(b"test-png")
    return PageData(page_number=1, text="1. 2+2=?", image_path=png, needs_visual_review=False)


def test_json_and_fence(findings):
    raw = json.dumps(findings)
    assert parse_findings(raw).summary == "검토 완료"
    assert parse_findings(f"```json\n{raw}\n```").issues == []


@pytest.mark.parametrize("raw", ['{}', 'not JSON', '{"summary":"partial"', '[]'])
def test_invalid_json(raw):
    with pytest.raises(ValidationError):
        parse_findings(raw)


def test_issue_cannot_claim_verification(findings):
    issue = dict(question_number="1", type="NO_VALID_ANSWER", severity="high",
                 description="Suspected", evidence="Example", suggestion=None,
                 confidence=0.9, verified=True)
    findings["issues"] = [issue]
    with pytest.raises(ValidationError):
        parse_findings(json.dumps(findings))
    issue["verified"] = None
    assert parse_findings(json.dumps(findings)).issues[0].verified is None
    issue["confidence"] = 1.5
    with pytest.raises(ValidationError):
        parse_findings(json.dumps(findings))


@pytest.mark.parametrize("text_only", [False, True])
def test_remote_contract(page, findings, monkeypatch, text_only):
    result = PageReviewResult(model=DEFAULT_MODEL, page_number=1, image_used=not text_only, review=findings)
    instance = Mock()
    instance.review.remote.return_value = {"result": result.model_dump()}
    constructor = Mock(return_value=instance)
    monkeypatch.setattr(modal.Cls, "from_name", Mock(return_value=constructor))
    assert review_page(page, DEFAULT_MODEL, text_only) == result
    constructor.assert_called_once_with(model_id=DEFAULT_MODEL)
    sent = instance.review.remote.call_args.args[0]
    assert sent["image_png"] == (None if text_only else b"test-png")


@pytest.mark.parametrize("raw", [{"error": "GPU_OOM"}, {"error": "INVALID_JSON"}, {}, None,
                                  {"result": {"secret": "private"}}])
def test_bad_response(page, monkeypatch, raw):
    instance = Mock()
    instance.review.remote.return_value = raw
    monkeypatch.setattr(modal.Cls, "from_name", Mock(return_value=Mock(return_value=instance)))
    with pytest.raises(CloudError) as error:
        review_page(page, DEFAULT_MODEL)
    assert "private" not in str(error.value)


def test_empty_text_only(page):
    page.text = ""
    with pytest.raises(CloudError, match="requires extracted text"):
        review_page(page, DEFAULT_MODEL, text_only=True)


@pytest.mark.parametrize("fail", [False, True])
def test_cli_review_and_cleanup(tmp_path, findings, monkeypatch, fail):
    pdf = tmp_path / "sample.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(pdf)
    images = []

    def fake_review(page, model, text_only):
        assert page.image_path.exists()
        images.append(page.image_path)
        if fail:
            raise CloudError("Failed review")
        return PageReviewResult(model=model, page_number=1, image_used=True, review=findings)

    monkeypatch.setattr("exam_checker.cli.review_page", fake_review)
    output = tmp_path / "report.json"
    result = CliRunner().invoke(app, [str(pdf), "--review", "--output", str(output)])
    assert result.exit_code == (1 if fail else 0), result.output
    assert not images[0].exists()
    assert output.exists() is not fail
    if not fail:
        assert json.loads(output.read_text())["scope"] == "first_page_only"


@pytest.mark.parametrize("options", [["--modal-check", "--review"], ["--text-only"], ["--model", "example"]])
def test_incompatible_options(options):
    assert CliRunner().invoke(app, ["missing.pdf", *options]).exit_code == 2
