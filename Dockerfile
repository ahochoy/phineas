# syntax=docker/dockerfile:1

# Match the worker's patched OS/Python family in both build and runtime stages.
FROM public.ecr.aws/lambda/python:3.14 AS base

RUN dnf upgrade -y --releasever=2023.12.20261112 && dnf clean all

FROM base AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN uv sync --locked --no-dev --no-editable --python /var/lang/bin/python3.14

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
# This is a Web Adapter HTTP app, not a native Python Lambda handler. Do not
# inherit /lambda-entrypoint.sh, which would treat our command as a handler.
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "phineas.api:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]
