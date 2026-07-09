"""因子数据统一消费层 — 业务模块获取因子数据的唯一入口。

职责（docs/factor-system-design.md §5）：
  - load_cross_section_panel: 截面选股，加载 signal_date 截面 + 按 preprocess_policy 预处理
  - load_time_series_panel: 时序回测，加载单标的因子原始值
  - load_factor_series: Agent/API 宽表时序，原始值

路由依据：compute_mode + data_origin + preprocess_policy
底层委托：CrossSectionReader / factor_data_loader / FacFactorRegistry

设计原则：
  - 薄壳 Facade，不重写底层加载/预处理逻辑
  - 按因子 metadata 路由，precomputed 走 DB，on_demand 走注册表（P4 实现）
  - preprocess_policy='cross_section_standard' 执行 5 步截面标准化
  - preprocess_policy='raw' 返回原始值（如前向收益率）
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from framework.commons.logger import get_logger
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.services import factor_data_loader as fdl
from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader
from xqtrader.domain.factor.services.on_demand_compute_registry import get_registry
from xqtrader.domain.market.models.candlestick import CandlestickDaily

logger = get_logger(__name__)

# on_demand 因子计算所需的 OHLCV warmup 天数（日历日）
# 缠论/唐奇安等需历史笔/中枢/通道，1 年 warmup 足以稳定计算
_ON_DEMAND_WARMUP_DAYS = 365


class FactorPanelService:
    """因子数据统一消费入口 — 按元数据路由到现有加载服务。

    路由表（§5.2）：
      | compute_mode | data_origin | 加载方式 |
      | precomputed | computed/fund_flow | fac_factor_value |
      | precomputed | fina_indicator | fac_financial_factor_value + PIT ffill |
      | precomputed | daily_indicator | sdc_daily_indicator |
      | precomputed | computed + quarterly | fac_financial_composite_value + PIT ffill |
      | cross_section | cross_section_compute | CrossSectionFactorCalculator 实时算 |
      | on_demand | — | OnDemandComputeRegistry 插件实时算（P4） |
    """

    def __init__(self) -> None:
        self._reader = CrossSectionReader()

    async def load_cross_section_panel(
        self,
        factor_ids: list[str],
        symbols: list[str],
        signal_date: date,
        pool_id: str = "all",
    ) -> pd.DataFrame:
        """截面选股：加载 signal_date 截面 + 按 preprocess_policy 预处理。

        按 metadata.preprocess_policy 决定是否执行截面标准化：
          - cross_section_standard: 缺失填充→MAD→Z-score→中性化→再Z-score
          - raw: 不执行截面预处理（如前向收益率）

        Args:
            factor_ids: 因子 ID 列表
            symbols: 样本池标的列表
            signal_date: 截面日期
            pool_id: 样本池标识（仅用于路由与日志）

        Returns:
            MultiIndex(trade_date, symbol), columns=factor_ids
        """
        if not factor_ids or not symbols:
            return pd.DataFrame()

        # 加载行业映射和市值面板（截面预处理用）
        industry_map = await self._reader.load_industry_map(symbols)
        market_cap_panel = await self._reader.load_market_cap_panel(
            symbols, signal_date, signal_date,
        )

        panels: list[pd.DataFrame] = []
        for factor_id in factor_ids:
            meta = await self._load_factor_meta(factor_id)
            if meta is None:
                logger.warning("[factor_panel] 因子 %s 未在注册表找到,跳过", factor_id)
                continue

            # on_demand 因子为时序计算（chan/td_seq/donchian/close/volume），
            # 不支持截面快照消费（见 §19.5：cross_section 规则禁止引用 on_demand signal_id）
            if meta.compute_mode == "on_demand":
                raise NotImplementedError(
                    f"on_demand 因子 {factor_id} 不支持截面消费,"
                    f"请改用 load_time_series_panel（on_demand 因子为时序计算）"
                )

            # 加载原始面板（precomputed/cross_section 均通过 load_factor_raw_chunk 路由）
            raw = await fdl.load_factor_raw_chunk(
                signal_date, signal_date, factor_id, symbols, pool_id,
            )
            if raw.empty:
                logger.debug(
                    "[factor_panel] pool=%s factor=%s signal_date=%s 数据为空",
                    pool_id, factor_id, signal_date,
                )
                continue

            # 按 preprocess_policy 决定是否预处理
            if meta.preprocess_policy == "cross_section_standard":
                panel = self._reader.process_preloaded_factor_panel(
                    raw, pool_id, factor_id, industry_map, market_cap_panel,
                )
            else:
                # raw: 不执行截面预处理
                panel = raw

            if not panel.empty:
                panels.append(panel)

        if not panels:
            return pd.DataFrame()

        # 合并所有因子列
        result = panels[0]
        for p in panels[1:]:
            result = result.join(p, how="outer")

        logger.info(
            "[factor_panel] load_cross_section_panel pool=%s signal_date=%s "
            "factors=%d symbols=%d rows=%d",
            pool_id, signal_date, len(factor_ids), len(symbols), len(result),
        )
        return result

    async def load_time_series_panel(
        self,
        factor_ids: list[str],
        symbol: str,
        start_date: date,
        end_date: date,
        pool_id: str = "all",
    ) -> pd.DataFrame:
        """时序回测：加载单标的因子原始值（不执行截面预处理）。

        Args:
            factor_ids: 因子 ID 列表
            symbol: 单标的代码
            start_date: 起始日期
            end_date: 结束日期
            pool_id: 样本池标识

        Returns:
            index=trade_date, columns=factor_ids
        """
        if not factor_ids:
            return pd.DataFrame()

        # 分离 precomputed 和 on_demand
        precomputed_ids: list[str] = []
        on_demand_ids: list[str] = []
        for fid in factor_ids:
            meta = await self._load_factor_meta(fid)
            if meta is None:
                logger.warning("[factor_panel] 因子 %s 未在注册表找到,跳过", fid)
                continue
            if meta.compute_mode == "on_demand":
                on_demand_ids.append(fid)
            else:
                precomputed_ids.append(fid)

        parts: list[pd.DataFrame] = []

        # on_demand 因子：加载 OHLCV + 委托 OnDemandComputeRegistry 实时计算
        if on_demand_ids:
            on_demand_panel = await self._load_on_demand_panel(
                on_demand_ids, symbol, start_date, end_date,
            )
            if not on_demand_panel.empty:
                parts.append(on_demand_panel)

        # precomputed 因子：从 DB 加载（load_from_factor_value 内部按 data_origin 路由）
        if precomputed_ids:
            raw = await fdl.load_from_factor_value(
                start_date, end_date, precomputed_ids, [symbol], pool_id,
            )
            if not raw.empty and symbol in raw.index.get_level_values("symbol"):
                sliced = raw.xs(symbol, level="symbol")
                ts = sliced.to_frame().copy() if isinstance(sliced, pd.Series) else sliced.copy()
                parts.append(ts)

        if not parts:
            return pd.DataFrame()

        result = parts[0]
        for p in parts[1:]:
            result = result.join(p, how="outer")

        logger.info(
            "[factor_panel] load_time_series_panel symbol=%s pool=%s "
            "precomputed=%d on_demand=%d rows=%d range=[%s,%s]",
            symbol, pool_id, len(precomputed_ids), len(on_demand_ids),
            len(result), start_date, end_date,
        )
        return result

    async def load_factor_series(
        self,
        factor_ids: list[str],
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Agent/API 宽表时序：原始值。

        与 load_time_series_panel 的区别：固定 pool_id='all'，面向 API/Agent 消费。

        Args:
            factor_ids: 因子 ID 列表
            symbol: 单标的代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            index=trade_date, columns=factor_ids
        """
        return await self.load_time_series_panel(
            factor_ids, symbol, start_date, end_date, pool_id="all",
        )

    @staticmethod
    async def _load_factor_meta(factor_id: str) -> FacFactorRegistry | None:
        """从注册表加载因子元数据（含 compute_mode/density/preprocess_policy）。"""
        return await FacFactorRegistry.get_or_none(factor_id=factor_id)

    @staticmethod
    async def _load_on_demand_panel(
        factor_ids: list[str],
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """加载 on_demand 因子时序面板：OHLCV warmup 加载 + 委托注册表实时计算。

        缠论/唐奇安等需历史笔/中枢/通道，故在 start_date 前加载 1 年 warmup，
        计算完成后切片到 [start_date, end_date] 返回。

        Args:
            factor_ids: on_demand 因子 ID 列表
            symbol: 单标的代码
            start_date: 起始日期（结果切片左端）
            end_date: 结束日期

        Returns:
            index=trade_date, columns=已成功计算的 on_demand factor_ids 子集
        """
        registry = get_registry()
        # 校验：未注册的 on_demand 因子直接告警返回空（注册表可能未初始化）
        unregistered = [fid for fid in factor_ids if not registry.is_on_demand_factor(fid)]
        if unregistered:
            logger.warning(
                "[factor_panel] on_demand 因子 %s 未在注册表注册,跳过;"
                "请确认 register_default_on_demand_computes() 已执行",
                unregistered,
            )
        registered = [fid for fid in factor_ids if registry.is_on_demand_factor(fid)]
        if not registered:
            return pd.DataFrame()

        # 加载 OHLCV（含 1 年 warmup）
        warmup_start = start_date - timedelta(days=_ON_DEMAND_WARMUP_DAYS)
        records = await CandlestickDaily.filter(
            symbol=symbol,
            trade_date__gte=warmup_start,
            trade_date__lte=end_date,
            order_by=CandlestickDaily.trade_date.asc(),
        )
        if not records:
            logger.warning(
                "[factor_panel] on_demand OHLCV 为空 symbol=%s range=[%s,%s]",
                symbol, warmup_start, end_date,
            )
            return pd.DataFrame()

        ohlcv = pd.DataFrame(
            [
                {
                    "trade_date": r.trade_date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in records
            ]
        ).set_index("trade_date")

        # 委托注册表计算
        computed = registry.compute_factors(ohlcv, registered)
        if computed.empty:
            return pd.DataFrame()

        # 切片到请求区间（drop warmup）
        result = computed.loc[
            (computed.index >= pd.Timestamp(start_date))
            & (computed.index <= pd.Timestamp(end_date))
        ].copy()
        logger.info(
            "[factor_panel] on_demand 计算 symbol=%s factors=%d rows=%d (warmup=%d)",
            symbol, len(registered), len(result), len(ohlcv) - len(result),
        )
        return result
