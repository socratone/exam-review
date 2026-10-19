"""배포 환경과 GPU 워커의 import가 같은 의존성을 선언하도록 검사한다."""
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("secret_name", ["", "test-tracing-secret"])
def test_worker_receives_dependency_configuration(monkeypatch, secret_name):
    from exam_checker import tracing

    monkeypatch.setattr(tracing, "load_environment", lambda: None)
    monkeypatch.setenv("EXAM_CHECKER_LANGSMITH_SECRET", secret_name)
    monkeypatch.setenv("EXAM_CHECKER_GPU", "L4")
    monkeypatch.setenv("EXAM_CHECKER_MODAL_APP", "test-exam-app")
    monkeypatch.setenv("LANGSMITH_API_KEY", "must-not-enter-image")
    image = Mock()
    image.pip_install.return_value = image
    image.env.return_value = image
    image.add_local_python_source.return_value = image
    app = SimpleNamespace(function=lambda **kwargs: lambda fn: fn, cls=lambda **kwargs: lambda cls: cls)
    fake = SimpleNamespace(
        App=lambda name: app,
        Image=SimpleNamespace(debian_slim=lambda **kwargs: image),
        Secret=SimpleNamespace(from_name=Mock()),
        Volume=SimpleNamespace(from_name=Mock()),
        parameter=lambda: None,
        enter=lambda: lambda fn: fn,
        method=lambda: lambda fn: fn,
    )
    monkeypatch.setitem(sys.modules, "modal", fake)
    runpy.run_path("modal_app/app.py")
    configuration = image.env.call_args_list[0].args[0]
    assert configuration == {
        "EXAM_CHECKER_LANGSMITH_SECRET": secret_name,
        "EXAM_CHECKER_GPU": "L4",
        "EXAM_CHECKER_MODAL_APP": "test-exam-app",
    }
    assert "must-not-enter-image" not in str(image.env.call_args_list)
