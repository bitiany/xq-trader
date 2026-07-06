from framework.commons.logger import get_logger

logger = get_logger(__name__)

_GRADE_ORDER: dict[str, int] = {"A": 4, "B": 3, "C": 2, "D": 1}


class GradeEvaluator:
    """因子评级评估服务，基于 IC/ICIR 和分层回测结果评定因子等级（A/B/C/D）。

    阈值口径适配 A 股个人版实际（技术因子 IC 普遍 0.02~0.05，ICIR 0.1~0.3）：
      - A 级：ICIR > 0.3 + 多空正收益 + 低换手（业界优秀，可实盘）
      - B 级：ICIR > 0.15 + 多空正收益（有效且可交易）
      - C 级：ICIR > 0.05 或 多空正收益（有微弱信号，待观察）
      - D 级：ICIR ≤ 0.05 且 多空非正（明显无效）

    主维度 ICIR（预测稳定性，不受成本扣除影响），辅维度 long_short_annual_ret
    （扣成本后实际选股能力），约束 turnover（可交易性）。
    """

    def evaluate(self, stats: dict) -> str:
        """根据统计指标评估因子等级。

        Args:
            stats: 包含 icir, long_short_annual_ret, turnover, ic_win_rate, coverage 的字典

        Returns:
            等级字符串: 'A', 'B', 'C', 'D'
        """
        icir = stats.get("icir")
        long_short_annual_ret = stats.get("long_short_annual_ret")
        turnover = stats.get("turnover")

        if icir is None or long_short_annual_ret is None or turnover is None:
            logger.info(
                "缺少必要统计指标，评级降为 D: icir=%s, ret=%s, turnover=%s",
                icir, long_short_annual_ret, turnover,
            )
            return "D"

        # 阈值口径：long_short_annual_ret / turnover 均为小数（10% = 0.10，换手 50% = 0.50）
        # A 级：ICIR 强 + 多空盈利 + 低换手（业界优秀，可实盘）
        if icir > 0.3 and long_short_annual_ret > 0 and turnover < 0.50:
            return "A"
        # B 级：ICIR 有效 + 多空盈利（有效且可交易）
        if icir > 0.15 and long_short_annual_ret > 0:
            return "B"
        # C 级：ICIR 有信号 或 多空微盈利（有微弱预测力，待观察）
        if icir > 0.05 or long_short_annual_ret > 0:
            return "C"
        return "D"

    def evaluate_all(self, factor_stats_list: list[dict]) -> list[dict]:
        """批量评估多个因子的等级。

        Args:
            factor_stats_list: 每个元素包含 factor_id, pool_id, stat 字段

        Returns:
            每个字典新增 factor_grade 键后的列表
        """
        for item in factor_stats_list:
            stats = item.get("stat", {})
            grade = self.evaluate(stats)
            item["factor_grade"] = grade
            logger.debug("因子 %s 在样本池 %s 评级为 %s", item.get("factor_id"), item.get("pool_id"), grade)
        return factor_stats_list

    def calc_global_grade(self, pool_grades: dict[str, str]) -> str:
        """根据各样本池等级计算全局因子等级（最优样本池规则）。

        Args:
            pool_grades: {pool_id: grade} 各样本池的因子等级

        Returns:
            全局等级，取所有样本池中的最高等级
        """
        if not pool_grades:
            return "D"

        best_grade = "D"
        for pool_id, grade in pool_grades.items():
            if _GRADE_ORDER.get(grade, 0) > _GRADE_ORDER.get(best_grade, 0):
                best_grade = grade
        logger.debug("全局评级计算完成: pool_grades=%s, global_grade=%s", pool_grades, best_grade)
        return best_grade
