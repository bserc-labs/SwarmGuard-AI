# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Stage 2: Runner
FROM python:3.12-slim

# No apt layer. The health check previously needed curl, which meant every
# build reached out to deb.debian.org over plain HTTP -- a dependency that fails
# closed on any network that blocks port 80 or sits behind a proxy, and the
# failure surfaces as "Unable to locate package curl" rather than as a network
# error. Python is already in this image and can make an HTTP request, so the
# check has no external dependency and the image is smaller for it.

# Non-root user security hardening
RUN groupadd -r swarmguard && useradd -r -g swarmguard appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY . .

RUN chmod +x /app/entrypoint.sh && chown -R appuser:swarmguard /app
USER appuser

# 127.0.0.1 rather than localhost: localhost can resolve to [::1] first, and the
# server binds IPv4, so the check would fail against a healthy container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["/app/entrypoint.sh"]
