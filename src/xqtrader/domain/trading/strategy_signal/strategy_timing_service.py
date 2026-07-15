"""策略择时历史服务 — 记录信号 + 后续走势比对 + 策略胜率计算

设计原则（文档 §10.5 阶段 5）:
  - 每次调用 strategy-timing 写入一条记录，含 symbol/as_of/signals/decision/confidence
  - 后续走势比对时回填 actual_return/verdict/compared_at/compare_window_days
  - 按 rule_id 聚合 verdict 计算策略胜率，样本数 ≥ 30 时启用权重反哺
  - 与 BacktestService 解耦：BacktestService 跑回测生成历史绩效，本服务记录实盘时点信号 + 走势回测

胜率判定规则（与 aggregated_signal 对齐）:
  - buy  + return >  +0.5% → win
  - buy  + return <  -0.5% → loss
  - sell + return <  -0.5% → win（做空方向正确）
  - sell + return >  +0.5% → loss
  - hold + |return| < 1.0% → win（观望正确，未错过趋势）
  - hold + |return| > 1.0% → loss（错过趋势）
  - 其它（中性区间）→ neutral
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from framework.commons.exceptions import BusinessException
from framework.commons.logger import get_logger
from framework.dal.transaction.transactional import transactional
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.trading.models.strategy_timing_history import StrategyTimingHistory

logger = get_logger("STRATEGY.TIMING")

# ── verdict 判定阈值（%） ────────────────────────────────────────────
_BUY_WIN_THRESHOLD = 0.5  # buy + return > 0.5% 视为 win
_SELL_WIN_THRESHOLD = -0.5  # sell + return < -0.5% 视为 win
_HOLD_WIN_ABS_THRESHOLD = 1.0  # hold + |return| < 1.0% 视为 win

# ── 走势比对默认参数 ────────────────────────────────────────────────
_DEFAULT_COMPARE_WINDOW_DAYS = 5
_COMPARE_BATCH_SIZE = 100

# ── 胜率反哺启用阈值 ────────────────────────────────────────────────
_MIN_SAMPLES_FOR_WEIGHT_FEEDBACK = 30


class StrategyTimingService:
    """策略择时历史服务 — 记录信号、走势比对、胜率计算。

    与 BacktestService 解耦：
      - BacktestService：跑历史回测，输出绩效指标（一次性、批量）
      - 本服务：记录实盘每次择时信号，比对后续走势，反哺聚合权重（持续、增量）
    """

    # ────────────────────────── 记录择时信号 ──────────────────────────

    @transactional(bind_key="trading")
    async def record_timing(
        self,
        *,
        symbol: str,
        as_of: date,
        aggregated_signal: str,
        confidence: float,
        signals: list[dict[str, Any]],
        market_regime: str | None = None,
        decision_rationale: str | None = None,
    ) -> StrategyTimingHistory:
        """记录一次 strategy-timing 信号。

        Args:
            symbol: 标的代码，如 "600519.SH"
            as_of: 择时日期（交易日）
            aggregated_signal: 综合聚合信号 "buy" / "hold" / "sell"
            confidence: 综合置信度 0.0-1.0
            signals: 各策略信号列表 [{strategy_name, strategy_category, rule_id,
                                    signal, score, confidence, reason, detail,
                                    factor_ids_consumed}]
            market_regime: 市场状态推断 "trending_up/down/sideways/volatile"
            decision_rationale: AI 综合聚合决策理由

        Returns:
            创建的 StrategyTimingHistory 实例（含主键）
        """
        if aggregated_signal not in ("buy", "hold", "sell"):
            raise BusinessException(
                message=f"非法 aggregated_signal: {aggregated_signal}，必须为 buy/hold/sell"
            )
        if not 0.0 <= confidence <= 1.0:
            raise BusinessException(
                message=f"非法 confidence: {confidence}，必须在 [0.0, 1.0] 区间"
            )

        instance = await StrategyTimingHistory.create(
            symbol=symbol,
            as_of=as_of,
            market_regime=market_regime,
            signals=signals,
            aggregated_signal=aggregated_signal,
            confidence=confidence,
            decision_rationale=decision_rationale,
        )
        logger.info(
            "择时信号已记录: symbol=%s, as_of=%s, aggregated_signal=%s, confidence=%.3f, "
            "strategies=%d",
            symbol, as_of, aggregated_signal, confidence, len(signals),
        )
        return instance

    # ────────────────────────── 走势比对 ──────────────────────────────

    async def compare_outcome(
        self,
        history_id: int,
        *,
        window_days: int = _DEFAULT_COMPARE_WINDOW_DAYS,
    ) -> StrategyTimingHistory | None:
        """比对单条择时记录的后续走势。

        Args:
            history_id: StrategyTimingHistory 主键
            window_days: 走势比对窗口（默认 5 个交易日）

        Returns:
            更新后的 StrategyTimingHistory 实例；若已比对或不存在返回 None
        """
        record = await StrategyTimingHistory.get(history_id)
        if record is None:
            logger.warning("走势比对失败：记录不存在 history_id=%s", history_id)
            return None
        if record.verdict is not None:
            logger.info(
                "走势比对跳过：已比对 history_id=%s, verdict=%s",
                history_id, record.verdict,
            )
            return record

        actual_return = await self._compute_actual_return(
            record.symbol, record.as_of, window_days,
        )
        if actual_return is None:
            logger.info(
                "走势比对跳过：窗口内数据不足 history_id=%s, symbol=%s, as_of=%s, window=%d",
                history_id, record.symbol, record.as_of, window_days,
            )
            return None

        verdict = self._determine_verdict(record.aggregated_signal, actual_return)
        await self._apply_verdict(
            history_id,
            actual_return=actual_return,
            verdict=verdict,
            compared_at=date.today(),
            window_days=window_days,
        )
        await record.refresh()
        logger.info(
            "走势比对完成: history_id=%s, symbol=%s, as_of=%s, return=%.4f%%, verdict=%s",
            history_id, record.symbol, record.as_of, actual_return, verdict,
        )
        return record

    async def compare_pending_outcomes(
        self,
        *,
        window_days: int = _DEFAULT_COMPARE_WINDOW_DAYS,
        batch_size: int = _COMPARE_BATCH_SIZE,
    ) -> int:
        """批量比对所有未比对的择时历史记录（供定时任务调用）。

        仅处理 as_of 已过 window_days 的记录，避免过早比对未完成窗口。

        Args:
            window_days: 走势比对窗口（默认 5 个交易日）
            batch_size: 单批处理数量上限

        Returns:
            成功比对的记录数
        """
        cutoff_date = date.today() - timedelta(days=window_days + 2)
        pending = await StrategyTimingHistory.filter(
            verdict__isnull=True,
            as_of__lte=cutoff_date,
            limit=batch_size,
            order_by=StrategyTimingHistory.as_of.asc(),
        )
        if not pending:
            logger.info("无待比对择时历史记录")
            return 0

        success_count = 0
        for record in pending:
            result = await self.compare_outcome(record.id, window_days=window_days)
            if result is not None and result.verdict is not None:
                success_count += 1
        logger.info(
            "批量走势比对完成: 待处理 %d, 成功 %d, window_days=%d",
            len(pending), success_count, window_days,
        )
        return success_count

    # ────────────────────────── 胜率计算 ──────────────────────────────

    async def get_strategy_stats(
        self,
        rule_id: str,
        *,
        min_samples: int = _MIN_SAMPLES_FOR_WEIGHT_FEEDBACK,
    ) -> dict[str, Any]:
        """按 rule_id 聚合计算策略胜率。

        Args:
            rule_id: SPI 插件标识，如 "ts_ma_cross"
            min_samples: 启用反哺的最小样本数（默认 30）

        Returns:
            {
                "rule_id": str,
                "total_samples": int,
                "win_count": int,
                "loss_count": int,
                "neutral_count": int,
                "win_rate": float,  # 0.0-1.0
                "is_feedback_enabled": bool,  # 样本数 >= min_samples
                "avg_return": float,  # 平均收益率%
            }
        """
        records = await StrategyTimingHistory.filter(
            verdict__isnull=False,
            limit=None,
        )
        stats = self._aggregate_strategy_stats(rule_id, records, min_samples)
        logger.info(
            "策略胜率统计: rule_id=%s, samples=%d, win_rate=%.3f, feedback_enabled=%s",
            rule_id, stats["total_samples"], stats["win_rate"], stats["is_feedback_enabled"],
        )
        return stats

    async def get_all_strategy_stats(
        self,
        *,
        min_samples: int = _MIN_SAMPLES_FOR_WEIGHT_FEEDBACK,
    ) -> list[dict[str, Any]]:
        """获取所有策略的胜率统计（用于反哺聚合权重）。

        一次性加载所有已比对记录，按 rule_id 分组统计，避免重复查询。

        Returns:
            [{rule_id, total_samples, win_rate, ...}] 按 win_rate 降序排序
        """
        records = await StrategyTimingHistory.filter(
            verdict__isnull=False,
            limit=None,
        )
        rule_ids = self._collect_rule_ids(records)
        stats_list = [
            self._aggregate_strategy_stats(rule_id, records, min_samples)
            for rule_id in rule_ids
        ]
        stats_list.sort(key=lambda x: x["win_rate"], reverse=True)
        logger.info(
            "全量策略胜率统计: 共 %d 个策略, 已比对记录 %d 条",
            len(stats_list), len(records),
        )
        return stats_list

    # ────────────────────────── 查询接口 ──────────────────────────────

    async def list_history(
        self,
        *,
        symbol: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[StrategyTimingHistory]:
        """查询择时历史记录列表。"""
        filters: dict[str, Any] = {}
        if symbol is not None:
            filters["symbol"] = symbol
        return await StrategyTimingHistory.filter(
            skip=skip,
            limit=limit,
            order_by=StrategyTimingHistory.as_of.desc(),
            **filters,
        )

    async def get_history(self, history_id: int) -> StrategyTimingHistory | None:
        """按主键查询择时历史详情。"""
        return await StrategyTimingHistory.get(history_id)

    # ────────────────────────── 私有辅助 ──────────────────────────────

    async def _compute_actual_return(
        self,
        symbol: str,
        as_of: date,
        window_days: int,
    ) -> float | None:
        """计算 as_of 后 window_days 个交易日的实际收益率（%）。

        收益率 = (后N日收盘价 - as_of收盘价) / as_of收盘价 * 100

        Returns:
            收益率（%），数据不足返回 None
        """
        # as_of 当日收盘价
        start_bar = await CandlestickDaily.get_one_or_none(
            symbol=symbol, trade_date=as_of,
        )
        if start_bar is None:
            return None

        # as_of 后 window_days 个交易日的收盘价（按 trade_date 升序）
        bars = await CandlestickDaily.filter(
            symbol=symbol,
            trade_date__gt=as_of,
            limit=window_days,
            order_by=CandlestickDaily.trade_date.asc(),
        )
        if len(bars) < window_days:
            return None

        end_close = float(bars[-1].close)
        start_close = float(start_bar.close)
        if start_close == 0.0:
            return None
        return round((end_close - start_close) / start_close * 100.0, 4)

    @staticmethod
    def _determine_verdict(aggregated_signal: str, actual_return: float) -> str:
        """根据 aggregated_signal 与 actual_return 判定胜负。

        Returns:
            "win" / "loss" / "neutral"
        """
        if aggregated_signal == "buy":
            if actual_return > _BUY_WIN_THRESHOLD:
                return "win"
            if actual_return < -_BUY_WIN_THRESHOLD:
                return "loss"
            return "neutral"
        if aggregated_signal == "sell":
            if actual_return < _SELL_WIN_THRESHOLD:
                return "win"
            if actual_return > -_SELL_WIN_THRESHOLD:
                return "loss"
            return "neutral"
        # hold
        if abs(actual_return) < _HOLD_WIN_ABS_THRESHOLD:
            return "win"
        return "loss"

    @staticmethod
    @transactional(bind_key="trading")
    async def _apply_verdict(
        history_id: int,
        *,
        actual_return: float,
        verdict: str,
        compared_at: date,
        window_days: int,
    ) -> None:
        """回填走势比对结果（事务化）。"""
        await StrategyTimingHistory.update_by(
            {
                "actual_return": actual_return,
                "verdict": verdict,
                "compared_at": compared_at,
                "compare_window_days": window_days,
            },
            id=history_id,
        )

    @staticmethod
    def _aggregate_strategy_stats(
        rule_id: str,
        records: list[StrategyTimingHistory],
        min_samples: int,
    ) -> dict[str, Any]:
        """按 rule_id 从已加载的记录中聚合胜率。

        从 signals JSONB 中过滤该 rule_id 的 signal，与 record.verdict 比对。
        单条记录中该 rule_id 的 signal 与 verdict 同向 → win，反向 → loss。
        """
        win_count = 0
        loss_count = 0
        neutral_count = 0
        returns: list[float] = []

        for record in records:
            signal_item = next(
                (s for s in record.signals if s.get("rule_id") == rule_id),
                None,
            )
            if signal_item is None:
                continue
            strategy_signal = signal_item.get("signal", "neutral")
            if strategy_signal == "neutral":
                continue  # 中性信号不计入胜率统计

            # 与 aggregated_signal 对齐的 verdict 已是按聚合信号判定
            # 此处按策略自身 signal 重新判定
            if record.actual_return is None:
                continue
            actual_return = float(record.actual_return)
            returns.append(actual_return)
            strategy_verdict = StrategyTimingService._determine_verdict(
                strategy_signal, actual_return,
            )
            if strategy_verdict == "win":
                win_count += 1
            elif strategy_verdict == "loss":
                loss_count += 1
            else:
                neutral_count += 1

        total = win_count + loss_count + neutral_count
        win_rate = win_count / total if total > 0 else 0.0
        avg_return = sum(returns) / len(returns) if returns else 0.0
        return {
            "rule_id": rule_id,
            "total_samples": total,
            "win_count": win_count,
            "loss_count": loss_count,
            "neutral_count": neutral_count,
            "win_rate": round(win_rate, 4),
            "is_feedback_enabled": total >= min_samples,
            "avg_return": round(avg_return, 4),
        }

    @staticmethod
    def _collect_rule_ids(records: list[StrategyTimingHistory]) -> list[str]:
        """从所有记录的 signals JSONB 中收集全部 rule_id（去重排序）。"""
        rule_ids: set[str] = set()
        for record in records:
            for signal_item in record.signals:
                rule_id = signal_item.get("rule_id")
                if rule_id:
                    rule_ids.add(rule_id)
        return sorted(rule_ids)


# 模块级单例 — 与 EventDetector 单例风格对齐
strategy_timing_service = StrategyTimingService()
