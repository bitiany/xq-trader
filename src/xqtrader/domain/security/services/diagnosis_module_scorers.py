"""新浪式六模块诊股评分 — 技术面/资金面/基本面/消息面/行业面/机构面。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from xqtrader.domain.market.models.financial_indicator import FinancialIndicator
from xqtrader.domain.market.models.fund_flow import FundFlowIndividual
from xqtrader.domain.research.models.research_report import ResearchReport
from xqtrader.domain.research.models.stock_news import StockNews
from xqtrader.domain.research.models.stock_sentiment import StockSentiment
from xqtrader.domain.security.services.stock_technical_service import StockTechnicalService

MODULE_WEIGHTS: dict[str, float] = {
    "technical": 0.20,
    "capital_flow": 0.20,
    "fundamental": 0.20,
    "sentiment": 0.15,
    "industry": 0.15,
    "institutional": 0.10,
}

MODULE_LABELS: dict[str, str] = {
    "technical": "技术面",
    "capital_flow": "资金面",
    "fundamental": "基本面",
    "sentiment": "消息面",
    "industry": "行业面",
    "institutional": "机构面",
}

MODULE_ORDER = (
    "technical",
    "capital_flow",
    "fundamental",
    "sentiment",
    "industry",
    "institutional",
)

# 资金面：主力净流入占比（%）加权系数
_CAPITAL_FLOW_WEIGHT_5D = 0.35
_CAPITAL_FLOW_WEIGHT_10D = 0.15
_CAPITAL_FLOW_WEIGHT_LATEST = 0.15
_CAPITAL_FLOW_AMT_BONUS = 0.5
_CAPITAL_FLOW_TREND_THRESHOLD = 0.5

_RATING_SCORES: dict[str, float] = {
    "买入": 10.0,
    "增持": 8.0,
    "推荐": 8.0,
    "中性": 5.0,
    "减持": 3.0,
    "卖出": 1.0,
}


class DiagnosisScoreMath:
    """诊股评分数值工具。"""

    @staticmethod
    def clamp(value: float) -> float:
        return round(max(0.0, min(10.0, value)), 1)

    @staticmethod
    def from_percentile(percentile: float | None) -> float | None:
        if percentile is None:
            return None
        return DiagnosisScoreMath.clamp(percentile / 10.0)

    @staticmethod
    def avg_last(values: list[float], n: int) -> float:
        window = values[-n:] if len(values) >= n else values
        if not window:
            return 0.0
        return sum(window) / len(window)

    @staticmethod
    def sum_last(values: list[float], n: int) -> float:
        window = values[-n:] if len(values) >= n else values
        return sum(window)


class DiagnosisModuleScorers:
    """六模块独立评分引擎。"""

    def __init__(
        self,
        technical: StockTechnicalService,
        *,
        daily_pct_cache: dict[str, float | None],
        financial_pct_cache: dict[str, float | None],
        industry_pe_cache: tuple[int | None, int | None] | None,
        valuation_panel: dict[str, Any] | None = None,
        institutional_hold_pct: float | None = None,
    ) -> None:
        self._technical = technical
        self._daily_pct = daily_pct_cache
        self._financial_pct = financial_pct_cache
        self._industry_pe = industry_pe_cache
        self._valuation_panel = valuation_panel or {}
        self._institutional_hold_pct = institutional_hold_pct

    async def score_all(self, symbol: str) -> list[dict[str, Any]]:
        specs = [
            ("technical", await self.score_technical(symbol)),
            ("capital_flow", await self.score_capital_flow(symbol)),
            ("fundamental", await self.score_fundamental(symbol)),
            ("sentiment", await self.score_sentiment(symbol)),
            ("industry", await self.score_industry(symbol)),
            ("institutional", await self.score_institutional(symbol)),
        ]
        return [
            {
                "key": key,
                "label": MODULE_LABELS[key],
                "score": score,
                "prev_score": None,
                "weight": MODULE_WEIGHTS[key],
                "detail": detail,
            }
            for key, (score, detail) in specs
        ]

    async def score_technical(self, symbol: str) -> tuple[float | None, dict[str, Any]]:
        technical = await self._technical.get_technical(symbol)
        if not technical.get("available"):
            factor_pct = self._daily_pct.get("composite_momentum")
            factor_score = DiagnosisScoreMath.from_percentile(factor_pct)
            if factor_score is None:
                return None, {"reason": "无技术数据"}
            return factor_score, {"factor_percentile": factor_pct}

        trend = technical.get("trend") or {}
        momentum = technical.get("momentum") or {}
        volatility = technical.get("volatility") or {}
        tech_score = self._technical_momentum_score(trend, momentum)
        factor_pct = self._daily_pct.get("composite_momentum")
        factor_score = DiagnosisScoreMath.from_percentile(factor_pct)
        if factor_score is not None:
            tech_score = DiagnosisScoreMath.clamp(factor_score * 0.4 + tech_score * 0.6)

        direction = trend.get("direction") or "震荡"
        short_label = self._horizon_label(direction, momentum, horizon="short")
        mid_label = self._horizon_label(direction, momentum, horizon="mid")
        long_label = direction

        signals: list[dict[str, str]] = []
        macd = momentum.get("macd") or {}
        kdj = momentum.get("kdj") or {}
        rsi = momentum.get("rsi") or {}
        if macd.get("signal"):
            signals.append({"name": "MACD", "value": str(macd["signal"])})
        if kdj.get("signal"):
            signals.append({"name": "KDJ", "value": str(kdj["signal"])})
        if rsi.get("signal"):
            signals.append({"name": "RSI", "value": str(rsi["signal"])})
        if trend.get("adx_label"):
            signals.append({"name": "ADX", "value": str(trend["adx_label"])})

        support = volatility.get("stop_price_long")
        resistance = volatility.get("stop_price_short")
        return tech_score, {
            "short_label": short_label,
            "mid_label": mid_label,
            "long_label": long_label,
            "direction": direction,
            "signals": signals,
            "support": support,
            "resistance": resistance,
            "adx": trend.get("adx"),
        }

    @staticmethod
    def _horizon_label(direction: str, momentum: dict[str, Any], *, horizon: str) -> str:
        macd_sig = (momentum.get("macd") or {}).get("signal", "")
        if horizon == "short":
            if macd_sig in {"金叉", "多头"}:
                return "偏多"
            if macd_sig in {"死叉", "空头"}:
                return "偏空"
            return "中性"
        if direction in {"多头", "上升趋势"}:
            return "偏多"
        if direction in {"空头", "下降趋势"}:
            return "偏空"
        return "中性"

    @staticmethod
    def _technical_momentum_score(trend: dict[str, Any], momentum: dict[str, Any]) -> float:
        score = 5.0
        direction = trend.get("direction")
        if direction in {"多头", "上升趋势"}:
            score += 1.5
        elif direction in {"空头", "下降趋势"}:
            score -= 1.5
        macd_sig = (momentum.get("macd") or {}).get("signal")
        if macd_sig == "金叉":
            score += 1.0
        elif macd_sig == "死叉":
            score -= 1.0
        kdj_sig = (momentum.get("kdj") or {}).get("signal")
        if kdj_sig == "超买":
            score -= 0.5
        elif kdj_sig == "超卖":
            score += 0.5
        rsi_sig = (momentum.get("rsi") or {}).get("signal")
        if rsi_sig == "超买":
            score -= 0.5
        elif rsi_sig == "超卖":
            score += 0.5
        return DiagnosisScoreMath.clamp(score)

    async def score_capital_flow(self, symbol: str) -> tuple[float | None, dict[str, Any]]:
        rows = await FundFlowIndividual.filter(
            symbol=symbol,
            order_by=FundFlowIndividual.trade_date.desc(),
            limit=25,
        )
        if not rows:
            return None, {"reason": "无资金流数据"}

        ordered = list(reversed(rows))
        pcts = [float(r.main_net_pct) for r in ordered if r.main_net_pct is not None]
        amts = [float(r.main_net_amt) for r in ordered if r.main_net_amt is not None]
        if not pcts:
            return None, {"reason": "主力占比为空"}

        net_5d = round(DiagnosisScoreMath.avg_last(pcts, 5), 2)
        net_10d = round(DiagnosisScoreMath.avg_last(pcts, 10), 2)
        net_20d = round(DiagnosisScoreMath.avg_last(pcts, 20), 2)
        amt_5d = round(DiagnosisScoreMath.sum_last(amts, 5), 2) if amts else None
        amt_10d = round(DiagnosisScoreMath.sum_last(amts, 10), 2) if amts else None
        latest = pcts[-1]

        score = (
            5.0
            + net_5d * _CAPITAL_FLOW_WEIGHT_5D
            + net_10d * _CAPITAL_FLOW_WEIGHT_10D
            + latest * _CAPITAL_FLOW_WEIGHT_LATEST
        )
        if amt_5d is not None:
            if amt_5d > 0:
                score += _CAPITAL_FLOW_AMT_BONUS
            elif amt_5d < 0:
                score -= _CAPITAL_FLOW_AMT_BONUS
        trend = (
            "净流入"
            if net_5d > _CAPITAL_FLOW_TREND_THRESHOLD
            else "净流出"
            if net_5d < -_CAPITAL_FLOW_TREND_THRESHOLD
            else "平衡"
        )
        flow_series = [
            {
                "trade_date": (
                    r.trade_date.isoformat()
                    if hasattr(r.trade_date, "isoformat")
                    else str(r.trade_date)
                ),
                "main_net_pct": round(float(r.main_net_pct), 2) if r.main_net_pct is not None else None,
                "main_net_amt": round(float(r.main_net_amt), 2) if r.main_net_amt is not None else None,
            }
            for r in ordered[-20:]
        ]
        return DiagnosisScoreMath.clamp(score), {
            "net_5d": net_5d,
            "net_10d": net_10d,
            "net_20d": net_20d,
            "amt_5d": amt_5d,
            "amt_10d": amt_10d,
            "latest_main_net_pct": round(latest, 2),
            "flow_trend": trend,
            "flow_series": flow_series,
        }

    @staticmethod
    def _growth_ring_from_history(rows: list[FinancialIndicator]) -> float | None:
        if not rows:
            return None
        current = rows[0]
        if current.roe is None or current.end_date is None:
            return None

        compare_row: FinancialIndicator | None = None
        target_month = current.end_date.month
        for hist in rows[1:]:
            if hist.end_date and hist.end_date.month == target_month:
                compare_row = hist
                break
        if compare_row is None and len(rows) >= 2:
            compare_row = rows[1]

        if compare_row is None or compare_row.roe is None or compare_row.roe == 0:
            return None
        delta = (float(current.roe) - float(compare_row.roe)) / abs(float(compare_row.roe))
        return DiagnosisScoreMath.clamp(5.0 + delta * 12.0)

    async def score_fundamental(self, symbol: str) -> tuple[float | None, dict[str, Any]]:
        rows = await FinancialIndicator.filter(
            symbol=symbol,
            update_flag="1",
            order_by=FinancialIndicator.end_date.desc(),
            limit=4,
        )
        growth_pct = self._financial_pct.get("composite_growth")
        quality_pct = self._financial_pct.get("composite_quality")

        rings: dict[str, float | None] = {
            "profit": None,
            "operation": None,
            "solvency": None,
            "growth": DiagnosisScoreMath.from_percentile(growth_pct),
            "cashflow": None,
        }
        if rings["growth"] is None and rows:
            rings["growth"] = self._growth_ring_from_history(rows)

        if rows:
            row = rows[0]
            if row.roe is not None:
                rings["profit"] = DiagnosisScoreMath.clamp(min(float(row.roe), 30) / 30 * 10)
            if row.roa is not None:
                rings["operation"] = DiagnosisScoreMath.clamp(min(abs(float(row.roa)), 15) / 15 * 10)
            if row.debt_to_assets is not None:
                rings["solvency"] = DiagnosisScoreMath.clamp(
                    (1 - min(float(row.debt_to_assets), 100) / 100) * 10,
                )
            if row.ocfps is not None:
                rings["cashflow"] = DiagnosisScoreMath.clamp(5 + min(max(float(row.ocfps), -2), 2) * 2)

        ring_values = [v for v in rings.values() if v is not None]
        factor_score = DiagnosisScoreMath.from_percentile(quality_pct)
        if not ring_values and factor_score is None:
            return None, {"reason": "无季频基本面数据", "rings": rings}

        if ring_values and factor_score is not None:
            score = DiagnosisScoreMath.clamp(
                sum(ring_values) / len(ring_values) * 0.6 + factor_score * 0.4,
            )
        elif ring_values:
            score = DiagnosisScoreMath.clamp(sum(ring_values) / len(ring_values))
        elif factor_score is None:
            return None, {"reason": "无季频基本面数据", "rings": rings}
        else:
            score = factor_score

        highlights: dict[str, float | str | None] = {}
        period_trend: list[dict[str, Any]] = []
        if rows:
            row = rows[0]
            highlights = {
                "roe": row.roe,
                "roa": row.roa,
                "grossprofit_margin": row.grossprofit_margin,
                "debt_to_assets": row.debt_to_assets,
                "current_ratio": row.current_ratio,
                "end_date": row.end_date.isoformat() if row.end_date else None,
            }
            for hist in rows:
                period_trend.append({
                    "end_date": hist.end_date.isoformat() if hist.end_date else None,
                    "roe": hist.roe,
                    "roa": hist.roa,
                    "debt_to_assets": hist.debt_to_assets,
                    "ocfps": hist.ocfps,
                })
        return score, {"rings": rings, "highlights": highlights, "period_trend": period_trend}

    async def score_sentiment(self, symbol: str) -> tuple[float | None, dict[str, Any]]:
        cutoff = datetime.now() - timedelta(days=30)
        news_rows = await StockNews.filter(
            symbol=symbol,
            news_type="news",
            publish_time__gte=cutoff,
            limit=0,
        )
        ann_rows = await StockNews.filter(
            symbol=symbol,
            news_type="announcement",
            publish_time__gte=cutoff,
            limit=0,
        )
        news_count = len(news_rows)
        announcement_count = len(ann_rows)

        sentiment_rows = await StockSentiment.filter(
            symbol=symbol,
            order_by=StockSentiment.snapshot_date.desc(),
            limit=1,
        )
        sentiment_score: float | None = None
        if sentiment_rows and sentiment_rows[0].sentiment_score is not None:
            sentiment_score = float(sentiment_rows[0].sentiment_score)

        score = 5.0
        if news_count >= 10:
            score += 1.0
        elif news_count >= 5:
            score += 0.5
        elif news_count == 0:
            score -= 0.5
        if announcement_count >= 3:
            score -= 0.3
        if sentiment_score is not None:
            score += sentiment_score * 2.0

        recent_news = [
            {
                "title": row.title,
                "published_at": row.publish_time.isoformat() if row.publish_time else None,
            }
            for row in sorted(
                news_rows,
                key=lambda r: r.publish_time or datetime.min,
                reverse=True,
            )[:5]
        ]
        return DiagnosisScoreMath.clamp(score), {
            "news_count": news_count,
            "announcement_count": announcement_count,
            "sentiment_score": sentiment_score,
            "recent_news": recent_news,
        }

    async def score_industry(self, symbol: str) -> tuple[float | None, dict[str, Any]]:
        val = self._valuation_panel
        if not val.get("available"):
            factor_pct = self._daily_pct.get("composite_value")
            factor_score = DiagnosisScoreMath.from_percentile(factor_pct)
            if factor_score is None:
                return None, {"reason": "无估值数据"}
            return factor_score, {"factor_percentile": factor_pct}

        pe_pct = val.get("pe_ttm_percentile")
        pb_pct = val.get("pb_percentile")
        pe_score = DiagnosisScoreMath.clamp((100 - pe_pct) / 10) if pe_pct is not None else None
        pb_score = DiagnosisScoreMath.clamp((100 - pb_pct) / 10) if pb_pct is not None else None

        rank, total = self._industry_pe or (None, None)
        rank_score: float | None = None
        if rank is not None and total and total > 0:
            rank_score = DiagnosisScoreMath.clamp((1 - (rank - 1) / total) * 10)

        parts = [s for s in (pe_score, pb_score, rank_score) if s is not None]
        if not parts:
            return None, {"reason": "估值分位不足"}
        score = DiagnosisScoreMath.clamp(sum(parts) / len(parts))
        return score, {
            "pe_percentile": pe_pct,
            "pb_percentile": pb_pct,
            "industry_rank": rank,
            "industry_total": total,
            "valuation_label": val.get("valuation_label"),
            "pe_ttm": val.get("pe_ttm"),
        }

    async def score_institutional(self, symbol: str) -> tuple[float | None, dict[str, Any]]:
        cutoff = date.today() - timedelta(days=180)
        reports = await ResearchReport.filter(
            symbol=symbol,
            publish_date__gte=cutoff,
            order_by=ResearchReport.publish_date.desc(),
            limit=50,
        )
        rating_dist: dict[str, int] = {}
        rating_weighted = 0.0
        weight_sum = 0.0
        for report in reports:
            rating = (report.rating or "中性").strip()
            rating_dist[rating] = rating_dist.get(rating, 0) + 1
            if not report.publish_date:
                continue
            days_ago = (date.today() - report.publish_date).days
            weight = 0.5 ** (days_ago / 60.0)
            rating_weighted += _RATING_SCORES.get(rating, 5.0) * weight
            weight_sum += weight

        rating_part = rating_weighted / weight_sum if weight_sum > 0 else 5.0
        hold_pct = self._institutional_hold_pct
        hold_score = DiagnosisScoreMath.clamp(hold_pct / 3) if hold_pct is not None else 5.0

        if not reports and hold_pct is None:
            return None, {"report_count": 0, "reason": "无研报与持股数据"}

        if reports:
            score = DiagnosisScoreMath.clamp(rating_part * 0.7 + hold_score * 0.3)
        else:
            score = hold_score

        earnings_preview = [
            {
                "info_code": r.info_code,
                "title": r.title,
                "org_name": r.org_name,
                "rating": r.rating,
                "publish_date": (
                    r.publish_date.isoformat()
                    if isinstance(r.publish_date, date)
                    else r.publish_date
                ),
                "eps_forecast": r.eps_forecast or [],
            }
            for r in reports[:20]
        ]
        return score, {
            "report_count": len(reports),
            "rating_dist": rating_dist,
            "hold_pct": hold_pct,
            "hold_source": "fund" if hold_pct is not None else None,
            "earnings_preview": earnings_preview,
        }
