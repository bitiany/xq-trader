"""宏观恐慌指数服务 — A 股市场情绪 + 美股海外指标 + 策略模式综合评分。

架构文档 §11.3.2 第二层：宏观恐慌指数监控。

数据源：
  A 股（akshare，主要数据源）：
    - 涨跌停家数（stock_zt_pool_em / stock_zt_pool_dtgc_em）
    - 市场活跃度（stock_market_activity_legu）
    - 微博财经舆情（stock_js_weibo_report）
  美股（Yahoo Finance，海外辅助维度，大陆环境可能不可达）：
    - ^VIX  美股恐慌指数
    - ^OVX  原油波动率指数
    - ^GVZ  黄金波动率指数
    - ^TNX  美 10 年期国债收益率（%）

采集失败处理：单个指标失败返回 None，不降级、不 fallback；
全部失败时评分保持基准分 50（中性）。

评分逻辑（策略模式，详见 fear_greed_score_strategy.py）：
  - 基准分 50
  - VIX 维度：±30 / ±15 / 0
  - US10Y 维度：±10
  - A 股涨跌停家数比：±20 / ±10 / 0
  - A 股市场活跃度：±15 / ±8 / 0
  - 微博舆情热度：±10 / ±5 / 0
  - 综合 0-100，>75 极度贪婪 / 55-75 贪婪 / 45-55 中性 / 25-45 恐慌 / <25 极度恐慌
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx

from framework.commons.logger import get_logger
from xqtrader.domain.event.models import MarketFearIndex
from xqtrader.domain.event.services.cn_market_sentiment_service import (
    cn_market_sentiment_service,
)
from xqtrader.domain.event.services.fear_greed_score_strategy import (
    classify_score,
    compute_fear_greed_score,
)

logger = get_logger("EVENT.FEAR_INDEX")

# Yahoo Finance chart API
_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
_YAHOO_TIMEOUT = 15.0
_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Yahoo Finance ticker 映射
_TICKERS = {
    "vix": "^VIX",
    "ovx": "^OVX",
    "gvz": "^GVZ",
    "us10y": "^TNX",  # ^TNX 返回的是收益率数值（如 4.337 表示 4.337%）
}


class MarketFearIndexService:
    """宏观恐慌指数服务 — A 股 + 美股双维度采集 + 策略模式评分。"""

    async def get_fear_index(
        self,
        indicators: list[str] | None = None,
        as_of: date | None = None,
    ) -> MarketFearIndex:
        """采集宏观恐慌指数并计算综合评分。

        Args:
            indicators: 指定采集的指标列表（None=全部，
                如 ["vix", "us10y", "cn_advance_decline"]）
            as_of: 基准日期（None 表示今天）

        Returns:
            MarketFearIndex 快照
        """
        ref_date = as_of or date.today()

        # 并发采集：A 股指标 + Yahoo 美股指标
        cn_task = cn_market_sentiment_service.fetch_all(as_of=ref_date)
        yahoo_task = self._fetch_all_yahoo(indicators)
        cn_result, yahoo_values = await asyncio.gather(cn_task, yahoo_task)

        vix = yahoo_values.get("vix")
        ovx = yahoo_values.get("ovx")
        gvz = yahoo_values.get("gvz")
        us10y = yahoo_values.get("us10y")

        cn_limit_up = cn_result.get("limit_up")
        cn_limit_down = cn_result.get("limit_down")
        cn_advance_decline_ratio = cn_result.get("advance_decline_ratio")
        cn_market_activity = cn_result.get("market_activity")
        cn_weibo_hot = cn_result.get("weibo_hot")

        # 构建评分快照（策略模式）
        score_snapshot: dict[str, Any] = {
            "vix": vix,
            "us10y": us10y,
            "advance_decline_ratio": cn_advance_decline_ratio,
            "market_activity": cn_market_activity,
            "weibo_hot": cn_weibo_hot,
        }
        score = compute_fear_greed_score(score_snapshot)
        score_level = classify_score(score)

        vix_level = self._classify_vix(vix)
        us10y_level = self._classify_us10y(us10y)
        risk_transmission = self._analyze_risk_transmission(
            vix, ovx, cn_advance_decline_ratio,
        )
        advice = self._build_advice(
            score, vix, ovx, cn_advance_decline_ratio, cn_market_activity,
        )

        logger.info(
            "宏观恐慌指数采集完成: as_of=%s vix=%s ovx=%s gvz=%s us10y=%s "
            "cn_limit_up=%s cn_limit_down=%s cn_ad_ratio=%s cn_activity=%s "
            "cn_weibo=%s score=%d level=%s",
            ref_date, vix, ovx, gvz, us10y,
            cn_limit_up, cn_limit_down, cn_advance_decline_ratio,
            cn_market_activity, cn_weibo_hot,
            score, score_level,
        )

        return MarketFearIndex(
            as_of=ref_date,
            vix=vix,
            vix_level=vix_level,
            ovx=ovx,
            gvz=gvz,
            us10y=us10y,
            us10y_level=us10y_level,
            cn_limit_up=cn_limit_up,
            cn_limit_down=cn_limit_down,
            cn_advance_decline_ratio=cn_advance_decline_ratio,
            cn_market_activity=cn_market_activity,
            cn_weibo_hot=cn_weibo_hot,
            fear_greed_score=score,
            fear_greed_level=score_level,
            risk_transmission=risk_transmission,
            advice=advice,
        )

    async def _fetch_all_yahoo(
        self,
        indicators: list[str] | None,
    ) -> dict[str, float | None]:
        """并发采集所有 Yahoo Finance 指标。"""
        target = indicators if indicators else list(_TICKERS.keys())
        # 仅采集 Yahoo 支持的指标（cn_ 前缀的跳过）
        yahoo_keys = [k for k in target if k in _TICKERS]
        if not yahoo_keys:
            return {}
        tasks = [self._fetch_yahoo(_TICKERS[k], k) for k in yahoo_keys]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return dict(zip(yahoo_keys, results, strict=True))

    async def _fetch_yahoo(self, ticker: str, key: str) -> float | None:
        """从 Yahoo Finance 采集单个指标值。

        采集失败返回 None 并记录 WARNING（不降级、不重试）。
        """
        url = f"{_YAHOO_CHART_URL}/{ticker}"
        params = {"range": "1d", "interval": "1d"}
        try:
            async with httpx.AsyncClient(timeout=_YAHOO_TIMEOUT) as client:
                response = await client.get(url, headers=_YAHOO_HEADERS, params=params)
                response.raise_for_status()
                body = response.json()
            result = body.get("chart", {}).get("result")
            if not result or not isinstance(result, list):
                logger.warning("Yahoo Finance %s 响应格式异常: result 为空", ticker)
                return None
            meta = result[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            if price is None:
                logger.warning("Yahoo Finance %s regularMarketPrice 为空", ticker)
                return None
            return float(price)
        except httpx.HTTPError as exc:
            logger.warning(
                "Yahoo Finance %s 采集失败 (HTTP): %s ticker=%s",
                key, exc, ticker,
            )
            return None
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Yahoo Finance %s 响应解析失败: %s ticker=%s",
                key, exc, ticker,
            )
            return None

    @staticmethod
    def _classify_vix(vix: float | None) -> str:
        """VIX 水平判定。"""
        if vix is None:
            return "数据缺失"
        if vix < 15:
            return "极度平静"
        if vix < 20:
            return "平静"
        if vix < 25:
            return "焦虑"
        if vix < 35:
            return "恐慌"
        return "极度恐慌"

    @staticmethod
    def _classify_us10y(us10y: float | None) -> str:
        """US10Y 水平判定。"""
        if us10y is None:
            return "数据缺失"
        if us10y < 3.8:
            return "利成长股"
        if us10y < 4.3:
            return "分水岭"
        if us10y <= 4.4:
            return "分水岭"
        return "利价值股"

    @staticmethod
    def _analyze_risk_transmission(
        vix: float | None,
        ovx: float | None,
        cn_ad_ratio: float | None,
    ) -> str:
        """风险传导分析 — 综合美股与 A 股维度。

        架构文档 §11.3.2 风险传导逻辑扩展：
          - OVX 与 VIX 同步共振向上 → 地缘风险已触发流动性危机
          - A 股跌停潮（ad_ratio < 0.2）→ A 股市场恐慌情绪蔓延
          - OVX 飙升但 VIX 滞后 → 风险仍集中在能源端
        """
        parts: list[str] = []
        if vix is not None and ovx is not None:
            if vix > 30 and ovx > 40:
                parts.append("OVX 与 VIX 同步共振向上 → 地缘风险已触发流动性危机，需立即风控")
            elif ovx > 40 and vix < 25:
                parts.append("OVX 飙升但 VIX 滞后 → 风险仍集中在能源端")
            elif vix > 25 and ovx < 30:
                parts.append("VIX 升高但 OVX 平稳 → 风险主要来自美股本身")
            else:
                parts.append("OVX 与 VIX 均平稳，无明显风险传导")
        else:
            parts.append("美股数据不足，无法分析 OVX/VIX 风险传导")

        if cn_ad_ratio is not None:
            if cn_ad_ratio < 0.2:
                parts.append("A 股跌停潮（涨跌停比 < 0.2）→ 市场恐慌情绪蔓延")
            elif cn_ad_ratio > 5:
                parts.append("A 股涨停潮（涨跌停比 > 5）→ 追涨情绪强烈，警惕回调")
        return "；".join(parts)

    @staticmethod
    def _build_advice(
        score: int,
        vix: float | None,
        ovx: float | None,
        cn_ad_ratio: float | None,
        cn_market_activity: float | None,
    ) -> str:
        """生成操作建议（按优先级返回）。"""
        if vix is not None and vix > 35:
            return "极度恐慌，建议降低仓位，关注超跌反弹机会"
        if cn_ad_ratio is not None and cn_ad_ratio < 0.2:
            return "A 股跌停潮，建议降低仓位，规避恐慌蔓延"
        if score < 25:
            return "极度恐慌，建议降低仓位，关注超跌反弹机会"
        if score > 75:
            return "极度贪婪，警惕回调风险，谨慎追高"
        if ovx is not None and ovx > 40:
            return "地缘风险升温，关注能源板块与避险资产"
        if cn_market_activity is not None and cn_market_activity < 20:
            return "市场活跃度极低，情绪冷清，谨慎操作"
        if 45 <= score <= 55:
            return "市场情绪中性，维持均衡配置"
        if score < 45:
            return "市场情绪偏恐慌，谨慎操作"
        return "市场情绪偏贪婪，可适度参与"
