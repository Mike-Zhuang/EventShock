# syntax=docker/dockerfile:1.7

FROM python:3.12.13-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    EVENTSHOCK_DATA_DIR=/data

WORKDIR /app

# 固定 UID/GID，确保 SQLite 持久卷在容器重建后仍可由非 root 进程写入。
RUN groupadd --gid 10001 eventshock \
    && useradd --uid 10001 --gid eventshock --create-home --shell /usr/sbin/nologin eventshock \
    && mkdir -p /app/frontend/dist /data \
    && chown -R eventshock:eventshock /app /data

COPY pyproject.toml requirements.lock README.md LICENSE ./
COPY backend/ ./backend/
RUN python -m pip install --requirement requirements.lock \
    && python -m pip install --no-deps .

COPY event-packs/ ./event-packs/
COPY --chown=eventshock:eventshock frontend/dist/ ./frontend/dist/
RUN chown -R eventshock:eventshock /app/backend

USER eventshock

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"]

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
