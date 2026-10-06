# Both runtimes use Debian bookworm. Official multi-platform digests checked 2026-10-05.
FROM node:24-bookworm-slim@sha256:eae779f20e0cdf264247f6f3b4e62510d91f168a615117ed38430ba295f55590 AS frontend
WORKDIR /build/web
ENV NEXT_TELEMETRY_DISABLED=1
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS backend
WORKDIR /build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
# Build tools stay in this stage (some dependency releases have source-only wheels).
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml requirements.lock README.md ./
COPY src/ ./src/
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir -c requirements.lock .
COPY examples/public_demo.py examples/forecast_lifecycle_verification.py \
    examples/instrument_comparison_verification.py ./examples/
# This builds prescribed synthetic records from an empty database. No export or keys.
RUN /opt/venv/bin/python examples/public_demo.py build --output /demo > /dev/null

FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production PORT=10000
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 demo \
    && useradd --uid 10001 --gid demo --no-create-home --shell /usr/sbin/nologin demo
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=backend /opt/venv /opt/venv
WORKDIR /app
COPY --from=frontend /build/web/.next/standalone ./web/
COPY --from=frontend /build/web/.next/static ./web/.next/static/
COPY --from=backend /demo ./demo/
COPY examples/public_demo.py ./examples/public_demo.py
COPY deploy/public_demo_runtime.py ./deploy/public_demo_runtime.py
# The runtime user cannot alter the package, even on a host with a writable root FS.
RUN chmod 0555 /app/demo && chmod 0444 /app/demo/* \
    && ldd /usr/local/bin/node \
    && /usr/local/bin/node --version && /opt/venv/bin/python --version
USER 10001:10001
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD ["/opt/venv/bin/python", "/app/deploy/public_demo_runtime.py", "health"]
ENTRYPOINT ["/opt/venv/bin/python", "/app/deploy/public_demo_runtime.py"]
