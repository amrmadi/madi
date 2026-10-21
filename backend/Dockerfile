# ============================================================================
# ElderLife AI — backend image
#
# Build (context is the REPOSITORY ROOT — run this from the repository root):
#   docker build -f backend/Dockerfile -t elderlife-backend .
#   docker run --rm -p 8000:8000 --env-file .env elderlife-backend
#
# Docker Compose does this for you; see docker-compose.yml.
#
# Design choices, and why:
#   * python:3.12-slim, NOT the 3.15 on the developer's Windows machine. Every
#     dependency in requirements.txt has a pre-built wheel on 3.12, so the image
#     builds without a C compiler and the version-pin workarounds noted in
#     requirements.txt are not needed here.
#   * A non-root user. The container runs as `elderlife`, so a compromise in the
#     app cannot write to system paths.
#   * Dependencies are copied and installed BEFORE the source code. Docker caches
#     each layer, so editing a Python file does not trigger a full re-install.
#   * No secrets are baked in. Everything comes from the environment at runtime.
# ============================================================================

FROM python:3.12-slim AS runtime

# Fail fast and never write .pyc files (they are useless in a container).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# `curl` is used only by the Compose healthcheck below. It is installed in its
# own layer so the rest of the image stays small and cacheable.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Dependencies -----------------------------------------------------------
# Copied on their own so this expensive layer is reused whenever only the
# application code changes. Note the path: the build context is the repository
# root, so it is `backend/requirements.txt`, not `requirements.txt`.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# --- Application code -------------------------------------------------------
# The build context is the REPOSITORY ROOT (see docker-compose.yml), because the
# backend imports the `ai` package, which lives outside backend/.
COPY backend/ ./backend/
COPY ai/ ./ai/
COPY pytest.ini ./pytest.ini

# --- Alembic ----------------------------------------------------------------
# alembic.ini lives inside backend/ and refers to its migration folder
# relatively, so migrations must run from that directory:
#   docker compose run --rm backend alembic upgrade head
# The working directory is set here for exactly that command. Uvicorn is
# unaffected because PYTHONPATH below is the repository root.
WORKDIR /app/backend

# --- Non-root user ----------------------------------------------------------
RUN useradd --create-home --shell /bin/bash elderlife \
    && chown -R elderlife:elderlife /app
USER elderlife

EXPOSE 8000

# The healthcheck mirrors the Compose one so `docker run` alone is also
# self-checking. /health performs a real database round-trip and reports
# "degraded" rather than lying when the database is unreachable.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD curl --fail --silent http://localhost:8000/health || exit 1

# The app is imported as a package (`backend.app.main`), so the repository root
# must be on the path. This is independent of the working directory above.
ENV PYTHONPATH=/app

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
