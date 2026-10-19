"""API 호출 없이 실제 LangSmith RunTree로 추적 연결과 본문 기록 제어를 검사한다."""
from unittest.mock import Mock

import pytest

from exam_checker import tracing


@pytest.fixture
def telemetry(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("EXAM_CHECKER_TRACE_CONTENT", "false")
    fake = Mock()
    monkeypatch.setattr(tracing, "client", lambda: fake)
    return fake


def test_disabled_without_key(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    with tracing.span("disabled") as run:
        assert run is None
    assert tracing.headers() == {}


def test_metadata_and_opt_in_content(telemetry, monkeypatch):
    with tracing.span("root") as run:
        tracing.record(run, metadata={"count": 2}, content={"text": "private"})
        assert run.outputs == {"count": 2}
        monkeypatch.setenv("EXAM_CHECKER_TRACE_CONTENT", "true")
        tracing.record(run, content={"text": "chosen content"})
        assert run.outputs["text"] == "chosen content"
    telemetry.create_run.assert_called()
    telemetry.update_run.assert_called()


def test_remote_parent_and_flush(telemetry):
    @tracing.remote_traced("remote")
    def remote():
        with tracing.span("child") as child:
            return {"trace_id": str(child.trace_id)}

    with tracing.span("local") as root:
        parent = tracing.headers()
        assert "langsmith-trace" in parent
        assert "test-key" not in str(parent)
        result = remote(trace_headers=parent)
        assert result["trace_id"] == str(root.trace_id)
    telemetry.flush.assert_called_once()


def test_remote_disabled_without_parent(telemetry):
    @tracing.remote_traced("remote")
    def remote():
        with tracing.span("child") as child:
            assert child is None
    remote()
    telemetry.create_run.assert_not_called()


def test_error_redaction(telemetry):
    with pytest.raises(ValueError, match="private"):
        with tracing.span("failure") as run:
            raise ValueError("private exam text")
    assert run.error == "ValueError"
    assert "private exam text" not in str(telemetry.update_run.call_args)


def test_tracing_failure_preserves_work(telemetry, monkeypatch):
    monkeypatch.setattr(tracing.ls, "trace", Mock(side_effect=RuntimeError("unavailable")))
    with tracing.span("work") as run:
        assert run is None


def test_dotenv_does_not_override_shell(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("EXAM_CHECKER_RENDER_DPI=180\n")
    monkeypatch.setenv("EXAM_CHECKER_RENDER_DPI", "100")
    tracing.load_environment()
    import os
    assert os.environ["EXAM_CHECKER_RENDER_DPI"] == "100"


def test_secret_sync_only_sends_tracing_settings(monkeypatch, tmp_path):
    from scripts import configure_tracing
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("UNRELATED_SECRET", "do-not-send")
    create = Mock()
    secret = Mock()
    fake_modal = Mock()
    fake_modal.Secret.objects.create = create
    fake_modal.Secret.from_name.return_value = secret
    monkeypatch.setattr(configure_tracing, "modal", fake_modal)
    configure_tracing.main()
    values = create.call_args.args[1]
    assert values["LANGSMITH_API_KEY"] == "test-key"
    assert "UNRELATED_SECRET" not in values
    secret.update.assert_called_once_with(values)
