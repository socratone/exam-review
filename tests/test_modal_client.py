from unittest.mock import Mock

import modal
import pymupdf
import pytest
from typer.testing import CliRunner

from exam_checker.cli import app
from exam_checker.cloud.modal_client import CloudError, check_gpu
from exam_checker.pdf.pipeline import PageData


@pytest.fixture
def page(tmp_path):
    path = tmp_path / "page.png"
    path.write_bytes(b"transport-test")
    return PageData(page_number=1, text="Sample", image_path=path, needs_visual_review=True)


@pytest.fixture
def response():
    return dict(kind="gpu_connection_check", page_number=1, text_characters=6,
                image_width=100, image_height=100, gpu_name="test GPU",
                cuda_available=True, computation_result=4.0)


def test_payload_and_response(page, response, monkeypatch):
    function = Mock()
    function.remote.return_value = response
    lookup = Mock(return_value=function)
    monkeypatch.setattr(modal.Function, "from_name", lookup)
    monkeypatch.setenv("EXAM_CHECKER_MODAL_APP", "test-app")
    assert check_gpu(page).gpu_name == "test GPU"
    lookup.assert_called_once_with("test-app", "gpu_probe")
    function.remote.assert_called_once_with(dict(page_number=1, text="Sample", image_png=b"transport-test"))


@pytest.mark.parametrize("exception,expected", [
    (modal.exception.AuthError("private-token"), "authentication failed"),
    (modal.exception.NotFoundError("private-payload"), "not found"),
    (TimeoutError("private-payload"), "timed out"),
    (RuntimeError("private-payload"), "RuntimeError"),
])
def test_cloud_errors_are_actionable_and_redacted(page, exception, expected, monkeypatch):
    function = Mock()
    function.remote.side_effect = exception
    monkeypatch.setattr(modal.Function, "from_name", Mock(return_value=function))
    with pytest.raises(CloudError, match=expected) as error:
        check_gpu(page)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("changes", [{"cuda_available": False}, {"computation_result": 3.0}, {"page_number": 2}])
def test_rejects_failed_or_mismatched_probe(page, response, changes, monkeypatch):
    function = Mock()
    function.remote.return_value = response | changes
    monkeypatch.setattr(modal.Function, "from_name", Mock(return_value=function))
    with pytest.raises(CloudError):
        check_gpu(page)


@pytest.mark.parametrize("fail", [False, True])
def test_cli_cloud_path_and_cleanup(tmp_path, response, monkeypatch, fail):
    from exam_checker.cloud.schema import GPUProbeResult

    pdf = tmp_path / "sample.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.new_page()
        document.save(pdf)
    seen = []

    def remote(page):
        assert page.image_path.exists()
        assert page.page_number == 1
        seen.append(page.image_path)
        if fail:
            raise CloudError("connection failed")
        return GPUProbeResult(**response)

    monkeypatch.setattr("exam_checker.cli.check_gpu", remote)
    output = tmp_path / "result.json"
    result = CliRunner().invoke(app, [str(pdf), "--modal-check", "--output", str(output)])
    assert result.exit_code == (1 if fail else 0), result.output
    assert len(seen) == 1
    assert not seen[0].parent.exists()
    assert output.exists() is not fail
    if not fail:
        assert GPUProbeResult.model_validate_json(output.read_text()).kind == "gpu_connection_check"


def test_cli_rejects_overwriting_pdf(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"original")
    result = CliRunner().invoke(app, [str(pdf), "--modal-check", "--output", str(pdf)])
    assert result.exit_code == 2
    assert pdf.read_bytes() == b"original"
