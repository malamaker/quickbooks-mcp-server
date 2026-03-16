# WARNING: This container modifies live QuickBooks financial data.
# Review DISCLAIMER.md before deploying to a production environment.
# Ensure QuickBooks backups are configured before enabling the scheduler.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

ENV MCP_TRANSPORT=streamable-http
ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8080
ENV DATA_DIR=/app/data

EXPOSE 8080 8888

VOLUME /app/data

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8888/health')" || exit 1

CMD [".venv/bin/python", "main_quickbooks_mcp.py"]
