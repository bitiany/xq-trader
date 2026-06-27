"""GradeEvaluator 评级阈值单测。"""

from xqtrader.domain.factor.services.grade_evaluator import GradeEvaluator


def test_grade_a_boundary() -> None:
    ev = GradeEvaluator()
    assert ev.evaluate({"icir": 1.1, "long_short_annual_ret": 0.11, "turnover": 0.40}) == "A"


def test_grade_b_boundary() -> None:
    ev = GradeEvaluator()
    assert ev.evaluate({"icir": 0.6, "long_short_annual_ret": 0.06, "turnover": 0.65}) == "B"


def test_grade_c_boundary() -> None:
    ev = GradeEvaluator()
    assert ev.evaluate({"icir": 0.35, "long_short_annual_ret": 0.04, "turnover": 0.90}) == "C"


def test_grade_d_high_ret_wrong_unit_would_fail() -> None:
    """旧 Bug：用小数收益 0.11 不应触发 A（需 >10 的错误阈值）。"""
    ev = GradeEvaluator()
    # 0.11 年化 11%，ICIR 够但换手过高 → B 而非 A
    assert ev.evaluate({"icir": 1.1, "long_short_annual_ret": 0.11, "turnover": 0.55}) == "B"


def test_grade_d_missing_metrics() -> None:
    ev = GradeEvaluator()
    assert ev.evaluate({"icir": 2.0, "long_short_annual_ret": None, "turnover": 0.1}) == "D"


def test_global_grade_best_pool() -> None:
    ev = GradeEvaluator()
    assert ev.calc_global_grade({"all": "C", "idx_300": "A"}) == "A"
