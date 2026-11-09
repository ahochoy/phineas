# syntax=docker/dockerfile:1

FROM python:3.14.7-slim-trixie AS base

RUN apt-get -o Acquire::Retries=0 update \
    && apt-get -o Acquire::Retries=0 upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

FROM base AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN uv sync --locked --no-dev --no-editable

FROM base AS runtime
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 /lambda-adapter /opt/extensions/lambda-adapter
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AWS_LWA_PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/health \
    AWS_LWA_READINESS_CHECK_HEALTHY_STATUS=200
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "phineas.api:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]
