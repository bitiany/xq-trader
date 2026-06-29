# MCP 服务镜像
# 依赖管理：pyproject.toml [dependency-groups].mcp + uv.lock
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONPATH=/app/src \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple \
    MCP_SERVER_HOST=0.0.0.0 \
    MCP_SERVER_PORT=8097

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/mcp_server /app/src/mcp_server
COPY src/framework /app/src/framework

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-install-project --only-group mcp --no-dev \
    && rm -rf /root/.cache \
    && useradd -m -u 1000 mcp \
    && mkdir -p /config \
    && chown -R mcp:mcp /config /app

USER mcp

EXPOSE 8097

CMD ["python", "-m", "mcp_server", "--config", "/config/mcp_server.yml"]
