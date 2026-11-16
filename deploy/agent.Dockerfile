FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.14.7-slim-bookworm AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/apps/agent
COPY apps/agent/pyproject.toml apps/agent/uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

FROM python:3.14.7-slim-bookworm AS ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends curl xz-utils ca-certificates \
    && curl --fail --location --retry 3 \
    https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-31-12-59/ffmpeg-n8.1.3-27-g8dca1586f4-linux64-lgpl-8.1.tar.xz \
    --output /tmp/ffmpeg.tar.xz \
    && echo "a64f3171e6ad1f7d358d28890a907ee478c331d1177ec696a93418f79ac3f1f3  /tmp/ffmpeg.tar.xz" | sha256sum -c \
    && mkdir /opt/ffmpeg && tar -xJf /tmp/ffmpeg.tar.xz -C /opt/ffmpeg --strip-components=1

FROM python:3.14.7-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 agent \
    && mkdir -p /app/apps/server/audio && chown agent:agent /app/apps/server/audio
COPY --from=dependencies /app/apps/agent/.venv /app/apps/agent/.venv
COPY --from=ffmpeg /opt/ffmpeg /opt/ffmpeg
ENV PATH="/app/apps/agent/.venv/bin:/opt/ffmpeg/bin:$PATH" \
    PYTHONUNBUFFERED=1
COPY apps/agent/*.py apps/agent/pyproject.toml /app/apps/agent/
COPY content/ /app/content/
COPY apps/mobile/assets/sounds/*.mp3 /app/apps/mobile/assets/sounds/
COPY apps/mobile/assets/sounds/textures/*.mp3 /app/apps/mobile/assets/sounds/textures/
COPY assets/audio/prologue.mp3 /app/assets/audio/prologue.mp3
WORKDIR /app/apps/agent
USER agent
RUN ffmpeg -version && ffprobe -version
CMD ["python", "agent.py", "start"]
