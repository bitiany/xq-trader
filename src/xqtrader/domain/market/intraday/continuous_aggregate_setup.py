"""TimescaleDB Continuous Aggregate 与 retention policy 初始化

在 FastAPI lifespan 中调用，为 sdc_candlestick_1m 表创建：
- 5m/15m/30m/1h Continuous Aggregate（自动增量聚合，替代降采样）
- 每个 CA 的刷新策略（schedule_interval=5 minutes）
- 1m 原始表的 retention policy（2 年后自动 drop）

幂等设计：所有操作均检查是否已存在，可重复执行。
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("INTRADAY")

# Continuous Aggregate 定义：(后缀, time_bucket 参数)
_CAGG_DEFINITIONS: list[tuple[str, str]] = [
    ("5m", "5 minutes"),
    ("15m", "15 minutes"),
    ("30m", "30 minutes"),
    ("1h", "1 hour"),
]


async def setup_continuous_aggregates(engine: AsyncEngine) -> None:
    """创建 5m/15m/30m/1h Continuous Aggregate + 刷新策略 + retention policy

    幂等：所有操作均检查是否已存在，可重复执行。
    前置条件：sdc_candlestick_1m 已通过 DatasourceManager 转为 hypertable。
    """
    # 前置检查：base table 必须为 hypertable
    if not await _is_hypertable(engine, "sdc_candlestick_1m"):
        logger.warning("sdc_candlestick_1m 不是 hypertable，跳过 Continuous Aggregate 初始化")
        return

    for suffix, bucket in _CAGG_DEFINITIONS:
        view_name = f"sdc_candlestick_{suffix}_cagg"
        await _create_continuous_aggregate(engine, view_name, bucket)
        await _add_cagg_policy(engine, view_name)

    await _add_retention_policy(engine)
    logger.info("Continuous Aggregate 初始化完成: 5m/15m/30m/1h + retention policy")


async def _is_hypertable(engine: AsyncEngine, table_name: str) -> bool:
    """检查表是否为 TimescaleDB hypertable"""
    sql = text("""
        SELECT 1 FROM timescaledb_information.hypertables
        WHERE hypertable_name = :table_name
    """)
    async with engine.connect() as conn:
        result = await conn.execute(sql, {"table_name": table_name})
        return result.fetchone() is not None


async def _create_continuous_aggregate(engine: AsyncEngine, view_name: str, bucket: str) -> None:
    """创建单个 Continuous Aggregate（幂等，IF NOT EXISTS）"""
    sql = text(f"""
        CREATE MATERIALIZED VIEW IF NOT EXISTS {view_name}
        WITH (timescaledb.continuous) AS
        SELECT
            symbol,
            time_bucket('{bucket}', trade_time) AS trade_time,
            first(open, trade_time) AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, trade_time) AS close,
            sum(volume) AS volume,
            sum(amount) AS amount,
            trade_date
        FROM sdc_candlestick_1m
        GROUP BY symbol, time_bucket('{bucket}', trade_time), trade_date
        WITH NO DATA
    """)
    try:
        async with engine.begin() as conn:
            await conn.execute(sql)
        logger.debug("Continuous Aggregate 已创建: %s", view_name)
    except Exception as e:
        err_msg = str(e).lower()
        if "already exists" in err_msg:
            logger.debug("Continuous Aggregate 已存在，跳过: %s", view_name)
        else:
            logger.error("创建 Continuous Aggregate 失败: %s, error=%s", view_name, e, exc_info=True)
            raise


async def _add_cagg_policy(engine: AsyncEngine, view_name: str) -> None:
    """为 Continuous Aggregate 添加刷新策略（幂等）

    schedule_interval=5 minutes，降低 job 调度开销
    start_offset=3 days，覆盖周末缺口
    end_offset=5 minutes，避免刷新未完成的最新桶
    """
    sql = text(f"""
        SELECT add_continuous_aggregate_policy(
            '{view_name}',
            start_offset => INTERVAL '3 days',
            end_offset => INTERVAL '5 minutes',
            schedule_interval => INTERVAL '5 minutes'
        )
    """)
    try:
        async with engine.begin() as conn:
            await conn.execute(sql)
        logger.debug("CA 刷新策略已添加: %s", view_name)
    except Exception as e:
        err_msg = str(e).lower()
        if "already exists" in err_msg or "duplicate" in err_msg:
            logger.debug("CA 刷新策略已存在，跳过: %s", view_name)
        else:
            logger.error("添加 CA 刷新策略失败: %s, error=%s", view_name, e, exc_info=True)
            raise


async def _add_retention_policy(engine: AsyncEngine) -> None:
    """为 sdc_candlestick_1m 添加 retention policy（2 年后自动 drop，幂等）"""
    sql = text("""
        SELECT add_retention_policy(
            'sdc_candlestick_1m',
            INTERVAL '2 years'
        )
    """)
    try:
        async with engine.begin() as conn:
            await conn.execute(sql)
        logger.debug("retention policy 已添加: sdc_candlestick_1m (2 years)")
    except Exception as e:
        err_msg = str(e).lower()
        if "already exists" in err_msg or "duplicate" in err_msg:
            logger.debug("retention policy 已存在，跳过: sdc_candlestick_1m")
        else:
            logger.error("添加 retention policy 失败: sdc_candlestick_1m, error=%s", e, exc_info=True)
            raise
