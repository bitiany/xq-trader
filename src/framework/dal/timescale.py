import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger("TIMESCALE")


@dataclass
class TimescaleTableConfig:
    time_column: str
    chunk_interval: str = "1 year"
    compress_after: str | None = None
    compress_segmentby: str | None = None


def timescale(
    time_column: str,
    chunk_interval: str = "1 month",
    compress_after: str | None = None,
    compress_segmentby: str | None = None,
) -> Callable[[type], type]:
    """
    声明式装饰器：标记 ORM 模型为 TimescaleDB hypertable

    Args:
        time_column: 时间分区键列名（必需）
        chunk_interval: 每个 chunk 覆盖的时间范围，默认 "1 month"
        compress_after: 数据写入多久后自动压缩，如 "3 months"
        compress_segmentby: 压缩时按此列分段存储，通常为高基数查询维度

    Usage:
        @timescale(time_column="trade_date", chunk_interval="1 month",
                   compress_after="3 months", compress_segmentby="symbol")
        class DailyBasic(Base):
            __tablename__ = "t_daily_basic"
            ...
    """
    def decorator(cls: type) -> type:
        setattr(
            cls,
            "__timescale_config__",
            TimescaleTableConfig(
                time_column=time_column,
                chunk_interval=chunk_interval,
                compress_after=compress_after,
                compress_segmentby=compress_segmentby,
            ),
        )
        return cls
    return decorator


class TimescaleManager:
    _sharded_configs: dict[str, TimescaleTableConfig] = {}
    _extension_checked: dict[int, bool] = {}

    def __init__(self, engine: AsyncEngine, schema: str = "public"):
        self.engine = engine
        self.schema = schema

    @classmethod
    def register_sharded_config(cls, logical_table: str, config: TimescaleTableConfig) -> None:
        cls._sharded_configs[logical_table] = config

    @classmethod
    def get_sharded_config(cls, logical_table: str) -> TimescaleTableConfig | None:
        return cls._sharded_configs.get(logical_table)

    @classmethod
    def clear_sharded_configs(cls) -> None:
        cls._sharded_configs.clear()

    def _qualified_table(self, table_name: str) -> str:
        if self.schema and self.schema != "public":
            return f"{self.schema}.{table_name}"
        return table_name

    async def enable_extension(self) -> bool:
        engine_id = id(self.engine)
        if engine_id in TimescaleManager._extension_checked:
            return TimescaleManager._extension_checked[engine_id]

        try:
            async with self.engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            logger.info("TimescaleDB 扩展已启用")
            TimescaleManager._extension_checked[engine_id] = True
            return True
        except Exception as e:
            logger.error(f"启用 TimescaleDB 扩展失败: {e}", exc_info=True)
            TimescaleManager._extension_checked[engine_id] = False
            return False

    async def is_hypertable(self, table_name: str) -> bool:
        try:
            async with self.engine.begin() as conn:
                result = await conn.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT 1 FROM timescaledb_information.hypertables
                            WHERE hypertable_name = :table_name
                            AND hypertable_schema = :schema
                        )
                    """),
                    {"table_name": table_name, "schema": self.schema},
                )
                return bool(result.scalar())
        except Exception:
            return False

    async def is_partitioned_table(self, table_name: str) -> bool:
        try:
            async with self.engine.begin() as conn:
                result = await conn.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT 1 FROM pg_partitioned_table pt
                            JOIN pg_class c ON c.oid = pt.partrelid
                            JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE c.relname = :table_name
                            AND n.nspname = :schema
                        )
                    """),
                    {"table_name": table_name, "schema": self.schema},
                )
                return bool(result.scalar())
        except Exception:
            return False

    async def _drop_incompatible_unique_indexes(
        self,
        conn: AsyncConnection,
        qualified: str,
        table_name: str,
        time_column: str,
    ) -> list[dict[str, Any]]:
        """
        删除不包含时间列的唯一索引/主键，返回需重建的索引信息列表。
        TimescaleDB 要求所有唯一索引必须包含分区键（时间列）。
        """
        indexes_to_rebuild = []

        result = await conn.execute(
            text("""
                SELECT indexname, indexdef FROM pg_indexes
                WHERE tablename = :table_name
                AND schemaname = :schema
                AND indexdef LIKE 'CREATE UNIQUE INDEX%'
            """),
            {"table_name": table_name, "schema": self.schema},
        )

        unique_indexes = result.fetchall()

        for row in unique_indexes:
            index_name, index_def = row[0], row[1]
            if time_column in index_def:
                continue

            is_pkey = "_pkey" in index_name
            logger.info(
                f"删除不兼容的唯一索引 {index_name} (不包含时间列 {time_column})"
            )

            if is_pkey:
                await conn.execute(
                    text(f'ALTER TABLE {qualified} DROP CONSTRAINT IF EXISTS {index_name}')
                )
            else:
                await conn.execute(
                    text(f'DROP INDEX IF EXISTS {self._qualified_table(index_name)}')
                )

            indexes_to_rebuild.append({
                "name": index_name,
                "def": index_def,
                "is_pkey": is_pkey,
            })

        return indexes_to_rebuild

    async def _rebuild_indexes_with_time_column(
        self,
        conn: AsyncConnection,
        qualified: str,
        time_column: str,
        indexes_to_rebuild: list[dict[str, Any]],
    ) -> None:
        """重建唯一索引，确保包含时间列"""
        for idx_info in indexes_to_rebuild:
            original_def = idx_info["def"]
            if idx_info["is_pkey"]:
                if time_column in original_def:
                    cols_match = re.search(r'\(([^)]+)\)\s*$', original_def)
                    cols = cols_match.group(1) if cols_match else "id"
                    await conn.execute(
                        text(
                            f'ALTER TABLE {qualified} ADD PRIMARY KEY ({cols})'
                        )
                    )
                    continue
                logger.info(
                    f"跳过主键重建 {idx_info['name']}：原主键不包含 {time_column}，"
                    f"改用普通索引代替"
                )
                cols_match = re.search(r'\(([^)]+)\)\s*$', original_def)
                pkey_cols = cols_match.group(1) if cols_match else "id"
                await conn.execute(
                    text(
                        f'CREATE INDEX IF NOT EXISTS {idx_info["name"]} '
                        f'ON {qualified} ({pkey_cols})'
                    )
                )
            else:
                if time_column in original_def:
                    await conn.execute(text(original_def))
                else:
                    col_part = original_def.split(" USING ")[0].split("(", 1)[1].rstrip(")")
                    new_def = (
                        f'CREATE UNIQUE INDEX {idx_info["name"]} '
                        f'ON {qualified} ({col_part}, {time_column})'
                    )
                    logger.info(f"重建唯一索引（添加时间列）: {idx_info['name']}")
                    await conn.execute(text(new_def))

    async def convert_to_hypertable(self, table_name: str, config: TimescaleTableConfig) -> bool:
        if await self.is_hypertable(table_name):
             # logger.info(f"表 {table_name} 已经是 hypertable，跳过转换")
            return True

        if await self.is_partitioned_table(table_name):
            logger.warning(
                f"表 {table_name} 是原生分区表，无法直接转换为 hypertable，"
                f"请先迁移数据并删除分区表后再重启服务"
            )
            return False

        try:
            qualified = self._qualified_table(table_name)
            async with self.engine.begin() as conn:
                indexes_to_rebuild = await self._drop_incompatible_unique_indexes(
                    conn, qualified, table_name, config.time_column
                )

                await conn.execute(
                    text(f"""
                        SELECT create_hypertable('{qualified}', '{config.time_column}',
                            if_not_exists => TRUE,
                            migrate_data => TRUE
                        )
                    """)
                )

                await conn.execute(
                    text(f"""
                        SELECT set_chunk_time_interval('{qualified}', INTERVAL '{config.chunk_interval}')
                    """)
                )

                await self._rebuild_indexes_with_time_column(
                    conn, qualified, config.time_column, indexes_to_rebuild
                )

            logger.info(
                f"表 {table_name} 已转换为 hypertable "
                f"(time_column={config.time_column}, chunk_interval={config.chunk_interval})"
            )
            return True
        except Exception as e:
            logger.error(f"转换表 {table_name} 为 hypertable 失败: {e}", exc_info=True)
            return False

    async def set_compression_policy(self, table_name: str, config: TimescaleTableConfig) -> bool:
        if not config.compress_after or not config.compress_segmentby:
            return True

        if not await self.is_hypertable(table_name):
            logger.warning(f"表 {table_name} 不是 hypertable，无法设置压缩策略")
            return False

        try:
            qualified = self._qualified_table(table_name)
            async with self.engine.begin() as conn:
                await conn.execute(
                    text(f"""
                        ALTER TABLE {qualified} SET (
                            timescaledb.compress,
                            timescaledb.compress_segmentby = '{config.compress_segmentby}'
                        )
                    """)
                )

                try:
                    await conn.execute(
                        text(f"""
                            SELECT add_compression_policy('{qualified}', INTERVAL '{config.compress_after}')
                        """)
                    )
                    # logger.debug(
                    #     f"表 {table_name} 压缩策略已配置 "
                    #     f"(compress_after={config.compress_after}, segmentby={config.compress_segmentby})"
                    # )
                except Exception as e:
                    err_msg = str(e).lower()
                    if "already exists" in err_msg or "duplicate" in err_msg:
                        logger.debug(f"表 {table_name} 压缩策略已存在，跳过")
                    else:
                        raise

            return True
        except Exception as e:
            logger.error(f"设置表 {table_name} 压缩策略失败: {e}", exc_info=True)
            return False

    async def initialize_table(self, table_name: str, config: TimescaleTableConfig) -> bool:
        converted = await self.convert_to_hypertable(table_name, config)
        if converted:
            await self.set_compression_policy(table_name, config)
        return converted

    async def initialize_all(self, tables_config: dict[str, TimescaleTableConfig]) -> dict[str, list[str]]:
        results: dict[str, list[str]] = {"success": [], "failed": [], "skipped": []}

        extension_ok = await self.enable_extension()
        if not extension_ok:
            logger.error("TimescaleDB 扩展不可用，跳过所有表初始化")
            for table_name in tables_config:
                results["skipped"].append(table_name)
            return results

        for table_name, config in tables_config.items():
            try:
                ok = await self.initialize_table(table_name, config)
                if ok:
                    results["success"].append(table_name)
                else:
                    results["failed"].append(table_name)
            except Exception as e:
                logger.error(f"初始化表 {table_name} TimescaleDB 失败: {e}", exc_info=True)
                results["failed"].append(table_name)

        # logger.info(
        #     f"TimescaleDB 初始化完成: "
        #     f"成功={len(results['success'])}, "
        #     f"失败={len(results['failed'])}, "
        #     f"跳过={len(results['skipped'])}"
        # )
        return results
