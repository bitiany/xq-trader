"""诊股快照 schema v2 就绪判断单元测试。"""

from __future__ import annotations

from xqtrader.domain.security.services.stock_diagnosis_service import (
    DIAGNOSIS_SCHEMA_VERSION,
    StockDiagnosisService,
)


class TestSnapshotCacheReady:

    def test_rejects_legacy_dimensions_snapshot(self) -> None:
        detail = {
            "thesis": None,
            "reports_count": 1,
            "prev_overall_score": None,
            "dimensions": [],
        }
        assert StockDiagnosisService._snapshot_cache_ready(detail) is False

    def test_accepts_schema_v2_modules(self) -> None:
        detail = {
            "schema_version": DIAGNOSIS_SCHEMA_VERSION,
            "thesis": None,
            "reports_count": 1,
            "prev_overall_score": None,
            "modules": [
                {
                    "key": "technical",
                    "score": 5.0,
                    "detail": {},
                },
                {
                    "key": "capital_flow",
                    "score": 8.0,
                    "detail": {
                        "flow_series": [{"trade_date": "2026-07-07", "main_net_pct": 1.0}],
                        "net_5d": 1.0,
                    },
                },
                {
                    "key": "fundamental",
                    "score": 3.0,
                    "detail": {"rings": {"growth": 0.0}, "highlights": {"roe": 3.0}},
                },
                {"key": "sentiment", "score": 4.0, "detail": {}},
                {"key": "industry", "score": 5.0, "detail": {}},
                {"key": "institutional", "score": 6.0, "detail": {}},
            ],
        }
        assert StockDiagnosisService._snapshot_cache_ready(detail) is True
