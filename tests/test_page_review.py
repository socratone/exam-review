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


# 스키마 검증에 사용할 최소한의 정상 AI 검토 내용이다.
@pytest.fixture
def findings():
    return {"summary": "검토 완료", "issues": [], "limitations": ["독립 검증이 필요함"]}


# 원격 전송 경로를 검사할 테스트 데이터다. 모델이나 GPU를 실행하지 않는다.
@pytest.fixture
def page(tmp_path):
    png = tmp_path / "page.png"
    png.write_bytes(b"test-png")
    return PageData(page_number=1, text="1. 2+2=?", image_path=png, needs_visual_review=False)


# 일반 JSON과 JSON 코드 블록을 같은 결과로 파싱하는지 확인한다.
def test_json_and_fence(findings):
    raw = json.dumps(findings)
    assert parse_findings(raw).summary == "검토 완료"
    assert parse_findings(f"```json\n{raw}\n```").issues == []


# 누락 필드·손상 문자열·잘못된 최상위 타입을 거부하는지 확인한다.
@pytest.mark.parametrize("raw", ['{}', 'not JSON', '{"summary":"partial"', '[]'])
def test_invalid_json(raw):
    with pytest.raises(ValidationError):
        parse_findings(raw)


# 모델이 verified=true를 주장하거나 신뢰도 범위를 벗어나면 거부하는지 확인한다.
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


# 이미지 포함·텍스트 전용 요청의 차이와 원격 모델 파라미터를 확인한다.
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


# 오류 코드와 손상된 원격 응답을 CloudError로 바꾸는지 확인한다.
@pytest.mark.parametrize("raw", [{"error": "GPU_OOM"}, {"error": "INVALID_JSON"}, {}, None,
                                  {"result": {"secret": "private"}}])
def test_bad_response(page, monkeypatch, raw):
    instance = Mock()
    instance.review.remote.return_value = raw
    monkeypatch.setattr(modal.Cls, "from_name", Mock(return_value=Mock(return_value=instance)))
    with pytest.raises(CloudError) as error:
        review_page(page, DEFAULT_MODEL)
    assert "private" not in str(error.value)


# 빈 텍스트를 텍스트 전용 모드로 보내기 전에 거부하는지 확인한다.
def test_empty_text_only(page):
    page.text = ""
    with pytest.raises(CloudError, match="requires extracted text"):
        review_page(page, DEFAULT_MODEL, text_only=True)


# AI 검토 성공·실패에 따른 저장 여부와 임시 이미지 삭제를 함께 확인한다.
@pytest.mark.parametrize("fail", [False, True])
def test_cli_review_and_cleanup(tmp_path, findings, monkeypatch, fail):
    pdf = tmp_path / "sample.pdf"
    with pymupdf.open() as doc:
        for number in range(1, 4):
            page = doc.new_page()
            page.insert_text((72, 72), f"Question on page {number}")
        doc.save(pdf)
    seen = []

    def fake_review(page, model, text_only):
        assert page.image_path.exists()
        assert page.image_path.read_bytes().startswith(b"\x89PNG")
        assert not text_only
        seen.append((page.page_number, page.image_path))
        if fail and page.page_number == 2:
            raise CloudError("Failed review")
        return PageReviewResult(model=model, page_number=page.page_number, image_used=True, review=findings)

    monkeypatch.setattr("exam_checker.cli.review_page", fake_review)
    output = tmp_path / "report.json"
    result = CliRunner().invoke(app, [str(pdf), "--review", "--output", str(output)])
    assert result.exit_code == (1 if fail else 0), result.output
    assert [number for number, _ in seen] == ([1, 2] if fail else [1, 2, 3])
    assert all(not image.exists() for _, image in seen)
    assert all(not image.parent.exists() for _, image in seen)
    assert output.exists() is not fail
    if not fail:
        report = json.loads(output.read_text())
        assert report["kind"] == "unverified_document_review"
        assert report["scope"] == "all_pages"
        assert report["page_count"] == 3
        assert [page["page_number"] for page in report["pages"]] == [1, 2, 3]
        assert all(page["scope"] == "single_page" and page["image_used"] for page in report["pages"])


# CLI부터 Modal 요청까지 각 페이지의 PNG가 전달되는지 확인한다.
@pytest.mark.parametrize("text_only", [False, True])
def test_cli_sends_each_page_to_modal(tmp_path, findings, monkeypatch, text_only):
    pdf = tmp_path / "sample.pdf"
    with pymupdf.open() as doc:
        for number in range(1, 4):
            page = doc.new_page()
            page.insert_text((72, 72), f"Page {number} question")
        doc.save(pdf)

    requests = []

    def fake_remote(payload, **kwargs):
        requests.append(payload)
        number = payload["page_number"]
        result = PageReviewResult(model=DEFAULT_MODEL, page_number=number,
                                  image_used=not text_only, review=findings)
        return {"result": result.model_dump()}

    instance = Mock()
    instance.review.remote.side_effect = fake_remote
    monkeypatch.setattr(modal.Cls, "from_name", Mock(return_value=Mock(return_value=instance)))
    output = tmp_path / "report.json"
    args = [str(pdf), "--review", "--output", str(output)]
    if text_only:
        args.append("--text-only")
    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert [request["page_number"] for request in requests] == [1, 2, 3]
    if text_only:
        assert all(request["image_png"] is None for request in requests)
    else:
        images = [request["image_png"] for request in requests]
        assert all(image.startswith(b"\x89PNG") for image in images)
        assert len(set(images)) == 3
    assert [page["image_used"] for page in json.loads(output.read_text())["pages"]] == [not text_only] * 3


# 의미가 맞지 않는 옵션 조합을 원격 호출 전에 사용법 오류로 처리하는지 확인한다.
@pytest.mark.parametrize("options", [["--modal-check", "--review"], ["--text-only"], ["--model", "example"]])
def test_incompatible_options(options):
    assert CliRunner().invoke(app, ["missing.pdf", *options]).exit_code == 2
