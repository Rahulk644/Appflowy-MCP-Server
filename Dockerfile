FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md KNOWLEDGE.md LICENSE ./
COPY appflowy_mcp ./appflowy_mcp
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12-slim
LABEL io.modelcontextprotocol.server.name="io.github.Rahulk644/appflowy-mcp-server"
WORKDIR /app
COPY --from=builder /wheels /tmp/wheels
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels
EXPOSE 8000
# Preserve the existing HTTP endpoint and reverse-proxy behavior.
CMD ["appflowy-mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]
