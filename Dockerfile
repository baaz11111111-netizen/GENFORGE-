# GENFORGE production image — dual target:
#   1. Hugging Face Spaces (Docker SDK, free CPU tier): root Dockerfile contract
#      - container runs as UID 1000, app binds $PORT (default 7860)
#   2. VPS via docker-compose.yml (PORT=8501 override, named volumes)
# FFmpeg/ffprobe installed via apt and verified at build time.
# No .env, no local data dirs, no caches in the image (see .dockerignore).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg/ffprobe for all media processing + curl for the container healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Fail the build immediately if the media toolchain is missing
RUN ffmpeg -version | head -n 1 && ffprobe -version | head -n 1

# Hugging Face Spaces contract: runtime user is UID 1000; set it up before COPY
RUN useradd -m -u 1000 user

USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH
WORKDIR $HOME/app

# CPU-only PyTorch wheel (Space free tier has no GPU; VPS image stays lean)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY --chown=user requirements.txt .
RUN pip install -r requirements.txt

# Application code only — data directories are mounted/persisted at runtime
COPY --chown=user . .

USER root
RUN chmod +x $HOME/app/docker/entrypoint.sh
USER user

# Default is the HF Spaces port; compose overrides PORT=8501 for VPS
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-7860}/_stcore/health || exit 1

ENTRYPOINT ["./docker/entrypoint.sh"]
