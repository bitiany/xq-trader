"""诊股评分 — 日频/季频因子截面百分位缓存。"""

from __future__ import annotations

from sqlalchemy import text

from framework.dal.enginee import engines_manager

_DAILY_FACTOR_IDS = (
    "composite_momentum",
    "composite_value",
    "composite_volatility",
    "composite_liquidity",
    "beta_250",
)

_FINANCIAL_FACTOR_IDS = (
    "composite_growth",
    "composite_quality",
    "composite_leverage",
)


class DiagnosisPercentileCache:
    """诊股模块所需的因子截面百分位缓存。"""

    def __init__(self) -> None:
        self.daily: dict[str, float | None] = dict.fromkeys(_DAILY_FACTOR_IDS)
        self.financial: dict[str, float | None] = dict.fromkeys(_FINANCIAL_FACTOR_IDS)

    async def warm_all(self, symbol: str) -> None:
        await self.warm_daily(symbol)
        await self.warm_financial(symbol)

    async def warm_daily(self, symbol: str) -> None:
        self.daily = dict.fromkeys(_DAILY_FACTOR_IDS)
        session_maker = engines_manager.get_session_maker("stock")
        async with session_maker() as session:
            result = await session.execute(
                text(
                    """
                    WITH latest AS (
                        SELECT factor_id, MAX(trade_date) AS trade_date
                        FROM stock.fac_factor_value
                        WHERE pool_id = 'all'
                          AND factor_id = ANY(:factor_ids)
                        GROUP BY factor_id
                    ),
                    sym AS (
                        SELECT f.factor_id, f.factor_value
                        FROM stock.fac_factor_value f
                        INNER JOIN latest l
                            ON f.factor_id = l.factor_id AND f.trade_date = l.trade_date
                        WHERE f.symbol = :symbol
                          AND f.pool_id = 'all'
                          AND f.factor_value IS NOT NULL
                    )
                    SELECT s.factor_id,
                        CASE WHEN COUNT(f.factor_value) = 0 THEN NULL
                        ELSE COUNT(*) FILTER (WHERE f.factor_value <= s.factor_value)::float
                             / COUNT(f.factor_value) * 100
                        END AS pct
                    FROM sym s
                    INNER JOIN latest l ON s.factor_id = l.factor_id
                    INNER JOIN stock.fac_factor_value f
                        ON f.factor_id = l.factor_id
                       AND f.trade_date = l.trade_date
                       AND f.pool_id = 'all'
                       AND f.factor_value IS NOT NULL
                    GROUP BY s.factor_id, s.factor_value
                    """,
                ),
                {"symbol": symbol, "factor_ids": list(_DAILY_FACTOR_IDS)},
            )
            for row in result:
                self.daily[row.factor_id] = float(row.pct) if row.pct is not None else None

    async def warm_financial(self, symbol: str) -> None:
        self.financial = dict.fromkeys(_FINANCIAL_FACTOR_IDS)
        session_maker = engines_manager.get_session_maker("stock")
        async with session_maker() as session:
            result = await session.execute(
                text(
                    """
                    WITH sym AS (
                        SELECT DISTINCT ON (factor_id)
                            factor_id, end_date, factor_value
                        FROM stock.fac_financial_factor_value
                        WHERE symbol = :symbol
                          AND factor_id = ANY(:factor_ids)
                          AND factor_value IS NOT NULL
                        ORDER BY factor_id, ann_date DESC
                    )
                    SELECT s.factor_id,
                        CASE WHEN COUNT(f.factor_value) = 0 THEN NULL
                        ELSE COUNT(*) FILTER (WHERE f.factor_value <= s.factor_value)::float
                             / COUNT(f.factor_value) * 100
                        END AS pct
                    FROM sym s
                    INNER JOIN stock.fac_financial_factor_value f
                        ON f.factor_id = s.factor_id AND f.end_date = s.end_date
                       AND f.factor_value IS NOT NULL
                    GROUP BY s.factor_id, s.factor_value
                    """,
                ),
                {"symbol": symbol, "factor_ids": list(_FINANCIAL_FACTOR_IDS)},
            )
            for row in result:
                self.financial[row.factor_id] = float(row.pct) if row.pct is not None else None
