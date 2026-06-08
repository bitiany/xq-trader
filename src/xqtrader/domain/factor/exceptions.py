"""因子领域异常层级。

禁止使用通用异常（ValueError/RuntimeError），所有因子相关异常须使用本模块定义的领域异常。
"""

from __future__ import annotations


class FactorError(Exception):
    """因子领域异常基类。"""


class FactorComputeError(FactorError):
    """因子计算异常。"""


class FactorLoadError(FactorError):
    """因子数据加载异常。"""


class FactorPersistError(FactorError):
    """因子持久化异常。"""


class FactorPreprocessError(FactorError):
    """因子预处理异常。"""


class FactorPITError(FactorError):
    """PIT截面取值异常。"""
