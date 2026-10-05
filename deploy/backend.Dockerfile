# Official multi-architecture image digests verified during implementation.
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS builder
WORKDIR /build
COPY pyproject.toml requirements.lock README.md ./
COPY src ./src
RUN python -m pip wheel --no-cache-dir -c requirements.lock --wheel-dir /wheels '.[retrieval]'

FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_DISABLE_IMPLICIT_TOKEN=1 \
    HF_HOME=/tmp/huggingface
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels 'agentic-investment-research[retrieval]' \
    && rm -rf /wheels \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /app/data /app/artifacts \
    && chown -R app:app /app
WORKDIR /app
USER 10001:10001
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/api/health', timeout=3)"
ENTRYPOINT ["researchdesk"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8010"]

FROM docker:28-cli@sha256:625d9431a9f54c5a2bc90f24f0e1c3d55b1349fd857dd85035f98c2c9acbdd4d AS docker-cli

FROM api AS worker
# Only the trusted worker receives this client and access to the host daemon.
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
HEALTHCHECK NONE
CMD ["worker"]
