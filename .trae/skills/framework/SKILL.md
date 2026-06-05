---
name: framework
description: >-
  xqtrader 项目 FastAPI 框架使用规范。涵盖路由定义、响应处理、异常处理、
  日志使用、以及单元测试与 API 集成测试的编写方式。
  在开发 API 路由、处理业务异常、编写测试时必须遵循本 skill。
---

# framework — FastAPI 框架使用规范

## 何时使用

| 场景 | 说明 |
|------|------|
| 新建 / 修改 API 路由 | 按领域模块组织路由 |
| 处理业务异常 | 使用 BusinessException 体系 |
| 编写单元测试 | ORM 层功能验证 |
| 编写 API 集成测试 | REST 接口黑盒验证 |
| 使用日志 | 统一日志规范 |

---

## 1. 路由定义

### 目录结构

```
src/xqtrader/
├── api/                          # API 路由层
│   ├── __init__.py               # 顶层聚合，挂载 v1
│   └── v1/                       # 版本化路由
│       ├── __init__.py           # v1 聚合，统一 API_PREFIX
│       ├── health.py             # 健康检查（平铺路由）
│       └── {module}/             # 领域模块目录
│           ├── __init__.py       # 导出 router
│           └── router.py         # 路由定义
├── domain/                       # 领域层
│   └── {module}/
│       ├── models.py             # ORM 模型
│       └── services/             # 业务逻辑
└── main.py                       # 应用工厂
```

### 路由注册规则

1. **领域路由**放在 `api/v1/{module}/` 子目录下，每个模块一个目录
2. **通用路由**（如 health）直接放在 `api/v1/` 下
3. 每个模块目录的 `__init__.py` 导出 `router`
4. `api/v1/__init__.py` 聚合所有子模块路由，统一设置 `prefix=settings.APP.API_PREFIX`

### 新增领域模块

**1) 路由** — `api/v1/trade/router.py`：

```python
from fastapi import APIRouter, Query
from framework.commons.exceptions import NotFoundException
from xqtrader.domain.trade.services.trade_service import TradeService

router = APIRouter(prefix="/trades", tags=["交易"])
_service = TradeService()


@router.get("", summary="查询交易列表")
async def list_trades(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> dict:
    return await _service.list_trades(page=page, page_size=page_size)


@router.get("/{trade_id}", summary="查询交易详情")
async def get_trade(trade_id: str) -> dict:
    trade = await _service.get_by_id(trade_id)
    if trade is None:
        raise NotFoundException(message=f"交易 {trade_id} 不存在")
    return trade
```

**2) 导出** — `api/v1/trade/__init__.py`：`from xqtrader.api.v1.trade.router import router`

**3) 注册** — 在 `api/v1/__init__.py` 中：`router.include_router(trade_router)`

### 要点

- 路由函数 **直接返回业务数据**，无需手动包装 ResponseModel
- 分页接口返回 `{"items": [...], "total": N, "page": N, "page_size": N}`
- Service 实例在模块级别创建（`_service = XxxService()`）
- 返回类型注解使用 `dict`，不使用 `ResponseModel`

---

## 2. 响应处理

所有 API 响应由中间件自动包装为：

```json
{"code": 0, "message": "success", "data": { ... }}
```

**业务层无需关心包装逻辑**，直接返回数据即可。分页响应的 `data` 字段包含 `items`/`total`/`page`/`page_size`。

跳过包装的路径：`/docs`、`/redoc`、`/openapi.json`、`/health`、`/ws*`

---

## 3. 异常处理

### 异常体系

```python
from framework.commons.exceptions import (
    BusinessException,       # 基类（code=400）
    UnauthorizedException,   # 未授权（code=401）
    NotFoundException,       # 资源不存在（code=404）
    ConflictException,       # 数据冲突（code=409）
)
```

### 使用方式

在路由或 Service 中直接 `raise`：

```python
raise NotFoundException(message="证券 000001.SZ 不存在")
raise ConflictException(message="该证券代码已存在")
raise BusinessException(message="余额不足", code=400)
```

所有异常自动转换为 `{"code": N, "message": "...", "data": null}` 格式响应。自动处理：`BusinessException`(400) / `NotFoundException`(404) / `UnauthorizedException`(401) / `ConflictException`(409) / `RequestValidationError`(422) / `Exception`(500)。

---

## 4. 日志使用

```python
from framework.commons.logger import get_logger

logger = get_logger("MODULE_NAME")
logger.info("处理请求: %s", request_id)
```

访问日志由中间件自动记录（方法、路径、状态码、耗时、request_id）。

---

## 5. 测试规范

### Fixture

| Fixture | 作用域 | 用途 |
|---------|--------|------|
| `app_with_datasource` | session | 含数据源的 FastAPI 实例（单元测试用） |
| `api_client` | session | httpx 异步客户端（API 集成测试用） |

均在 `conftest.py` 中定义，自动触发 lifespan 初始化数据源。

### 单元测试（ORM 层）

```python
import pytest
from xqtrader.domain.security.models import Security


class TestSecurityModel:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_one_or_none(self, app_with_datasource):
        security = await Security.get_one_or_none(symbol="000001.SZ")
        assert security is not None
        assert security.symbol == "000001.SZ"
```

### API 集成测试（REST 接口）

```python
import pytest

API_PREFIX = "/api/v1"


class TestSecurityAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_list_securities(self, api_client):
        response = await api_client.get(f"{API_PREFIX}/securities")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] > 0

    @pytest.mark.asyncio(loop_scope="session")
    async def test_not_found(self, api_client):
        response = await api_client.get(f"{API_PREFIX}/securities/NOTEXIST.XX")
        assert response.status_code == 404
        assert response.json()["code"] == 404
```

### 要点

- 异步测试使用 `@pytest.mark.asyncio(loop_scope="session")`
- API 测试验证完整响应格式（`code`/`message`/`data`）
- 覆盖正常流程 + 异常流程（404、422 等）
- 环境初始化在 `conftest.py` 统一处理

---

## 6. 开发检查清单

```
- [ ] 路由按领域模块放在 api/v1/{module}/ 下
- [ ] 路由函数直接返回业务数据，不手动包装 ResponseModel
- [ ] 业务异常使用 BusinessException 体系，不抛原生 Exception
- [ ] Service 在模块级别实例化
- [ ] 日志使用 get_logger()，不使用 print()
- [ ] ORM 模型遵循 dal-orm skill 规范
- [ ] API 集成测试使用 api_client fixture
- [ ] 单元测试使用 app_with_datasource fixture
```
