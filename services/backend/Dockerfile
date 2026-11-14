# syntax=docker/dockerfile:1
# Backend image: the API, the task worker and the scheduler (selected by the command).
# Builds from the repo root, like all our images:
#   docker build -f services/backend/Dockerfile .
# Base images are pinned to exact versions in the FROM lines, where Dependabot updates them.
# Keep Python and uv in line with mise.toml.

FROM ghcr.io/astral-sh/uv:0.13.1 AS uv

FROM python:3.14.10-slim AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# Dependencies first, so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
COPY services/backend/pyproject.toml services/backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package ada --no-install-workspace
COPY services/backend services/backend
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package ada

FROM python:3.14.10-slim
RUN useradd --system --uid 1000 --no-create-home ada \
    # Snapshots; compose mounts a volume here that the API and the workers share.
    && mkdir /data && chown ada /data
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    # uvicorn reads UVICORN_* settings from the environment; compose can override the port.
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000 \
    # Only the gateway reaches the backend, so trust its X-Forwarded-* headers.
    FORWARDED_ALLOW_IPS="*"
USER ada
EXPOSE 8000
VOLUME /data
CMD ["uvicorn", "ada.entrypoints.http.app:create_app", "--factory", "--proxy-headers"]
