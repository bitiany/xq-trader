# Agent Worker 镜像
# 依赖管理：pyproject.toml [dependency-groups].agent + uv.lock（与项目 uv 工作流一致）
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONPATH=/app/src \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple \
    PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple \
    PIP_DEFAULT_TIMEOUT=180 \
    AGENT_WORKSPACE=/workspace \
    ENV=/config/.env

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/agent /app/src/agent
COPY src/framework /app/src/framework
COPY src/xqtrader/domain/agent /app/src/xqtrader/domain/agent
COPY src/xqtrader/domain/watermark /app/src/xqtrader/domain/watermark
COPY docker/agent/stubs/xqtrader/__init__.py /app/src/xqtrader/__init__.py

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-install-project --only-group agent --no-dev \
    && rm -rf /root/.cache \
    && useradd -m -u 1000 agent \
    && mkdir -p /workspace /config \
    && chown -R agent:agent /workspace /config /app

USER agent

CMD ["python", "-m", "agent"]
