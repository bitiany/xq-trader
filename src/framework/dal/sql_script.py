"""按语句拆分并执行 SQL 脚本（用于种子数据等幂等脚本）。"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def _strip_transaction_directives(sql: str) -> str:
    out_lines: list[str] = []
    for line in sql.splitlines():
        s = line.strip()
        if s.upper() in ("BEGIN;", "COMMIT;", "ROLLBACK;"):
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def _is_comment_only_statement(stmt: str) -> bool:
    for line in stmt.splitlines():
        t = line.strip()
        if not t:
            continue
        if not t.startswith("--"):
            return False
    return True


def iter_sql_statements(sql: str) -> list[str]:
    """
    将脚本拆成单条语句（按「行末分号」聚合多行语句）。
    适用于INSERT/ON CONFLICT 等多行 DDL/DML；不含 PL/pgSQL 函数体。
    """
    body = _strip_transaction_directives(sql)
    statements: list[str] = []
    chunk: list[str] = []
    for line in body.splitlines():
        chunk.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(chunk).strip()
            chunk = []
            if stmt and not _is_comment_only_statement(stmt):
                statements.append(stmt)
    if chunk:
        stmt = "\n".join(chunk).strip()
        if stmt and not _is_comment_only_statement(stmt):
            statements.append(stmt)
    return statements


async def execute_sql_statements_async(engine: AsyncEngine, sql: str) -> int:
    """在单事务中顺序执行拆分后的语句，返回执行条数。"""
    stmts = iter_sql_statements(sql)
    if not stmts:
        return 0
    async with engine.begin() as conn:
        for stmt in stmts:
            # 去掉纯包装空白，保留语句内换行
            cleaned = re.sub(r"^\s*\n", "", stmt)
            await conn.execute(text(cleaned))
    return len(stmts)
