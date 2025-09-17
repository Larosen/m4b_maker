# Dockerfile with FFmpeg 7.1.2
FROM alpine:3.20

# Maintainer Info
LABEL maintainer="Unraid Community"
LABEL description="Modern audiobook converter with FFmpeg 7.1.2 and beets-audible integration"
LABEL version="1.0.0"

# Environment Variables
ENV PYTHONUNBUFFERED=1 \
    PUID=99 \
    PGID=100 \
    UMASK=002 \
    TZ=Europe/Berlin

# Install system dependencies with FFmpeg 7.1.2
RUN apk update && apk add --no-cache \
    python3 \
    python3-dev \
    py3-pip \
    ffmpeg=7.1.2-r0 \
    ffmpeg-dev=7.1.2-r0 \
    fdk-aac \
    fdk-aac-dev \
    mp4v2-tools \
    curl \
    wget \
    bash \
    shadow \
    tzdata \
    git \
    build-base \
    sqlite \
    && rm -rf /var/cache/apk/*

# Verify FFmpeg version and libfdk_aac support
RUN echo "=== FFmpeg Version Check ===" && \
    ffmpeg -version | head -1 && \
    echo "=== Checking libfdk_aac support ===" && \
    ffmpeg -hide_banner -h encoder=libfdk_aac | head -3

# Create user for container
RUN addgroup -g 100 users && \
    adduser -D -u 99 -G users -s /bin/bash abc

# Install Python packages
RUN pip3 install --no-cache-dir --break-system-packages \
    beets \
    requests \
    mutagen \
    pillow \
    pyyaml \
    watchdog \
    flask \
    gunicorn

# Install beets-audible plugin from GitHub
RUN pip3 install --no-cache-dir --break-system-packages \
    git+https://github.com/Neurrone/beets-audible.git

# Create directory structure
RUN mkdir -p /app /config /input /output /temp /logs && \
    chown -R abc:users /app /config /input /output /temp /logs

# Copy application files
COPY app/ /app/
COPY config/ /config/

# Make scripts executable
RUN chmod +x /app/*.py /app/*.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 /app/healthcheck.py

# Volumes
VOLUME ["/config", "/input", "/output", "/logs"]

# Working directory
WORKDIR /app

# Expose port for status API
EXPOSE 8080

# Switch to non-root user
USER abc

# Entry point
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "/app/main.py"]