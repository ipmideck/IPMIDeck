# Stage 1: Build frontend
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Python backend + built frontend
FROM python:3.11-slim

# OCI image metadata (D-11). VERSION/REVISION are build-args with safe defaults for a bare
# `docker build`; CI (docker/metadata-action + build-push-action, Plan 04) passes the real
# values. Image TAGS are produced by metadata-action in CI, NOT written here (D-12). The
# Python version INSIDE the image still resolves via attr: reading the copied branding.py
# (the COPY backend/ + pip install . flow below is unchanged; no .git needed).
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="IPMIDeck" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.source="https://github.com/ipmideck/IPMIDeck" \
      org.opencontainers.image.licenses="Apache-2.0"

# Install ipmitool
RUN apt-get update && apt-get install -y --no-install-recommends ipmitool && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
COPY backend/ ./backend/
RUN pip install --no-cache-dir .

# Copy built frontend
COPY --from=frontend /app/frontend/dist ./backend/static/

# Run as an unprivileged user rather than root. A fixed uid/gid keeps ownership predictable
# for anyone bind-mounting a host directory. No USER directive: the entrypoint has to start
# as root to adopt a data volume created by an older version of this image, and drops
# privileges itself once that is done — see docker-entrypoint.sh.
RUN groupadd --system --gid 1000 ipmideck && \
    useradd --system --create-home --uid 1000 --gid 1000 ipmideck && \
    mkdir -p /data && \
    chown -R ipmideck:ipmideck /data /app
ENV HOME=/home/ipmideck

# Environment
ENV IPMIDECK_DATA_DIR=/data
ENV IPMIDECK_DEMO=false

EXPOSE 3000

VOLUME ["/data"]

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/api/health')"

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "3000"]
