"""LangSmith 추적 도우미. 추적 설정과 시험지 내용 기록은 별도로 제어한다."""
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache, wraps
from pathlib import Path

import langsmith as ls
from dotenv import load_dotenv
from langsmith.run_helpers import get_current_run_tree

logger = logging.getLogger(__name__)
_remote_allowed = ContextVar("remote_trace_allowed", default=True)


def load_environment():
    # 실행 디렉터리의 .env만 읽는다. 이미 설정한 셸 환경변수는 덮어쓰지 않는다.
    load_dotenv(Path.cwd() / ".env", override=False)


def enabled():
    return _remote_allowed.get() and os.getenv("LANGSMITH_TRACING", "false").lower() == "true" and bool(os.getenv("LANGSMITH_API_KEY"))


def capture_content():
    return os.getenv("EXAM_CHECKER_TRACE_CONTENT", "false").lower() == "true"


@lru_cache(maxsize=4)
def _client(key, endpoint):
    return ls.Client(api_key=key, api_url=endpoint, timeout_ms=5000)


def client():
    return _client(os.environ["LANGSMITH_API_KEY"], os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"))


def flush():
    # CLI와 서버리스 요청이 종료되기 전에 백그라운드 전송을 마친다.
    if enabled():
        try:
            client().flush()
        except Exception:
            logger.warning("LangSmith flush failed; review results are unaffected.")


def record(run, *, metadata=None, content=None):
    """선택한 항목만 기록한다. 모델 객체·PNG 바이트·환경변수 전체는 넘기지 않는다."""
    if run is not None:
        try:
            outputs = dict(metadata or {})
            if capture_content() and content:
                outputs.update(content)
            run.add_outputs(outputs)
        except Exception:
            logger.warning("LangSmith output recording failed.")


@contextmanager
def span(name, *, inputs=None, run_type="chain", parent=None):
    """본문 예외는 타입만 기록해 Pydantic 예외의 시험지 원문 노출을 막는다."""
    if not enabled():
        yield None
        return
    try:
        context = ls.tracing_context(enabled=True, client=client())
        context.__enter__()
    except Exception:
        logger.warning("LangSmith initialization failed; continuing without tracing.")
        yield None
        return
    manager = None
    try:
        try:
            manager = ls.trace(name, run_type=run_type, inputs=inputs or {}, parent=parent,
                               project_name=os.getenv("LANGSMITH_PROJECT", "exam-checker"), client=client())
            run = manager.__enter__()
        except Exception:
            manager = None
            run = None
            logger.warning("LangSmith span creation failed; continuing without tracing.")
        try:
            yield run
        except BaseException as exc:
            if run is not None:
                try:
                    run.end(error=type(exc).__name__)
                except Exception:
                    pass
            raise
        finally:
            if manager is not None:
                try:
                    # 오류 문자열과 traceback을 SDK에 자동 전달하지 않는다.
                    manager.__exit__(None, None, None)
                except Exception:
                    logger.warning("LangSmith span completion failed.")
    finally:
        context.__exit__(None, None, None)


def headers():
    # 추적 ID만 원격 요청에 전달한다. API 키는 Modal Secret에서 별도로 공급한다.
    if enabled() and (run := get_current_run_tree()):
        return run.to_headers()
    return {}


def traced(name, *, root=False):
    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            if root:
                load_environment()
                if os.getenv("LANGSMITH_TRACING", "false").lower() == "true" and not os.getenv("LANGSMITH_API_KEY"):
                    logger.warning("LANGSMITH_API_KEY is missing; tracing is disabled.")
            try:
                with span(name):
                    return function(*args, **kwargs)
            finally:
                if root:
                    flush()
        return wrapper
    return decorate


def remote_traced(name):
    """Modal 메서드의 부모 trace를 복원하고 요청 종료 전에 전송을 마친다."""
    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            parent = kwargs.pop("trace_headers", None)
            token = _remote_allowed.set(bool(parent))
            try:
                with span(name, parent=parent) as run:
                    result = function(*args, **kwargs)
                    if isinstance(result, dict) and "error" in result and run is not None:
                        run.end(error=result["error"])
                    record(run, metadata={"status": "error" if isinstance(result, dict) and "error" in result else "ok"})
                    return result
            finally:
                flush()
                _remote_allowed.reset(token)
        return wrapper
    return decorate
