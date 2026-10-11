FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim@sha256:5ae92e4d35b8d586d50ddf4aba6ecdd9f744237284d31c86bf45077e4e17e4bd

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock .python-version README.md ./
COPY src ./src

RUN test -s /app/src/horse_racing/web/data/horse_evaluation_v1.json \
    && uv sync --locked --no-dev --only-group web-prod --no-install-project \
    && groupadd --gid 10001 web \
    && useradd --uid 10001 --gid 10001 --no-create-home web \
    && mkdir -p /app/data \
    && chown 10001:10001 /app/data

USER 10001:10001

CMD ["sh", "-c", "exec uvicorn horse_racing.web.app:app --host 0.0.0.0 --port ${PORT:-8080} --no-proxy-headers"]
