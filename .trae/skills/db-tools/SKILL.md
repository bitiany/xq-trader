---
name: db-tools
description: >-
  PostgreSQL 数据库操作工具（Cursor 用户级 skill）。当需要查看表结构、执行只读查询、
  执行 INSERT/UPDATE/DELETE/DDL，或运行 .sql 脚本文件时，必须使用本 skill。
  禁止直接使用 psql、pgAdmin 或其他绕过 db_tools 的数据库访问方式。
---

# db-tools — PostgreSQL 数据库操作

## 工具位置

本 skill 安装在 Cursor 用户级目录：

```
%USERPROFILE%\.cursor\skills\db-tools\
├── SKILL.md
├── db_tools.py
└── .env
```

## 何时使用

在以下场景 **必须** 加载并遵循本 skill：

| 场景 | 使用命令 |
|------|----------|
| 查看 schema 下有哪些表、列、外键、索引 | `get_all_tables_info` |
| 只读查询（SELECT / WITH / EXPLAIN 等） | `execute_query` |
| 写操作或 DDL（INSERT / UPDATE / DELETE / CREATE / ALTER 等） | `execute_sql` |
| 执行 `.sql` 脚本（单文件或 glob 批量） | `execute_sql_file` |

## 前置条件

1. **Python 环境**：使用已安装 `sqlalchemy`、`python-dotenv`、`psycopg2` 的环境（如项目 conda 环境）。
2. **数据库连接**：通过 `%USERPROFILE%\.cursor\skills\db-tools\.env` 中的 `DATABASE_URL` 配置。
3. **ENV 变量**：执行前设置 `ENV` 指向 `.env` 文件路径。

```powershell
$DB_TOOLS = Join-Path $env:USERPROFILE ".cursor\skills\db-tools"
$env:ENV = Join-Path $DB_TOOLS ".env"
```

## 命令速查

```powershell
$DB_TOOLS = Join-Path $env:USERPROFILE ".cursor\skills\db-tools"
python (Join-Path $DB_TOOLS "db_tools.py") <command> [options]
```

| 命令 | 用途 | 安全约束 |
|------|------|----------|
| `get_all_tables_info` | 获取表元数据 | 只读 |
| `execute_query` | 执行查询 SQL | 仅允许 SELECT/WITH/EXPLAIN/SHOW/DESCRIBE；自动 LIMIT |
| `execute_sql` | 执行 DML/DDL | 自动识别 read/write/ddl |
| `execute_sql_file` | 执行 `.sql` 文件 | 单事务；默认遇错回滚 |

---

## 1. get_all_tables_info

获取指定 schema 下所有表的列、外键、索引信息。

```powershell
$DB_TOOLS = Join-Path $env:USERPROFILE ".cursor\skills\db-tools"
$env:ENV = Join-Path $DB_TOOLS ".env"
python (Join-Path $DB_TOOLS "db_tools.py") get_all_tables_info --schema public --json
```

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--schema` | 否 | `public` | PostgreSQL schema 名称 |
| `--json` | 否 | — | 输出结构化 JSON |

---

## 2. execute_query

执行只读 SQL 查询。若语句不含 `LIMIT`，自动追加 `--limit`（默认 1000）。

```powershell
$DB_TOOLS = Join-Path $env:USERPROFILE ".cursor\skills\db-tools"
$env:ENV = Join-Path $DB_TOOLS ".env"
python (Join-Path $DB_TOOLS "db_tools.py") execute_query `
  --sql "SELECT rule_code, rule_name FROM public.t_trade_signal_rule" `
  --limit 10 --json
```

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--sql` | 是 | — | 只读 SQL 语句 |
| `--limit` | 否 | `1000` | 最大返回行数 |
| `--json` | 否 | — | 输出 JSON 数组 |

---

## 3. execute_sql

执行 DML 或 DDL，自动识别语句类型并返回对应结构。

```powershell
$DB_TOOLS = Join-Path $env:USERPROFILE ".cursor\skills\db-tools"
$env:ENV = Join-Path $DB_TOOLS ".env"
python (Join-Path $DB_TOOLS "db_tools.py") execute_sql `
  --sql "UPDATE public.t_trade_signal_rule SET description='updated' WHERE rule_code='test'" `
  --json
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--sql` | 是 | 任意 SQL 语句 |
| `--json` | 否 | 输出 JSON |

**返回结构**：

| SQL 类型 | 返回 |
|----------|------|
| read | `{"type": "read", "rows": [...], "row_count": int}` |
| write | `{"type": "write", "affected_rows": int}` |
| ddl | `{"type": "ddl", "message": "DDL 执行成功"}` |

---

## 4. execute_sql_file

执行一个或多个 `.sql` 脚本文件，支持 glob 模式。文件路径相对于**当前工作目录**。

```powershell
$DB_TOOLS = Join-Path $env:USERPROFILE ".cursor\skills\db-tools"
$env:ENV = Join-Path $DB_TOOLS ".env"
python (Join-Path $DB_TOOLS "db_tools.py") execute_sql_file --file db/migrations/001_init.sql --json
python (Join-Path $DB_TOOLS "db_tools.py") execute_sql_file --file "db/migrations/*.sql" --json
```

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--file` | 是 | — | `.sql` 文件路径或 glob 模式 |
| `--no-stop` | 否 | `false` | 遇错继续执行（默认遇错停止并回滚） |
| `--json` | 否 | — | 输出 JSON 汇总 |

---

## 操作规范

1. **统一入口**：所有数据库操作必须通过用户级 `db_tools.py`，不得绕过。
2. **读写分离**：查询用 `execute_query`，写入/DDL 用 `execute_sql` 或 `execute_sql_file`。
3. **Schema 前缀**：SQL 中始终使用完整表名，如 `public.t_trade_signal_rule`。
4. **结构化输出**：程序化处理结果时加 `--json`。
5. **连接配置**：通过 `$env:ENV` 加载 `.env`，勿硬编码凭据。

## 命令选择流程

```
需要操作数据库？
├─ 查看表结构        → get_all_tables_info
├─ SELECT 查询       → execute_query
├─ 单条 INSERT/UPDATE/DELETE/DDL → execute_sql
└─ .sql 脚本文件     → execute_sql_file
```
