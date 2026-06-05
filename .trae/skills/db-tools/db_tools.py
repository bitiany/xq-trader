r"""
PostgreSQL 数据库操作 CLI — xqtrader db-tools Skill

提供四类能力：
  - get_all_tables_info  获取 schema 下表结构元数据
  - execute_query        只读查询（SELECT / WITH / EXPLAIN 等）
  - execute_sql          写操作与 DDL（INSERT / UPDATE / DELETE / CREATE 等）
  - execute_sql_file     执行 .sql 脚本文件（支持 glob）

用法（Cursor 用户级 skill）:
    $DB_TOOLS = Join-Path $env:USERPROFILE ".cursor\skills\db-tools"
    $env:ENV = Join-Path $DB_TOOLS ".env"
    python (Join-Path $DB_TOOLS "db_tools.py") get_all_tables_info --schema public
    python (Join-Path $DB_TOOLS "db_tools.py") execute_query --sql "SELECT 1" --json
    python (Join-Path $DB_TOOLS "db_tools.py") execute_sql --sql "UPDATE public.t SET x=1 WHERE id=1" --json
    python (Join-Path $DB_TOOLS "db_tools.py") execute_sql_file --file migrations/001_init.sql --json
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_READ_ONLY_KEYWORDS = re.compile(
    r"^\s*(SELECT|WITH|EXPLAIN|SHOW|DESCRIBE)\b", re.IGNORECASE | re.DOTALL
)
_WRITE_KEYWORDS = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|TRUNCATE)\b", re.IGNORECASE | re.DOTALL
)
_DDL_KEYWORDS = re.compile(
    r"^\s*(CREATE|ALTER|DROP|GRANT|REVOKE|COMMENT)\b", re.IGNORECASE | re.DOTALL
)


def load_env_file(env_path: str) -> bool:
    """加载指定的 .env 文件。"""
    path = Path(env_path)
    if not path.is_absolute():
        path = Path.cwd() / path

    if not path.exists():
        print(f"[WARN] .env 文件不存在：{path}", file=sys.stderr)
        return False

    success = load_dotenv(str(path))
    if success:
        print(f"[OK] 已加载环境变量：{path}")
    else:
        print(f"[WARN] 加载 .env 文件失败：{path}", file=sys.stderr)
    return success


def get_database_url() -> str:
    """从环境变量读取 DATABASE_URL。"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("未设置 DATABASE_URL，请先配置 %USERPROFILE%\\.cursor\\skills\\db-tools\\.env 或设置 ENV 环境变量")
    return database_url


def _get_sync_engine() -> Engine:
    """获取同步 SQLAlchemy 引擎。"""
    database_url = get_database_url()
    if "psycopg2" not in database_url:
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://")
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )


def get_all_tables_info(schema: str = "public") -> list[dict[str, Any]]:
    """
    获取指定 schema 下所有表的元数据（列、外键、索引）。

    Args:
        schema: PostgreSQL schema 名称，默认 public。

    Returns:
        表信息列表，每项包含 schema、name、columns、foreign_keys、indexes。
    """
    engine = _get_sync_engine()
    metadata = MetaData()
    metadata.reflect(bind=engine, schema=schema)

    tables_info: list[dict[str, Any]] = []
    inspector = inspect(engine)

    for table_name in inspector.get_table_names(schema=schema):
        columns_info = [
            {
                "name": column["name"],
                "type": str(column["type"]),
                "nullable": column["nullable"],
                "default": column.get("default"),
                "primary_key": column.get("primary_key", False),
            }
            for column in inspector.get_columns(table_name, schema=schema)
        ]
        tables_info.append(
            {
                "schema": schema,
                "name": table_name,
                "columns": columns_info,
                "foreign_keys": inspector.get_foreign_keys(table_name, schema=schema),
                "indexes": inspector.get_indexes(table_name, schema=schema),
            }
        )

    return tables_info


def _classify_sql(sql: str) -> str:
    """
    分类 SQL 语句类型。

    Returns:
        'read' | 'write' | 'ddl'
    """
    stripped = sql.strip()
    if not stripped:
        raise ValueError("SQL 语句不能为空")
    if _READ_ONLY_KEYWORDS.match(stripped):
        return "read"
    if _WRITE_KEYWORDS.match(stripped):
        return "write"
    if _DDL_KEYWORDS.match(stripped):
        return "ddl"
    return "write"


def execute_query(
    sql: str,
    params: dict[str, Any] | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """
    执行只读 SQL 查询。

    仅允许 SELECT / WITH / EXPLAIN / SHOW / DESCRIBE。
    若语句未包含 LIMIT，自动追加 limit 参数（默认 1000）。

    Raises:
        ValueError: 语句不是只读类型。
        RuntimeError: 执行失败。
    """
    sql_type = _classify_sql(sql)
    if sql_type != "read":
        raise ValueError(
            f"execute_query 仅允许只读查询，当前语句被分类为: {sql_type}。"
            f"写操作请使用 execute_sql。"
        )

    engine = _get_sync_engine()
    has_limit = re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE)
    final_sql = sql if has_limit else f"{sql.rstrip(';')} LIMIT {limit}"

    try:
        with engine.connect() as conn:
            result = conn.execute(text(final_sql), params or {})
            columns = result.keys()
            data = [dict(zip(columns, row)) for row in result.fetchall()]
        logger.info("execute_query 成功, 返回 %d 行", len(data))
        return data
    except Exception as exc:
        logger.error("execute_query 执行失败: %s", exc)
        raise RuntimeError(f"查询执行失败: {exc}") from exc


def execute_sql(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    执行任意 SQL（DML / DDL），自动识别语句类型。

    Returns:
        read:  {"type": "read", "rows": [...], "row_count": int}
        write: {"type": "write", "affected_rows": int}
        ddl:   {"type": "ddl", "message": "DDL 执行成功"}
    """
    sql_type = _classify_sql(sql)
    engine = _get_sync_engine()

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params or {})

            if sql_type == "read":
                columns = result.keys()
                rows = [dict(zip(columns, row)) for row in result.fetchall()]
                logger.info("execute_sql[read] 成功, 返回 %d 行", len(rows))
                return {"type": "read", "rows": rows, "row_count": len(rows)}

            if sql_type == "write":
                conn.commit()
                affected = result.rowcount
                logger.info("execute_sql[write] 成功, 影响 %d 行", affected)
                return {"type": "write", "affected_rows": affected}

            conn.commit()
            logger.info("execute_sql[ddl] 成功")
            return {"type": "ddl", "message": "DDL 执行成功"}

    except Exception as exc:
        logger.error("execute_sql 执行失败, type=%s, 错误: %s", sql_type, exc)
        raise RuntimeError(f"SQL 执行失败: {exc}") from exc


def _strip_sql_comments(content: str) -> str:
    """移除 SQL 单行与块注释。"""
    content = re.sub(r"--.*$", "", content, flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)


def _split_sql_statements(content: str) -> list[str]:
    """按分号拆分 SQL 语句，忽略引号内的分号。"""
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False

    for char in content:
        if char == "'" and not in_double:
            in_single = not in_single
            current.append(char)
        elif char == '"' and not in_single:
            in_double = not in_double
            current.append(char)
        elif char == ";" and not in_single and not in_double:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(char)

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _resolve_sql_files(file_pattern: str) -> list[Path]:
    """
    解析 .sql 文件路径，支持 glob（如 migrations/*.sql）。

    Raises:
        FileNotFoundError: 未匹配到任何文件。
        ValueError: 匹配到的文件不是 .sql。
    """
    matched = sorted(Path(p) for p in glob.glob(file_pattern, recursive=True))
    if not matched:
        candidate = Path(file_pattern)
        if candidate.exists():
            matched = [candidate]
        else:
            raise FileNotFoundError(f"未找到 SQL 文件: {file_pattern}")

    for path in matched:
        if path.suffix.lower() != ".sql":
            raise ValueError(f"仅支持 .sql 文件: {path}")

    return matched


def execute_sql_file(file_pattern: str, stop_on_error: bool = True) -> dict[str, Any]:
    """
    执行一个或多个 .sql 脚本文件。

    支持：
    - 单文件路径或 glob 模式（如 db/migrations/*.sql）
    - 多条语句（分号分隔，忽略引号内分号）
    - 单行注释 (-- ) 与块注释 (/* */)
    - 单事务：全部成功则提交，任一失败则回滚（stop_on_error=True 时）

    Returns:
        {
            "files": [...],
            "total": int,
            "succeeded": int,
            "failed": int,
            "results": [...]
        }
    """
    sql_files = _resolve_sql_files(file_pattern)
    all_statements: list[tuple[str, int, str]] = []

    for sql_file in sql_files:
        content = _strip_sql_comments(sql_file.read_text(encoding="utf-8"))
        for index, stmt in enumerate(_split_sql_statements(content), start=1):
            all_statements.append((str(sql_file), index, stmt))

    if not all_statements:
        return {
            "files": [str(p) for p in sql_files],
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
        }

    engine = _get_sync_engine()
    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    with engine.connect() as conn:
        for file_path, stmt_index, stmt in all_statements:
            label = f"{file_path}#{stmt_index}"
            try:
                result = conn.execute(text(stmt))
                sql_type = _classify_sql(stmt)

                if sql_type == "read":
                    row_count = len(result.fetchall())
                    entry: dict[str, Any] = {
                        "file": file_path,
                        "index": stmt_index,
                        "type": "read",
                        "row_count": row_count,
                    }
                elif sql_type == "write":
                    entry = {
                        "file": file_path,
                        "index": stmt_index,
                        "type": "write",
                        "affected_rows": result.rowcount,
                    }
                else:
                    entry = {
                        "file": file_path,
                        "index": stmt_index,
                        "type": "ddl",
                        "message": "OK",
                    }

                results.append(entry)
                succeeded += 1
                print(f"  [{label}] OK: {stmt[:80]}{'...' if len(stmt) > 80 else ''}")

            except Exception as exc:
                failed += 1
                results.append(
                    {
                        "file": file_path,
                        "index": stmt_index,
                        "type": "error",
                        "error": str(exc),
                        "sql": stmt[:200],
                    }
                )
                print(f"  [{label}] ERROR: {str(exc)[:120]}")
                if stop_on_error:
                    conn.rollback()
                    print(f"\n[WARN] 已回滚。成功 {succeeded} 条, 失败 {failed} 条")
                    return {
                        "files": [str(p) for p in sql_files],
                        "total": len(all_statements),
                        "succeeded": succeeded,
                        "failed": failed,
                        "results": results,
                    }

        if failed == 0:
            conn.commit()
            print(f"\n[OK] SQL 脚本执行完成: {succeeded}/{len(all_statements)} 条成功, 已提交")
        else:
            conn.rollback()
            print(f"\n[WARN] SQL 脚本执行: {succeeded} 成功, {failed} 失败, 已回滚")

    return {
        "files": [str(p) for p in sql_files],
        "total": len(all_statements),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def _print_query_preview(rows: list[dict[str, Any]], row_count: int) -> None:
    print(f"\n[OK] 查询返回 {row_count} 行:")
    if not rows:
        return
    print("\n前 5 条示例:")
    for i, row in enumerate(rows[:5], 1):
        print(f"\n  行 {i}:")
        for key, value in list(row.items())[:8]:
            print(f"    {key}: {value}")
    if len(rows) > 5:
        print(f"\n  ... 共 {len(rows)} 行")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PostgreSQL 数据库操作工具 (xqtrader db-tools)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  $DB_TOOLS = Join-Path $env:USERPROFILE ".cursor\\skills\\db-tools"
  python (Join-Path $DB_TOOLS "db_tools.py") get_all_tables_info --schema public
  python (Join-Path $DB_TOOLS "db_tools.py") execute_query --sql "SELECT version()" --json
  python (Join-Path $DB_TOOLS "db_tools.py") execute_sql --sql "UPDATE public.t SET x=1 WHERE id=1" --json
  python (Join-Path $DB_TOOLS "db_tools.py") execute_sql_file --file db/migrations/*.sql --json
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    p_info = subparsers.add_parser("get_all_tables_info", help="获取 schema 下所有表元数据")
    p_info.add_argument("--schema", type=str, default="public", help="schema 名称 (默认 public)")
    p_info.add_argument("--json", action="store_true", help="输出 JSON")

    p_query = subparsers.add_parser("execute_query", help="执行只读 SQL 查询")
    p_query.add_argument("--sql", type=str, required=True, help="SELECT 查询语句")
    p_query.add_argument("--limit", type=int, default=1000, help="最大返回行数 (默认 1000)")
    p_query.add_argument("--json", action="store_true", help="输出 JSON")

    p_sql = subparsers.add_parser("execute_sql", help="执行 DML/DDL SQL")
    p_sql.add_argument("--sql", type=str, required=True, help="SQL 语句")
    p_sql.add_argument("--json", action="store_true", help="输出 JSON")

    p_file = subparsers.add_parser("execute_sql_file", help="执行 .sql 脚本文件 (支持 glob)")
    p_file.add_argument("--file", type=str, required=True, help=".sql 文件路径或 glob 模式")
    p_file.add_argument("--no-stop", action="store_true", help="遇错继续执行 (默认遇错停止并回滚)")
    p_file.add_argument("--json", action="store_true", help="输出 JSON")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    env_path = os.getenv("ENV")
    if env_path:
        load_env_file(env_path)

    try:
        if args.command == "get_all_tables_info":
            result = get_all_tables_info(args.schema)
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(f"\n[OK] Schema '{args.schema}' 共有 {len(result)} 个表:")
                for table in result:
                    print(f"\n  {table['name']}")
                    print(f"     列数: {len(table['columns'])}")
                    if table["foreign_keys"]:
                        print(f"     外键: {len(table['foreign_keys'])}")
                    if table["indexes"]:
                        print(f"     索引: {len(table['indexes'])}")

        elif args.command == "execute_query":
            query_rows = execute_query(args.sql, limit=args.limit)
            if args.json:
                print(json.dumps(query_rows, indent=2, default=str))
            else:
                _print_query_preview(query_rows, len(query_rows))

        elif args.command == "execute_sql":
            sql_result = execute_sql(args.sql)
            if args.json:
                print(json.dumps(sql_result, indent=2, default=str))
            elif sql_result["type"] == "read":
                _print_query_preview(sql_result["rows"], sql_result["row_count"])
            elif sql_result["type"] == "write":
                print(f"\n[OK] 写操作完成, 影响 {sql_result['affected_rows']} 行")
            else:
                print(f"\n[OK] {sql_result['message']}")

        elif args.command == "execute_sql_file":
            file_result = execute_sql_file(args.file, stop_on_error=not args.no_stop)
            if args.json:
                print(json.dumps(file_result, indent=2, default=str))
            sys.exit(0 if file_result["failed"] == 0 else 1)

    except Exception as exc:
        print(f"\n[ERROR] 执行失败: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
