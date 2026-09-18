FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock .python-version README.md ./
COPY src ./src

RUN uv sync --locked --no-dev --only-group web-prod --no-install-project

CMD ["sh", "-c", "exec uvicorn horse_racing.web.app:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
