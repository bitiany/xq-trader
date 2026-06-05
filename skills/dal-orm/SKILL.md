---
name: dal-orm
description: >-
  xqtrader 项目数据库 ORM 开发规范。基于 SQLAlchemy，由 framework/dal/base.py 封装
  Tortoise-ORM 风格 CRUD API，并支持 @transactional 声明式事务。在定义 ORM 模型、
  编写单表 CRUD、使用事务、或涉及 framework/dal 层数据库访问时必须遵循本 skill。
---

# dal-orm — 数据库 ORM 开发规范

## 何时使用

在以下场景 **必须** 加载并遵循本 skill：

| 场景 | 说明 |
|------|------|
| 新建 / 修改 ORM 模型 | 继承 `Base` 或 `AuditedBase` |
| 单表 CRUD | 使用 `Base` 提供的类方法 / 实例方法 |
| 多步写操作、跨表一致性 | 使用 `@transactional` 装饰器 |
| 审查数据库访问代码 | 检查是否绕过 DAL 封装 |

**与 db-tools 的分工**：业务代码走 DAL ORM；需要直接查库验证表结构或执行 SQL 时，使用 db-tools。

---

## 三条强制规则

1. **所有数据库模型，必须继承 `Base` 或 `AuditedBase`**
2. **所有的单表 CRUD 操作，必须遵循 `Base` 中提供的 API**
3. **需要事务时，可通过声明式的注解 `@transactional` 来实现**

---

## 1. 模型定义

### 基类选择

| 基类 | 适用场景 | 自带字段 |
|------|----------|----------|
| `AuditedBase` | 常规业务表（推荐默认） | `id`, `created_at`, `updated_at` |
| `Base` | 自定义主键、无审计字段、时序/分表等特殊表 | 无 |

```python
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean
from framework.dal.base import AuditedBase

class User(AuditedBase):
    __bind_key__ = "default"      # 数据源标识，省略时默认 "default"
    __tablename__ = "t_user"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
```

### 模型必备属性

- `__tablename__`：表名（必填）
- `__bind_key__`：多数据源路由（可选，默认 `"default"`）
- 字段使用 SQLAlchemy 2.0 风格：`Mapped[T]` + `mapped_column(...)`

### 禁止

- 业务模型直接继承 `DeclarativeBase` 或裸 SQLAlchemy Model（应通过 `Base`/`AuditedBase` 间接继承）
- 在业务层手写 `select()` / `session.execute()` 做单表 CRUD
- 在模型中封装绕过 `Base` API 的自定义 DB 访问方法

### 可选扩展

- **自定义主键表**：继承 `Base`，自行定义主键列，勿重复定义 `AuditedBase` 的 `id`
- **TimescaleDB 时序表**：在 `Base` 子类上使用 `@timescale(...)` 装饰器

---

## 2. 单表 CRUD — 必须使用 Base API

所有方法均为 **async**，风格类似 Tortoise-ORM。

### 查询（Read）

| 方法 | 用途 |
|------|------|
| `await Model.get(id)` | 按主键查单条，未找到返回 `None` |
| `await Model.get_by_id(id)` | 同上（别名） |
| `await Model.get_or_none(**filters)` | 按等值条件查单条（filter_by 语义） |
| `await Model.get_one_or_none(**filters)` | 按过滤条件查单条（filter + limit=1） |
| `await Model.filter(skip=0, limit=None, order_by=..., **filters)` | 条件列表 + 分页排序，`limit=None` 不限制返回数量 |
| `await Model.filter_with_or(or_conditions=..., or_groups=..., and_filters=..., skip=0, limit=100, order_by=...)` | OR 组合查询（详见下方） |
| `await Model.all(**filters)` | 查全部（可带过滤），等价于 `filter(limit=None)` |
| `await Model.count(**filters)` | 计数 |
| `await Model.count_with_or(or_conditions=..., or_groups=..., and_filters=...)` | OR 组合计数 |

```python
user = await User.get(1)
active = await User.filter(status=True, limit=20, order_by=User.created_at.desc())
total = await User.count(status=True)
one = await User.get_one_or_none(username="john")
all_users = await User.all(status=True)
```

### filter_with_or / count_with_or 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `or_conditions` | `list` | 单层 OR 条件列表，如 `[User.name.like('%x%'), User.code.like('%x%')]` |
| `or_groups` | `list[list]` | 多组 OR 条件，组间 AND、组内 OR |
| `and_filters` | `dict` | AND 过滤条件字典，如 `{'status': True}` |

`or_conditions` 与 `or_groups` 二选一，`or_groups` 优先。

```python
from sqlalchemy import or_

# 单层 OR
users = await User.filter_with_or(
    or_conditions=[User.name.like('%john%'), User.email.like('%john%')],
    and_filters={'status': True},
    limit=10
)

# 多组 OR（组间 AND）
users = await User.filter_with_or(
    or_groups=[
        [User.name.like('%john%'), User.email.like('%john%')],
        [User.status == True, User.is_verified == True],
    ],
    and_filters={'role': 'admin'},
)
```

### 创建（Create）

| 方法 | 用途 |
|------|------|
| `await Model.create(**kwargs)` | 创建并持久化，返回含主键的实例 |
| `instance = Model(**kwargs); await instance.save()` | 手动构造后保存 |

```python
user = await User.create(username="john", email="john@example.com")
```

### 更新（Update）

| 方法 | 用途 |
|------|------|
| `await instance.update({"field": value})` | 实例更新并保存 |
| `await Model.update_by_id(id, data)` | 按 ID 更新 |
| `await Model.update_by(data, **filters)` | 条件批量 UPDATE（高效，单条 SQL） |
| `await Model.bulk_update([(id, data), ...])` | 按 ID 列表批量更新 |

```python
await user.update({"status": False})
await User.update_by({"status": "active"}, id__in=[1, 2, 3])
```

### 删除（Delete）

| 方法 | 用途 |
|------|------|
| `await instance.delete()` | 删除实例，返回 `bool` |
| `await Model.delete_by_id(id)` | 按 ID 删除，返回 `bool` |
| `await Model.delete_many(**filters)` | 条件批量 DELETE（高效，单条 SQL），返回删除行数 |

```python
await User.delete_by_id(1)
await User.delete_many(status="inactive", created_at__lt="2024-01-01")
```

### 批量 Upsert

```python
await Model.bulk_create_or_update(
    instances,               # 模型实例列表
    on_conflict=["id"],      # 冲突检测字段，None 时用主键
    update_fields=["name"],  # 冲突时更新字段，None 时更新除主键/审计字段外的所有字段
    batch_size=500           # 分片大小
)
```

### 实例工具

| 方法 | 用途 |
|------|------|
| `instance.to_dict()` | 转字典 |
| `instance.update_from_dict(data)` | 仅更新内存属性（不持久化），支持链式调用 |
| `await instance.refresh()` | 从 DB 刷新 |

### 过滤语法速查

```
field=value          # 等于
field__in=[1,2,3]    # IN
field__like='%x%'    # LIKE（区分大小写）
field__ilike='%x%'   # ILIKE（不区分大小写）
field__gt=value      # 大于
field__gte=value     # 大于等于
field__lt=value      # 小于
field__lte=value     # 小于等于
field__ne=value      # 不等于
```

空值（`None`、空字符串、空列表）自动忽略，不会生成过滤条件。

---

## 3. 声明式事务 — @transactional

```python
from framework.dal.transaction import transactional, Propagation

@transactional()
async def create_user_with_profile(user_data, profile_data):
    user = await User.create(**user_data)
    await Profile.create(user_id=user.id, **profile_data)
    return user

@transactional(propagation=Propagation.REQUIRED, bind_key="stock")
async def write_to_stock_db(data):
    await Security.create(**data)
```

### 要点

- 装饰的函数必须是 **async**
- 装饰器内所有 `Base` CRUD 自动加入同一事务（事务感知 session）
- **数据源路由**：`bind_key=None`（默认）时，由 Base 层按各模型的 `__bind_key__` 自动路由；显式指定 `bind_key` 时，装饰器内所有操作使用指定数据源
- 异常自动回滚；正常结束自动提交

### Propagation 传播行为

| 值 | 行为 |
|----|------|
| `REQUIRED`（默认） | 有事务则加入，无则新建 |
| `REQUIRES_NEW` | 总是新建事务 |
| `MANDATORY` | 必须在已有事务中，否则报错 |
| `NOT_SUPPORTED` | 非事务执行 |
| `NEVER` | 禁止在事务中执行 |

### 何时加 @transactional

- 同一业务函数内有多条写操作
- 读-改-写需要一致性
- 跨模型操作需原子性

单条只读或单条写操作可不加；`Base` 方法在非事务环境下会自动创建临时 session。

---

## 4. 开发检查清单

编写或审查代码时逐项确认：

```
- [ ] 模型继承 Base 或 AuditedBase（禁止直接继承 DeclarativeBase）
- [ ] 定义了 __tablename__，按需设置 __bind_key__
- [ ] 单表 CRUD 全部通过 Base API，无手写 session/SQL
- [ ] 多步写操作用 @transactional 包裹
- [ ] 批量操作用 update_by / delete_many / bulk_create_or_update，非循环逐条
- [ ] 过滤条件使用 Tortoise 风格 kwargs，非原始 SQL WHERE
- [ ] 查库验证走 db-tools，业务逻辑走 DAL ORM
```

---

## 5. 反模式（禁止）

```python
# ❌ 直接操作 SQLAlchemy session
async with engines_manager.get_session("default") as db:
    result = await db.execute(select(User).where(...))

# ❌ 单表 CRUD 写原生 SQL
await db.execute(text("UPDATE t_user SET status = true WHERE id = 1"))

# ❌ 循环逐条更新/删除（应使用 update_by / delete_many）
for uid in ids:
    user = await User.get(uid)
    await user.update({"status": True})

# ❌ 业务模型直接继承 DeclarativeBase（应继承 Base 或 AuditedBase）
class User(DeclarativeBase): ...
```

---

## 6. 源码索引

| 文件 | 内容 |
|------|------|
| `framework/dal/base.py` | `Base` / `AuditedBase` 及全部 CRUD API |
| `framework/dal/transaction/transactional.py` | `@transactional` 装饰器 |
| `framework/dal/transaction/manager.py` | `Propagation` 枚举 |

详细 API 文档以 `framework/dal/base.py` 中各方法的 docstring 为准。
