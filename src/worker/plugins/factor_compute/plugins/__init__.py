"""因子计算插件包 — 导出所有插件类与注册表。"""

from worker.plugins.factor_compute.plugins.base import FactorPlugin, FactorPluginRegistry
from worker.plugins.factor_compute.plugins.fund_flow import FundFlowPlugin
from worker.plugins.factor_compute.plugins.fundamental import FundamentalPlugin
from worker.plugins.factor_compute.plugins.momentum import MomentumPlugin
from worker.plugins.factor_compute.plugins.quantitative import QuantitativePlugin
from worker.plugins.factor_compute.plugins.risk import RiskPlugin
from worker.plugins.factor_compute.plugins.technical import TechnicalPlugin
from worker.plugins.factor_compute.plugins.valuation import ValuationPlugin

__all__ = [
    "FactorPlugin",
    "FactorPluginRegistry",
    "FundFlowPlugin",
    "FundamentalPlugin",
    "MomentumPlugin",
    "QuantitativePlugin",
    "RiskPlugin",
    "TechnicalPlugin",
    "ValuationPlugin",
]
