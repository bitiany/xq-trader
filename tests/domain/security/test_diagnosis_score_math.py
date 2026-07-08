"""诊股评分数学工具单元测试。"""

from __future__ import annotations

from xqtrader.domain.security.services.diagnosis_module_scorers import DiagnosisScoreMath


class TestDiagnosisScoreMath:

    def test_avg_last_uses_daily_mean_not_sum(self) -> None:
        values = [4.08, 5.58, 2.8, 18.71, -0.27]
        assert round(DiagnosisScoreMath.avg_last(values, 5), 2) == 6.18

    def test_clamp_bounds(self) -> None:
        assert DiagnosisScoreMath.clamp(12.0) == 10.0
        assert DiagnosisScoreMath.clamp(-1.0) == 0.0
