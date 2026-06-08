"""因子定义声明 — 代码为唯一真相源 (Single Source of Truth)。

每个 FactorDefinition 声明因子的静态属性，启动时同步到 fac_factor_registry 表。
运行时状态（factor_grade, status）由评估管线动态更新，保留数据库值。
"""

from xqtrader.domain.factor.definitions.alpha import ALPHA_FACTORS
from xqtrader.domain.factor.definitions.candlestick import CANDLESTICK_FACTORS
from xqtrader.domain.factor.definitions.chan import CHAN_FACTORS
from xqtrader.domain.factor.definitions.factor_def import FactorDefinition
from xqtrader.domain.factor.definitions.fundamental import FUNDAMENTAL_FACTORS
from xqtrader.domain.factor.definitions.quantitative import QUANTITATIVE_FACTORS
from xqtrader.domain.factor.definitions.risk import RISK_FACTORS
from xqtrader.domain.factor.definitions.technical import TECHNICAL_FACTORS

# 因子定义注册表（模块级单例）
_ALL_DEFINITIONS: list[FactorDefinition] = (
    RISK_FACTORS
    + FUNDAMENTAL_FACTORS
    + TECHNICAL_FACTORS
    + QUANTITATIVE_FACTORS
    + CHAN_FACTORS
    + CANDLESTICK_FACTORS
    + ALPHA_FACTORS
)


def get_all_definitions() -> list[FactorDefinition]:
    """获取所有因子定义。"""
    return _ALL_DEFINITIONS
