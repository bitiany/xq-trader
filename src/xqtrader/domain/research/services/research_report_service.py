"""券商研报查询服务 — 基于已采集的 ResearchReport 表提供只读查询。"""

from __future__ import annotations

from datetime import date
from typing import Any

from framework.commons.exceptions import NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.domain.research.models.research_report import ResearchReport


class ResearchReportService:
    """券商研报服务。"""

    async def list_reports(
        self,
        symbol: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        skip, limit = paginate(page, page_size)
        rows = await ResearchReport.filter(
            symbol=symbol, skip=skip, limit=limit,
            order_by=ResearchReport.publish_date.desc(),
        )
        total = await ResearchReport.count(symbol=symbol)
        items = [self._report_summary(r) for r in rows]
        return build_paginated_response(items, total, page, page_size)

    async def get_report(self, info_code: str) -> dict[str, Any]:
        rows = await ResearchReport.filter(info_code=info_code, limit=1)
        if not rows:
            raise NotFoundException(message=f"研报不存在: {info_code}")
        return self._report_detail(rows[0])

    @staticmethod
    def _report_summary(r: ResearchReport) -> dict[str, Any]:
        return {
            "info_code": r.info_code,
            "title": r.title,
            "org_name": r.org_name,
            "researcher": r.researcher,
            "rating": r.rating,
            "rating_change": r.rating_change,
            "publish_date": r.publish_date.isoformat() if isinstance(r.publish_date, date) else r.publish_date,
            "industry": r.industry,
            "eps_forecast": r.eps_forecast or [],
            "pdf_url": r.pdf_url,
        }

    @staticmethod
    def _report_detail(r: ResearchReport) -> dict[str, Any]:
        base = ResearchReportService._report_summary(r)
        base["summary"] = r.summary
        base["content"] = r.content
        base["pdf_path"] = r.pdf_path
        return base
