# xq-trader

量化交易平台 API 服务，基于 FastAPI + SQLAlchemy 构建，采用领域驱动设计分层架构。

## 项目结构

```
xq-trader/
├── src/                            # 源码根目录
│   ├── framework/                  # 核心框架（DAL、中间件、配置、通用工具）
│   │   ├── commons/                # 公共工具（异常、日志、加解密）
│   │   ├── config/                 # 配置管理（settings、环境变量）
│   │   ├── dal/                    # 数据访问层（Base ORM、数据源、事务）
│   │   └── middleware/             # HTTP 中间件（响应包装、异常处理、日志、认证）
│   └── xqtrader/                   # 业务应用
│       ├── api/                    # API 路由层
│       │   └── v1/                 # 版本化路由（按领域模块划分子目录）
│       ├── domain/                 # 领域层（models + services）
│       ├── lifespan.py             # 应用 lifespan 管理
│       └── main.py                 # 应用工厂（create_app）
├── tests/                          # 测试目录
│   ├── conftest.py                 # 测试公共配置（sys.path、数据源 fixture、API client）
│   ├── framework/                  # framework 单元测试
│   └── api/                        # API 集成测试
├── skills/                         # Trae skill 定义（dal-orm、framework、db-tools）
├── .conda/                         # Python 虚拟环境
├── .env                            # 环境变量（数据库连接等）
├── .trae/rules/                    # Trae 规则配置
├── datasource.yml                  # 多数据源配置（占位符由环境变量解析）
└── pyproject.toml                  # 项目元数据与工具配置
```

## 环境要求

- **Python**：3.12+
- **虚拟环境**：项目根目录下 `.conda`
- **操作系统**：Windows，终端使用 PowerShell
- **包管理**：pip，镜像源 `https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple`
- **数据库**：PostgreSQL（多 schema：default / stock / research / trading）

## 快速启动

### 1. 激活虚拟环境

```powershell
conda activate .\.conda
```

### 2. 配置环境变量

复制并编辑 `.env` 文件，配置数据库连接信息：

```
DATABASES_DEFAULT_HOST=localhost
DATABASES_DEFAULT_PORT=5432
DATABASES_DEFAULT_USER=postgres
DATABASES_DEFAULT_PASSWORD=your_password
DATABASES_DEFAULT_DB=xqtrader
...
```

### 3. 启动服务

```powershell
uvicorn xqtrader.main:create_app --factory --host 0.0.0.0 --port 8096
```

### 4. 启动 Worker（异步任务调度）

```powershell
# 启动 Celery Worker（支持 4 个并发任务）
celery -A worker.celery_entry worker --loglevel=info -c 4

# 启动 Celery Beat（定时任务）
celery -A worker.celery_entry beat --loglevel=info
```

**参数说明**：
- `-c 4`：启动 4 个并发工作进程，支持并行处理任务
- `--loglevel=info`：日志级别为 info

### 5. Worker CLI 工具

通过命令行发送任务和管理分布式锁：

```powershell
# 设置环境
conda activate .\.conda
$env:PYTHONPATH="src"
```

**列出所有已注册任务**：

```powershell
python -m worker.cli list
```

**发送任务**：

```powershell
# 因子计算 — 全量模式，指定标的
python -m worker.cli run factor.compute_daily --symbols 000001.SZ,600519.SH --mode full

# 因子计算 — 增量模式，全市场
python -m worker.cli run factor.compute_daily --mode incremental

# 因子计算 — 指定日期范围
python -m worker.cli run factor.compute_daily --start-date 2024-01-01 --end-date 2024-12-31

# 资金流采集
python -m worker.cli run market.fund_flow_collect --symbols 000001.SZ

# 日线行情采集
python -m worker.cli run market.daily_kline_collect

# 传递额外参数
python -m worker.cli run factor.compute_daily --kwargs max_workers=5 warmup_bars=500
```

**管理分布式锁**：

```powershell
# 查看所有任务锁
python -m worker.cli lock-list

# 释放指定任务的锁（任务异常退出后锁未释放时使用）
python -m worker.cli lock-release factor.compute_daily

# 释放所有任务锁
python -m worker.cli lock-release-all
```

### 6. 访问文档

- Swagger UI：http://localhost:8096/docs
- ReDoc：http://localhost:8096/redoc
- 健康检查：http://localhost:8096/api/v1/health

## 运行测试

```powershell
conda activate .\.conda
pytest tests/ -v
```

仅运行 API 集成测试：

```powershell
pytest tests/api/ -v
```

仅运行 framework 单元测试：

```powershell
pytest tests/framework/ -v
```

## 静态检查

```powershell
conda activate .\.conda
ruff check src/ tests/
mypy src/
```

## 架构概览

### 请求处理链

```
Request → LoggingMiddleware → AuthMiddleware → ResponseMiddleware → Route Handler
                                                                              ↓
Response ← ResponseMiddleware（自动包装） ← ExceptionHandlers（异常捕获） ← Business Logic
```

### 核心约定

- **路由定义**：按领域模块组织在 `api/v1/{module}/` 下，路由函数直接返回业务数据
- **响应格式**：由 `ResponseMiddleware` 自动包装为 `{code, message, data}` 格式
- **异常处理**：使用 `BusinessException` 体系，由 `exception_handlers` 统一捕获
- **数据访问**：ORM 模型继承 `Base` / `AuditedBase`，CRUD 遵循 dal-orm skill 规范
- **数据源管理**：通过 `register_datasource` 在 `create_app()` 中注册，lifespan 自动初始化
- **日志规范**：使用 `get_logger()` 获取日志器，访问日志由中间件自动记录

### 数据源配置

数据源定义在 `datasource.yml`，通过 `${ENV_VAR}` 占位符从 `.env` 读取连接信息。当前配置 4 个数据源（default / stock / research / trading），均指向同一 PostgreSQL 实例的不同 schema。
