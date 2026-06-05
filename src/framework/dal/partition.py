"""
PostgreSQL 分区表管理器 [DEPRECATED]

已弃用：请使用 TimescaleDB 替代原生分区方案。
TimescaleDB 提供自动分区管理、列式压缩、更优的查询性能，是原生分区的超集。

保留此模块仅供降级场景使用（数据库不支持 TimescaleDB 扩展时）。
"""
import logging
from datetime import date, timedelta
from typing import Any, cast

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, String, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.schema import Table
from sqlalchemy.sql.type_api import TypeEngine

logger = logging.getLogger("PARTITION")

SQLALCHEMY_TO_PG_TYPE = {
    String: "VARCHAR",
    Float: "DOUBLE PRECISION",
    Integer: "INTEGER",
    Date: "DATE",
    DateTime: "TIMESTAMP",
    Boolean: "BOOLEAN",
    Numeric: "NUMERIC",
}


class PartitionManager:
    """
    PostgreSQL 分区表管理器

    用于管理按日期/时间分区的表，自动创建和维护分区。
    基于 ORM 模型定义动态生成 DDL，与实体定义保持一致。
    """

    def __init__(self, engine: AsyncEngine, schema: str = "public"):
        self.engine = engine
        self.schema = schema

    async def create_partitioned_table(
        self,
        model_class: type[DeclarativeBase],
        partition_key: str = "trade_date",
        partition_type: str = "RANGE",
        interval_months: int = 12,
        start_year: int | None = None,
        years_ahead: int = 2,
    ) -> None:
        """
        基于 ORM 模型创建分区表（如果不存在）

        在同一个事务中完成主表创建和子分区创建，确保分区能引用到主表。

        Args:
            model_class: SQLAlchemy ORM 模型类
            partition_key: 分区键列名
            partition_type: 分区类型 (RANGE, LIST, HASH)
            interval_months: 分区间隔月数
            start_year: 分区起始年份，默认为当前年份-5
            years_ahead: 提前创建年数，默认2
        """
        table_name = model_class.__tablename__
        table = cast(Table, model_class.__table__)

        if start_year is None:
            start_year = date.today().year - 5

        async with self.engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = :schema
                        AND table_name = :table_name
                    )
                """),
                {"schema": self.schema, "table_name": table_name},
            )
            exists = result.scalar()

            if not exists:
                ddl = self._build_partitioned_table_ddl(table_name, table, partition_key, partition_type)
                await conn.execute(text(ddl))
                logger.info(f"分区表 {self.schema}.{table_name} 创建成功")

                await self._create_partitions_ahead_with_conn(
                    conn, table_name, partition_key, interval_months,
                    start_year=start_year, years_ahead=years_ahead,
                )
            else:
                logger.info(f"分区表 {self.schema}.{table_name} 已存在，跳过创建")
                await self._ensure_partitions_cover_range_with_conn(
                    conn, table_name, partition_key, interval_months,
                    start_year=start_year, years_ahead=years_ahead,
                )

    def _build_partitioned_table_ddl(
        self,
        table_name: str,
        table: Table,
        partition_key: str,
        partition_type: str,
    ) -> str:
        """
        基于 SQLAlchemy Table 对象动态生成分区表的 CREATE TABLE DDL

        Args:
            table_name: 表名
            table: SQLAlchemy Table 对象
            partition_key: 分区键列名
            partition_type: 分区类型

        Returns:
            CREATE TABLE ... PARTITION BY DDL 语句
        """
        column_defs = []
        pk_columns = []

        for col in table.columns:
            pg_type = self._get_pg_type(col.type)
            parts = [f'"{col.name}"', pg_type]

            if not col.nullable and not col.primary_key:
                parts.append("NOT NULL")

            if col.primary_key:
                pk_columns.append(f'"{col.name}"')

            column_defs.append(" ".join(parts))

        if pk_columns:
            column_defs.append(f"PRIMARY KEY ({', '.join(pk_columns)})")

        columns_sql = ",\n    ".join(column_defs)

        ddl = f"""CREATE TABLE {self.schema}.{table_name} (
    {columns_sql}
) PARTITION BY {partition_type} ("{partition_key}")"""

        return ddl

    def _get_pg_type(self, col_type: TypeEngine[Any]) -> str:
        """
        将 SQLAlchemy 列类型映射为 PostgreSQL 类型

        Args:
            col_type: SQLAlchemy 列类型实例

        Returns:
            PostgreSQL 类型字符串
        """
        for sa_type, pg_type in SQLALCHEMY_TO_PG_TYPE.items():
            if isinstance(col_type, sa_type):
                if isinstance(col_type, String) and col_type.length is not None:
                    return f"VARCHAR({col_type.length})"
                if isinstance(col_type, Numeric) and col_type.precision is not None:
                    if col_type.scale is not None:
                        return f"NUMERIC({col_type.precision},{col_type.scale})"
                    return f"NUMERIC({col_type.precision})"
                return pg_type

        type_name = type(col_type).__name__
        logger.warning(f"未识别的 SQLAlchemy 类型: {type_name}，回退为 TEXT")
        return "TEXT"

    async def _create_partitions_ahead_with_conn(
        self,
        conn: AsyncConnection,
        table_name: str,
        partition_key: str = "trade_date",
        interval_months: int = 12,
        start_year: int | None = None,
        years_ahead: int = 2,
    ) -> None:
        """
        在同一事务中提前创建分区（覆盖历史年份和未来年份）

        Args:
            conn: 数据库连接（同一事务）
            table_name: 表名
            partition_key: 分区键
            interval_months: 分区间隔月数
            start_year: 分区起始年份
            years_ahead: 提前创建年数
        """
        today = date.today()
        if start_year is None:
            start_year = today.year - 5
        end_year = today.year + years_ahead

        if interval_months == 12:
            for year in range(start_year, end_year + 1):
                partition_name = f"{table_name}_y{year}"
                start_date = f"{year}-01-01"
                end_date = f"{year + 1}-01-01"
                await self._create_partition_with_conn(conn, table_name, partition_name, start_date, end_date)
        else:
            months_ahead = (end_year - today.year) * 12 // interval_months + 1
            months_back = (today.year - start_year) * 12 // interval_months
            for i in range(-months_back, months_ahead + 1):
                partition_date = date(today.year, today.month, 1)
                partition_date = self._add_months(partition_date, i * interval_months)
                next_date = self._add_months(partition_date, interval_months)

                if interval_months >= 12:
                    partition_name = f"{table_name}_y{partition_date.year}"
                else:
                    partition_name = f"{table_name}_p{partition_date.strftime('%Y%m')}"

                start_date = partition_date.strftime("%Y-%m-%d")
                end_date = next_date.strftime("%Y-%m-%d")
                await self._create_partition_with_conn(conn, table_name, partition_name, start_date, end_date)

    async def _ensure_partitions_cover_range_with_conn(
        self,
        conn: AsyncConnection,
        table_name: str,
        partition_key: str,
        interval_months: int,
        start_year: int | None = None,
        years_ahead: int = 2,
    ) -> None:
        """
        检查并补充分区，确保覆盖历史和未来数据范围（同一事务）
        """
        existing = await self._list_partitions_with_conn(conn, table_name)
        existing_names = {p["name"] for p in existing}

        today = date.today()
        if start_year is None:
            start_year = today.year - 5
        end_year = today.year + years_ahead

        if interval_months == 12:
            for year in range(start_year, end_year + 1):
                partition_name = f"{table_name}_y{year}"
                if partition_name not in existing_names:
                    start_date = f"{year}-01-01"
                    end_date = f"{year + 1}-01-01"
                    await self._create_partition_with_conn(conn, table_name, partition_name, start_date, end_date)
                    logger.info(f"补充创建分区: {partition_name}")

    async def _create_partition_with_conn(
        self,
        conn: AsyncConnection,
        table_name: str,
        partition_name: str,
        start_date: str,
        end_date: str,
    ) -> bool:
        """
        在同一事务中创建单个分区
        """
        check_result = await conn.execute(
            text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = :schema
                    AND table_name = :partition_name
                )
            """),
            {"schema": self.schema, "partition_name": partition_name},
        )
        exists = check_result.scalar()

        if exists:
            logger.debug(f"分区 {partition_name} 已存在，跳过")
            return False

        sql = f"""
            CREATE TABLE {self.schema}.{partition_name}
            PARTITION OF {self.schema}.{table_name}
            FOR VALUES FROM ('{start_date}') TO ('{end_date}')
        """
        await conn.execute(text(sql))
        logger.info(f"分区 {partition_name} 创建成功 ({start_date} - {end_date})")
        return True

    async def _list_partitions_with_conn(
        self,
        conn: AsyncConnection,
        table_name: str,
    ) -> list[dict]:
        """
        在同一事务中列出表的所有分区
        """
        result = await conn.execute(
            text("""
                SELECT
                    child.relname AS partition_name,
                    pg_get_expr(pt.partexprs, pt.partrelid) AS partition_expr
                FROM pg_inherits i
                JOIN pg_class parent ON parent.oid = i.inhparent
                JOIN pg_class child ON child.oid = i.inhrelid
                JOIN pg_partitioned_table pt ON pt.partrelid = parent.oid
                WHERE parent.relname = :table_name
                AND parent.relnamespace = (
                    SELECT oid FROM pg_namespace WHERE nspname = :schema
                )
                ORDER BY child.relname
            """),
            {"table_name": table_name, "schema": self.schema},
        )
        return [
            {"name": row[0], "bound": row[1]}
            for row in result.fetchall()
        ]

    async def create_partition(
        self,
        table_name: str,
        partition_name: str,
        start_date: str,
        end_date: str,
    ) -> bool:
        """
        创建单个分区

        Args:
            table_name: 父表名
            partition_name: 分区名
            start_date: 起始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)

        Returns:
            是否创建成功
        """
        async with self.engine.begin() as conn:
            check_result = await conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = :schema
                        AND table_name = :partition_name
                    )
                """),
                {"schema": self.schema, "partition_name": partition_name},
            )
            exists = check_result.scalar()

            if exists:
                logger.debug(f"分区 {partition_name} 已存在，跳过")
                return False

            sql = f"""
                CREATE TABLE {self.schema}.{partition_name}
                PARTITION OF {self.schema}.{table_name}
                FOR VALUES FROM ('{start_date}') TO ('{end_date}')
            """
            await conn.execute(text(sql))
            logger.info(f"分区 {partition_name} 创建成功 ({start_date} - {end_date})")
            return True

    async def drop_old_partitions(
        self,
        table_name: str,
        keep_months: int = 24,
    ) -> list[str]:
        """
        删除过老的分区

        Args:
            table_name: 表名
            keep_months: 保留最近N个月的分区

        Returns:
            被删除的分区列表
        """
        cutoff_date = date.today()
        cutoff_date = date(cutoff_date.year, cutoff_date.month, 1)
        cutoff_date = self._add_months(cutoff_date, -keep_months)

        async with self.engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT child.relname AS partition_name
                    FROM pg_inherits i
                    JOIN pg_class parent ON parent.oid = i.inhparent
                    JOIN pg_class child ON child.oid = i.inhrelid
                    WHERE parent.relname = :table_name
                    AND parent.relnamespace = (
                        SELECT oid FROM pg_namespace WHERE nspname = :schema
                    )
                    ORDER BY child.relname
                """),
                {"table_name": table_name, "schema": self.schema},
            )
            partitions = [row[0] for row in result.fetchall()]

        dropped = []
        for partition_name in partitions:
            try:
                if "_y" in partition_name:
                    year_str = partition_name.split("_y")[-1]
                    part_date = date(int(year_str), 1, 1)
                elif "_p" in partition_name:
                    date_str = partition_name.split("_p")[-1]
                    if len(date_str) == 6:
                        part_date = date(int(date_str[:4]), int(date_str[4:6]), 1)
                    else:
                        continue
                else:
                    continue

                if part_date < cutoff_date:
                    await self._drop_partition(table_name, partition_name)
                    dropped.append(partition_name)
            except (ValueError, IndexError):
                continue

        if dropped:
            logger.info(f"删除过老分区: {dropped}")

        return dropped

    async def _drop_partition(self, table_name: str, partition_name: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(f"DROP TABLE IF EXISTS {self.schema}.{partition_name}")
            )
            logger.info(f"已删除分区: {partition_name}")

    async def list_partitions(self, table_name: str) -> list[dict]:
        """
        列出表的所有分区

        Args:
            table_name: 表名

        Returns:
            分区信息列表
        """
        async with self.engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT
                        child.relname AS partition_name,
                        pg_get_expr(pt.partexprs, pt.partrelid) AS partition_expr
                    FROM pg_inherits i
                    JOIN pg_class parent ON parent.oid = i.inhparent
                    JOIN pg_class child ON child.oid = i.inhrelid
                    JOIN pg_partitioned_table pt ON pt.partrelid = parent.oid
                    WHERE parent.relname = :table_name
                    AND parent.relnamespace = (
                        SELECT oid FROM pg_namespace WHERE nspname = :schema
                    )
                    ORDER BY child.relname
                """),
                {"table_name": table_name, "schema": self.schema},
            )
            return [
                {"name": row[0], "bound": row[1]}
                for row in result.fetchall()
            ]

    @staticmethod
    def _add_months(source_date: date, months: int) -> date:
        month = source_date.month + months
        year = source_date.year + (month - 1) // 12
        month = (month - 1) % 12 + 1

        last_day_of_month = date(year, month, 1)
        if month == 12:
            last_day_of_month = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day_of_month = date(year, month + 1, 1) - timedelta(days=1)

        day = min(source_date.day, last_day_of_month.day)
        return date(year, month, day)
