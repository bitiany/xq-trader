"""个股诊股评分服务 — 新浪式六模块 + 综合得分 + 快照持久化。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from framework.commons.exceptions import DataCollectionError, NotFoundException
from framework.commons.logger import get_logger
from framework.dal.enginee import engines_manager
from framework.dal.transaction.transactional import transactional
from xqtrader.broker.services.akshare_data_collector import AkshareDataCollector
from xqtrader.domain.agent.services.thesis_service import ThesisService
from xqtrader.domain.security.models import Security
from xqtrader.domain.security.services.diagnosis_module_scorers import (
    MODULE_ORDER,
    DiagnosisModuleScorers,
)
from xqtrader.domain.security.services.diagnosis_percentile_cache import DiagnosisPercentileCache
from xqtrader.domain.security.services.diagnosis_summary_service import DiagnosisSummaryService
from xqtrader.domain.security.services.stock_detail_service import SecurityMixin
from xqtrader.domain.security.services.stock_technical_service import StockTechnicalService
from xqtrader.domain.security.stock_diagnosis_snapshot import StockDiagnosisSnapshot

logger = get_logger("STOCK_DIAGNOSIS")

DIAGNOSIS_SCHEMA_VERSION = 2
_CACHE_DETAIL_KEYS = ("thesis", "reports_count", "prev_overall_score", "modules", "schema_version")


class StockDiagnosisService(SecurityMixin):
    """结构化诊股评分引擎。"""

    def __init__(self) -> None:
        self._technical = StockTechnicalService()
        self._thesis = ThesisService()
        self._akshare = AkshareDataCollector()
        self._summary = DiagnosisSummaryService()
        self._percentile_cache = DiagnosisPercentileCache()
        self._industry_pe_cache: tuple[int | None, int | None] | None = None

    async def get_diagnosis(
        self,
        symbol: str,
        *,
        refresh: bool = False,
        ai_summary: bool = False,
    ) -> dict[str, Any]:
        security = await self._ensure_security(symbol)

        if not refresh:
            latest_cached = await StockDiagnosisSnapshot.filter(
                symbol=symbol,
                order_by=StockDiagnosisSnapshot.as_of.desc(),
                limit=1,
            )
            if latest_cached and self._snapshot_cache_ready(latest_cached[0].detail or {}):
                return await self._build_payload_from_snapshot(latest_cached[0], security)

        as_of = await self._resolve_as_of(symbol)

        if not refresh:
            cached_rows = await StockDiagnosisSnapshot.filter(symbol=symbol, as_of=as_of, limit=1)
            if cached_rows and self._snapshot_cache_ready(cached_rows[0].detail or {}):
                return await self._build_payload_from_snapshot(cached_rows[0], security)

        prev_snapshot = await self._load_prev_snapshot(symbol, as_of)

        await self._percentile_cache.warm_all(symbol)
        self._industry_pe_cache = await self._compute_industry_pe_rank(symbol)
        valuation_panel = await self._technical.get_valuation(symbol)
        key_metrics = await self._build_key_metrics(symbol, security, refresh=refresh)

        scorers = DiagnosisModuleScorers(
            self._technical,
            daily_pct_cache=self._percentile_cache.daily,
            financial_pct_cache=self._percentile_cache.financial,
            industry_pe_cache=self._industry_pe_cache,
            valuation_panel=valuation_panel,
            institutional_hold_pct=key_metrics.get("institutional_hold_pct"),
        )
        module_scores = await scorers.score_all(symbol)
        self._attach_prev_module_scores(module_scores, prev_snapshot)
        overall = self._compute_overall(module_scores)
        market_percentile = await self._compute_market_percentile(overall, as_of)
        prev_as_of = prev_snapshot.as_of.isoformat() if prev_snapshot else None
        summary = self._build_rule_summary(
            module_scores,
            overall,
            prev_snapshot,
            name=security.name,
            prev_as_of=prev_as_of,
        )
        thesis = await self._thesis_snapshot(symbol)

        payload = {
            "symbol": symbol,
            "name": security.name,
            "industry": security.industry,
            "intro": security.introduction,
            "as_of": as_of.isoformat(),
            "overall_score": overall,
            "prev_overall_score": prev_snapshot.overall_score if prev_snapshot else None,
            "prev_as_of": prev_as_of,
            "market_percentile": market_percentile,
            "rating_label": self._rating_label(overall),
            "module_scores": module_scores,
            "key_metrics": key_metrics,
            "summary": summary,
            "thesis": thesis,
            "reports_count": await self._count_snapshots(symbol),
            "cached": False,
        }
        if ai_summary and DiagnosisSummaryService.is_enabled():
            payload["summary"] = await self._summary.generate(
                DiagnosisSummaryService.build_context(payload),
            )

        await self._save_snapshot(symbol, as_of, payload)
        return payload

    @staticmethod
    def _snapshot_cache_ready(detail: dict[str, Any]) -> bool:
        if detail.get("schema_version", 0) < DIAGNOSIS_SCHEMA_VERSION:
            return False
        if not all(key in detail for key in _CACHE_DETAIL_KEYS):
            return False
        modules = detail.get("modules")
        if not isinstance(modules, list) or len(modules) != len(MODULE_ORDER):
            return False
        module_map = {
            m["key"]: m
            for m in modules
            if isinstance(m, dict) and m.get("key")
        }
        if set(module_map) != set(MODULE_ORDER):
            return False
        capital_flow = module_map["capital_flow"]
        if capital_flow.get("score") is None:
            return False
        cf_detail = capital_flow.get("detail") or {}
        if not cf_detail.get("flow_series"):
            return False
        fundamental = module_map["fundamental"]
        if fundamental.get("score") is None:
            return False
        rings = (fundamental.get("detail") or {}).get("rings") or {}
        return rings.get("growth") is not None

    async def _build_payload_from_snapshot(
        self,
        row: StockDiagnosisSnapshot,
        security: Security,
    ) -> dict[str, Any]:
        detail = row.detail or {}
        module_scores = list(detail.get("modules") or [])
        prev_overall = detail.get("prev_overall_score")
        prev_as_of = detail.get("prev_as_of")
        if prev_overall is None:
            prev_snapshot = await self._load_prev_snapshot(row.symbol, row.as_of)
            prev_overall = prev_snapshot.overall_score if prev_snapshot else None
            prev_as_of = prev_snapshot.as_of.isoformat() if prev_snapshot else None
            self._attach_prev_module_scores(module_scores, prev_snapshot)

        if "thesis" in detail:
            thesis = detail.get("thesis")
        else:
            thesis = await self._thesis_snapshot(row.symbol)

        if "reports_count" in detail:
            reports_count = detail["reports_count"]
        else:
            reports_count = await self._count_snapshots(row.symbol)

        key_metrics = self._normalize_key_metrics(detail.get("key_metrics") or {})
        overall_score = self._compute_overall(module_scores) or row.overall_score
        market_percentile = detail.get("market_percentile")
        if market_percentile is None and overall_score is not None:
            market_percentile = await self._compute_market_percentile(
                overall_score, row.as_of,
            )

        return {
            "symbol": row.symbol,
            "name": security.name,
            "industry": security.industry,
            "intro": security.introduction,
            "as_of": row.as_of.isoformat(),
            "overall_score": overall_score,
            "prev_overall_score": prev_overall,
            "prev_as_of": prev_as_of,
            "market_percentile": market_percentile,
            "rating_label": self._rating_label(overall_score),
            "module_scores": module_scores,
            "key_metrics": key_metrics,
            "summary": row.summary or {"bullets": [], "generated_by": "rule", "generated_at": ""},
            "thesis": thesis,
            "reports_count": reports_count,
            "cached": True,
        }

    async def get_history(self, symbol: str, days: int = 90) -> dict[str, Any]:
        await self._ensure_security(symbol)
        cutoff = date.today() - timedelta(days=days)
        rows = await StockDiagnosisSnapshot.filter(
            symbol=symbol,
            as_of__gte=cutoff,
            order_by=StockDiagnosisSnapshot.as_of.asc(),
            limit=0,
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            detail = row.detail or {}
            modules_from_detail = detail.get("modules") or []
            modules = {
                m["key"]: m.get("score")
                for m in modules_from_detail
                if isinstance(m, dict) and m.get("key")
            }
            items.append({
                "as_of": row.as_of.isoformat(),
                "overall_score": row.overall_score,
                "modules": modules,
            })
        return {"symbol": symbol, "items": items}

    async def _resolve_as_of(self, symbol: str) -> date:
        session_maker = engines_manager.get_session_maker("stock")
        async with session_maker() as session:
            result = await session.execute(
                text(
                    """
                    SELECT trade_date
                    FROM stock.sdc_daily_indicator
                    WHERE symbol = :symbol
                    ORDER BY trade_date DESC
                    LIMIT 1
                    """,
                ),
                {"symbol": symbol},
            )
            row = result.first()
            if row is not None:
                td = row.trade_date
                return td if isinstance(td, date) else date.fromisoformat(str(td))
        return date.today()


    async def _industry_pe_rank(self, symbol: str) -> tuple[int | None, int | None]:
        if self._industry_pe_cache is not None:
            return self._industry_pe_cache
        return await self._compute_industry_pe_rank(symbol)

    async def _compute_industry_pe_rank(self, symbol: str) -> tuple[int | None, int | None]:
        security = await Security.get_one_or_none(symbol=symbol)
        if security is None or not security.industry:
            return None, None

        session_maker = engines_manager.get_session_maker("stock")
        async with session_maker() as session:
            result = await session.execute(
                text(
                    """
                    WITH latest_date AS (
                        SELECT MAX(trade_date) AS trade_date FROM stock.sdc_daily_indicator
                    ),
                    industry_peers AS (
                        SELECT di.symbol, di.pe_ttm,
                               ROW_NUMBER() OVER (ORDER BY di.pe_ttm ASC) AS rank,
                               COUNT(*) OVER () AS total
                        FROM stock.sdc_daily_indicator di
                        INNER JOIN stock.sdc_security s ON s.symbol = di.symbol
                        CROSS JOIN latest_date ld
                        WHERE s.industry = :industry
                          AND s.list_status = 'L'
                          AND di.trade_date = ld.trade_date
                          AND di.pe_ttm IS NOT NULL
                          AND di.pe_ttm > 0
                    )
                    SELECT rank, total
                    FROM industry_peers
                    WHERE symbol = :symbol
                    """,
                ),
                {"symbol": symbol, "industry": security.industry},
            )
            row = result.first()
            if row is None:
                return None, None
            return int(row.rank), int(row.total)

    async def _build_key_metrics(
        self,
        symbol: str,
        security: Security,
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        valuation = await self._technical.get_valuation(symbol)
        industry_rank, industry_total = self._industry_pe_cache or (None, None)
        dv = valuation.get("dv_ttm") if valuation.get("available") else None
        dv_pct = round(float(dv), 2) if isinstance(dv, (int, float)) else None

        institutional_hold_pct: float | None = None
        if not refresh:
            latest_rows = await StockDiagnosisSnapshot.filter(
                symbol=symbol,
                order_by=StockDiagnosisSnapshot.as_of.desc(),
                limit=1,
            )
            if latest_rows:
                cached_metrics = (latest_rows[0].detail or {}).get("key_metrics") or {}
                hold = cached_metrics.get("institutional_hold_pct")
                if hold is not None:
                    institutional_hold_pct = float(hold)
        if institutional_hold_pct is None:
            institutional_hold_pct = await self._akshare.fetch_fund_hold_pct(symbol)

        return self._normalize_key_metrics({
            "pe_ttm": valuation.get("pe_ttm") if valuation.get("available") else None,
            "pb": valuation.get("pb") if valuation.get("available") else None,
            "dv_ttm": dv_pct,
            "institutional_hold_pct": institutional_hold_pct,
            "industry_rank": industry_rank,
            "industry_total": industry_total,
            "industry_name": security.industry,
        })

    @staticmethod
    def _normalize_key_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(metrics)
        hold_pct = normalized.get("institutional_hold_pct")
        if hold_pct is not None and normalized.get("institutional_hold_source") is None:
            normalized["institutional_hold_source"] = "fund"
        return normalized

    @staticmethod
    def _compute_overall(modules: list[dict[str, Any]]) -> float | None:
        scored = [(m, m["score"], m["weight"]) for m in modules if m["score"] is not None]
        if not scored:
            return None
        total_weight = sum(w for _, _, w in scored)
        if total_weight <= 0:
            return None
        value = sum(s * w for _, s, w in scored) / total_weight
        return float(round(value, 1))

    async def _compute_market_percentile(
        self,
        overall: float | None,
        as_of: date,
    ) -> float | None:
        if overall is None:
            return None
        session_maker = engines_manager.get_session_maker("stock")
        async with session_maker() as session:
            result = await session.execute(
                text(
                    """
                    WITH latest AS (
                        SELECT MAX(as_of) AS as_of
                        FROM stock.sdc_stock_diagnosis_snapshot
                        WHERE as_of <= :as_of
                    )
                    SELECT
                        COUNT(*) FILTER (WHERE overall_score <= :score)::float
                        / NULLIF(COUNT(*), 0) * 100 AS pct
                    FROM stock.sdc_stock_diagnosis_snapshot s
                    INNER JOIN latest l ON s.as_of = l.as_of
                    WHERE s.overall_score IS NOT NULL
                    """,
                ),
                {"score": overall, "as_of": as_of},
            )
            row = result.first()
            if row is None or row.pct is None:
                return None
            return round(float(row.pct), 1)

    @staticmethod
    def _attach_prev_module_scores(
        modules: list[dict[str, Any]],
        prev: StockDiagnosisSnapshot | None,
    ) -> None:
        if prev is None:
            return
        detail = prev.detail or {}
        prev_modules = detail.get("modules") or []
        prev_map = {
            m["key"]: m.get("score")
            for m in prev_modules
            if isinstance(m, dict) and m.get("key")
        }
        for module in modules:
            module["prev_score"] = prev_map.get(module["key"])

    @staticmethod
    def _module_changes(
        modules: list[dict[str, Any]],
        *,
        min_delta: float = 0.3,
    ) -> list[tuple[float, dict[str, Any], float]]:
        changes: list[tuple[float, dict[str, Any], float]] = []
        for module in modules:
            cur = module.get("score")
            prev_score = module.get("prev_score")
            if cur is None or prev_score is None:
                continue
            delta = float(cur) - float(prev_score)
            if abs(delta) >= min_delta:
                changes.append((abs(delta), module, delta))
        changes.sort(key=lambda item: item[0], reverse=True)
        return changes

    @staticmethod
    def _rating_label(score: float | None) -> str | None:
        if score is None:
            return None
        if score >= 7.0:
            return "偏强"
        if score >= 4.0:
            return "中性"
        return "偏弱"

    @staticmethod
    def _highlight_segments(label: str) -> list[dict[str, Any]]:
        return [
            {"text": "【", "highlight": False},
            {"text": label, "highlight": True},
            {"text": "】", "highlight": False},
        ]

    @staticmethod
    def _build_rule_summary(
        modules: list[dict[str, Any]],
        overall: float | None,
        prev: StockDiagnosisSnapshot | None,
        *,
        name: str,
        prev_as_of: str | None,
    ) -> dict[str, Any]:
        bullets: list[str] = []
        highlights: list[dict[str, Any]] = []
        narrative: str | None = None

        prev_overall = prev.overall_score if prev else None
        if overall is not None and prev_overall is not None:
            delta = overall - prev_overall
            if abs(delta) >= 0.3:
                direction = "上调" if delta > 0 else "下调"
                bullets.append(
                    f"综合得分较上期{direction}{abs(delta):.1f}分（{prev_overall:.1f}→{overall:.1f}）",
                )

        module_changes = StockDiagnosisService._module_changes(modules, min_delta=0.3)
        top_modules = module_changes[:2]

        if max_module := (module_changes[0][1] if module_changes else None):
            max_change = module_changes[0][0]
            if max_change >= 0.5:
                bullets.append(
                    f"主要变化在{max_module['label']}模块"
                    f"（{max_module['prev_score']:.1f}→{max_module['score']:.1f}）",
                )

        high_modules = [m for m in modules if m.get("score") is not None and m["score"] >= 7.0]
        low_modules = [m for m in modules if m.get("score") is not None and m["score"] <= 3.0]
        if high_modules:
            labels = "、".join(m["label"] for m in high_modules[:2])
            bullets.append(f"{labels}表现较强")
        if low_modules:
            labels = "、".join(m["label"] for m in low_modules[:2])
            bullets.append(f"{labels}偏弱，需关注风险")

        if not bullets:
            bullets.append("各模块评分较上期变化不大，可点击「深度投研分析」获取交易策略。")

        if overall is not None and prev_overall is not None and prev_as_of:
            if top_modules:
                module_labels = [item[1]["label"] for item in top_modules]
                direction_words = [
                    "上升" if item[2] > 0 else "下降"
                    for item in top_modules
                ]
                if len(module_labels) == 1:
                    module_clause = (
                        f"【{module_labels[0]}】得分{direction_words[0]}"
                    )
                else:
                    module_clause = (
                        f"【{module_labels[0]}】和【{module_labels[1]}】得分"
                        f"{direction_words[0]}/{direction_words[1]}"
                    )
                narrative = (
                    f"{name}在{prev_as_of}综合得分由{prev_overall:.1f}分调整为"
                    f"{overall:.1f}分，近期平均分变化主要由于{module_clause}。"
                )
                for module in (item[1] for item in top_modules):
                    highlights.append({
                        "key": module["key"],
                        "label": module["label"],
                        "segments": StockDiagnosisService._highlight_segments(module["label"]),
                    })
            else:
                narrative = (
                    f"{name}在{prev_as_of}综合得分由{prev_overall:.1f}分调整为"
                    f"{overall:.1f}分，各模块评分较上期变化不大。"
                )
        elif overall is not None:
            rating = StockDiagnosisService._rating_label(overall)
            narrative = f"{name}当前综合得分{overall:.1f}分"
            if rating:
                narrative += f"，整体评价{rating}"
            narrative += "。"

        result: dict[str, Any] = {
            "bullets": bullets[:3],
            "generated_by": "rule",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        if narrative:
            result["narrative"] = narrative
        if highlights:
            result["highlights"] = highlights
        return result

    async def regenerate_ai_summary(self, symbol: str) -> dict[str, Any]:
        """基于最新快照重新生成 LLM 解读并写回（供异步 Worker 调用）。"""
        if not DiagnosisSummaryService.is_enabled():
            raise DataCollectionError("LLM 未配置，无法生成 Agent 诊股解读")

        security = await self._ensure_security(symbol)
        rows = await StockDiagnosisSnapshot.filter(
            symbol=symbol,
            order_by=StockDiagnosisSnapshot.as_of.desc(),
            limit=1,
        )
        if not rows:
            raise NotFoundException(message=f"诊股快照不存在: {symbol}")

        row = rows[0]
        payload = await self._build_payload_from_snapshot(row, security)
        summary = await self._summary.generate(
            DiagnosisSummaryService.build_context(payload),
        )
        await StockDiagnosisSnapshot.update_by_id(row.id, {"summary": summary})
        return {
            "symbol": symbol,
            "as_of": row.as_of.isoformat(),
            "summary": summary,
        }

    async def _thesis_snapshot(self, symbol: str) -> dict[str, Any] | None:
        thesis = await self._thesis.get_thesis(symbol)
        if not thesis or thesis.get("status") != "active":
            return None
        as_of = thesis.get("as_of")
        valid_until = thesis.get("valid_until")
        return {
            "direction": thesis.get("direction"),
            "as_of": as_of.isoformat() if isinstance(as_of, date) else as_of,
            "valid_until": valid_until.isoformat() if isinstance(valid_until, date) else valid_until,
            "core_assumption": thesis.get("core_assumption"),
        }

    async def _load_prev_snapshot(
        self,
        symbol: str,
        as_of: date,
    ) -> StockDiagnosisSnapshot | None:
        rows = await StockDiagnosisSnapshot.filter(
            symbol=symbol,
            as_of__lt=as_of,
            order_by=StockDiagnosisSnapshot.as_of.desc(),
            limit=1,
        )
        return rows[0] if rows else None

    async def _count_snapshots(self, symbol: str) -> int:
        return await StockDiagnosisSnapshot.count(symbol=symbol)

    @transactional(bind_key="stock")
    async def _save_snapshot(self, symbol: str, as_of: date, payload: dict[str, Any]) -> None:
        existing = await StockDiagnosisSnapshot.filter(symbol=symbol, as_of=as_of, limit=1)
        module_map = {m["key"]: m["score"] for m in payload["module_scores"]}
        record = {
            "symbol": symbol,
            "as_of": as_of,
            "overall_score": payload.get("overall_score"),
            "earnings_score": module_map.get("institutional"),
            "momentum_score": module_map.get("technical"),
            "fundamental_score": module_map.get("fundamental"),
            "valuation_score": module_map.get("industry"),
            "risk_score": module_map.get("sentiment"),
            "detail": {
                "schema_version": DIAGNOSIS_SCHEMA_VERSION,
                "modules": payload["module_scores"],
                "key_metrics": payload["key_metrics"],
                "thesis": payload.get("thesis"),
                "reports_count": payload.get("reports_count"),
                "prev_overall_score": payload.get("prev_overall_score"),
                "prev_as_of": payload.get("prev_as_of"),
                "market_percentile": payload.get("market_percentile"),
            },
            "summary": payload["summary"],
        }
        if existing:
            await StockDiagnosisSnapshot.update_by_id(existing[0].id, record)
        else:
            await StockDiagnosisSnapshot.create(**record)
