FROM python:3.12-slim
# uv 실행 파일만 가져와 잠금 파일에 맞는 로컬 의존성을 설치한다.
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
# /app은 호스트 소스로 덮여 연결되므로 가상환경은 별도 경로에 둔다.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
# 테스트 의존성과 프로젝트 설치를 생략한다. 복사한 소스를 모듈로 실행한다.
RUN uv sync --frozen --no-dev --no-install-project
COPY exam_checker ./exam_checker
COPY modal_app ./modal_app
ENTRYPOINT ["python", "-m", "exam_checker.cli"]
