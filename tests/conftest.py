"""개발자의 실제 키가 있어도 테스트에서 외부 추적 서버에 전송하지 않는다."""
import pytest


@pytest.fixture(autouse=True)
def disable_external_tracing(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
