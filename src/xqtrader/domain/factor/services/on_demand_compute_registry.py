"""OnDemandComputeRegistry — on_demand 因子计算与 SPI 插件的统一注册中心

职责（docs/factor-system-design.md §5.4 / §19.3）：
  1. on_demand 因子计算注册 — `compute_mode=on_demand` 的因子（chan_*/td_seq_*/donchian_*/close/volume）
     消费时由注册表实时计算，不走 DB（§5.4 白名单）。
  2. SPI 规则插件发现 — 14 个 RulePlugin 子类（MACD/KDJ/布林/缠论/九转 等），
     供 BacktestService / 决策流按 rule_id 或 plugin_class 解析。

设计要点：
  - 单例：模块级 `_REGISTRY` + `get_registry()` 访问。
  - 因子计算函数支持「一组共算」：chan_*/td_seq_* 一次调用产出多列，
    注册时按 group 注册，compute 时按 group 去重调用。
  - SPI 插件用鸭子类型校验（具备 evaluate/factor_ids 类属性），
    本模块不依赖 trading 层运行时导入（避免 factor→trading 反向依赖）。
  - 默认注册由 trading 层的 `register_default_on_demand_computes()` 完成（依赖反转）。

消费契约：
  - FactorPanelService.on_demand 分支 → 加载 OHLCV + compute_factors()
  - BacktestService / 决策流 → compute_factors() + get_plugin()
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import pandas as pd

from framework.commons.logger import get_logger

logger = get_logger(__name__)

# on_demand 因子计算函数：输入 OHLCV DataFrame，输出因子列 DataFrame（index 对齐）
ComputeFn = Callable[[pd.DataFrame], pd.DataFrame]


class RulePluginLike(Protocol):
    """SPI 规则插件鸭子类型协议（避免运行时依赖 trading 层）。"""

    rule_id: str
    name: str
    factor_ids: list[str]

    def evaluate(self, context: Any) -> Any: ...


class OnDemandComputeRegistry:
    """on_demand 因子计算 + SPI 插件统一注册中心。

    线程安全说明：注册发生在应用启动阶段（单线程），消费发生在运行时（只读），
    因此不加锁；若需运行时动态注册，调用方自行保证并发安全。
    """

    def __init__(self) -> None:
        # factor_id → (group_key, compute_fn)
        # 同一 group_key 的多个 factor_id 共享一次 compute_fn 调用
        self._factor_compute: dict[str, tuple[str, ComputeFn]] = {}
        # group_key → 该组所有 factor_id（用于 compute 时去重调用）
        self._group_factors: dict[str, list[str]] = {}
        # rule_id → 插件类
        self._plugins_by_rule_id: dict[str, type[RulePluginLike]] = {}
        # plugin_class 全限定名 → 插件类
        self._plugins_by_class: dict[str, type[RulePluginLike]] = {}

    # ================ on_demand 因子计算 ================

    def register_compute(
        self,
        factor_ids: list[str],
        compute_fn: ComputeFn,
        group_key: str | None = None,
    ) -> None:
        """注册一组共算的 on_demand 因子。

        Args:
            factor_ids: 该 compute_fn 一次产出的全部因子 ID（如 chan_buy_point/chan_sell_point/chan_bi_direction）
            compute_fn: 输入 OHLCV DataFrame，输出含 factor_ids 列的 DataFrame（index 与输入对齐）
            group_key: 共算组标识；默认取 factor_ids[0]，相同 group_key 覆盖旧注册
        """
        if not factor_ids:
            raise ValueError("factor_ids 不能为空")
        key = group_key or factor_ids[0]
        if key in self._group_factors:
            # 覆盖前清理旧 factor_id 映射
            for old_fid in self._group_factors[key]:
                self._factor_compute.pop(old_fid, None)
            logger.debug("[on_demand] 覆盖共算组 %s 旧注册", key)
        self._group_factors[key] = list(factor_ids)
        for fid in factor_ids:
            if fid in self._factor_compute:
                logger.warning(
                    "[on_demand] 因子 %s 已注册,将被共算组 %s 覆盖", fid, key,
                )
            self._factor_compute[fid] = (key, compute_fn)
        logger.info(
            "[on_demand] 注册共算组 %s: factors=%s", key, factor_ids,
        )

    def is_on_demand_factor(self, factor_id: str) -> bool:
        """判断 factor_id 是否为已注册的 on_demand 因子。"""
        return factor_id in self._factor_compute

    def list_on_demand_factors(self) -> list[str]:
        """列出全部已注册的 on_demand 因子 ID。"""
        return sorted(self._factor_compute.keys())

    def compute_factors(
        self,
        ohlcv_df: pd.DataFrame,
        factor_ids: list[str],
    ) -> pd.DataFrame:
        """按需计算 on_demand 因子列。

        按 group 去重调用 compute_fn，仅返回请求的 factor_ids 列。
        未注册的 factor_id 跳过并告警（调用方应预先用 is_on_demand_factor 校验）。

        Args:
            ohlcv_df: OHLCV DataFrame，至少含 open/high/low/close/volume 列
            factor_ids: 需要计算的 on_demand 因子 ID 列表

        Returns:
            DataFrame, index 与 ohlcv_df 对齐, columns=已成功计算的 factor_ids 子集
        """
        if ohlcv_df.empty or not factor_ids:
            return pd.DataFrame(index=ohlcv_df.index)

        # 按 group 聚合，避免同一 group 重复调用
        groups: dict[str, list[str]] = {}
        unknown: list[str] = []
        for fid in factor_ids:
            entry = self._factor_compute.get(fid)
            if entry is None:
                unknown.append(fid)
                continue
            gkey, _ = entry
            groups.setdefault(gkey, []).append(fid)

        if unknown:
            logger.warning(
                "[on_demand] 因子 %s 未注册,跳过计算", unknown,
            )

        if not groups:
            return pd.DataFrame(index=ohlcv_df.index)

        columns: dict[str, pd.Series] = {}
        for gkey, requested in groups.items():
            compute_fn = self._factor_compute[requested[0]][1]
            try:
                produced = compute_fn(ohlcv_df)
            except Exception:
                logger.error(
                    "[on_demand] 共算组 %s 计算失败 factor_ids=%s",
                    gkey, requested, exc_info=True,
                )
                continue
            for fid in requested:
                if fid in produced.columns:
                    columns[fid] = produced[fid]
                else:
                    logger.warning(
                        "[on_demand] 共算组 %s 未产出列 %s", gkey, fid,
                    )

        if not columns:
            return pd.DataFrame(index=ohlcv_df.index)
        return pd.DataFrame(columns, index=ohlcv_df.index)

    # ================ SPI 插件发现 ================

    def register_plugin(self, plugin_cls: type[RulePluginLike]) -> None:
        """注册一个 SPI 规则插件类。

        Args:
            plugin_cls: RulePlugin 子类（需具备 rule_id/factor_ids 类属性与 evaluate 方法）
        """
        # 鸭子类型校验（不导入 RulePlugin，避免反向依赖）
        if not (
            hasattr(plugin_cls, "rule_id")
            and hasattr(plugin_cls, "factor_ids")
            and hasattr(plugin_cls, "evaluate")
        ):
            raise TypeError(
                f"{plugin_cls} 不符合 RulePlugin 接口（缺少 rule_id/factor_ids/evaluate）"
            )

        rule_id = plugin_cls.rule_id  # type: ignore[attr-defined]
        full_name = f"{plugin_cls.__module__}.{plugin_cls.__qualname__}"

        if rule_id in self._plugins_by_rule_id and self._plugins_by_rule_id[rule_id] is not plugin_cls:
            logger.warning(
                "[on_demand] rule_id=%s 已注册插件 %s,将被 %s 覆盖",
                rule_id, self._plugins_by_rule_id[rule_id].__qualname__, plugin_cls.__qualname__,
            )
        self._plugins_by_rule_id[rule_id] = plugin_cls
        self._plugins_by_class[full_name] = plugin_cls
        logger.info(
            "[on_demand] 注册 SPI 插件 rule_id=%s class=%s", rule_id, full_name,
        )

    def get_plugin_by_rule_id(self, rule_id: str) -> type[RulePluginLike] | None:
        """按 rule_id 获取插件类。"""
        return self._plugins_by_rule_id.get(rule_id)

    def get_plugin_by_class(self, plugin_class: str) -> type[RulePluginLike] | None:
        """按全限定类名获取插件类。

        优先精确匹配；未命中则按类名后缀模糊匹配（容错）。
        """
        if not plugin_class:
            return None
        if plugin_class in self._plugins_by_class:
            return self._plugins_by_class[plugin_class]
        # 容错：按 qualname 结尾匹配（如 "macd.MACDPlugin"）
        for full_name, cls in self._plugins_by_class.items():
            if full_name.endswith(plugin_class) or plugin_class.endswith(cls.__qualname__):
                return cls
        return None

    def list_plugins(self) -> list[type[RulePluginLike]]:
        """列出全部已注册的 SPI 插件类。"""
        return list(self._plugins_by_rule_id.values())

    def list_plugin_rule_ids(self) -> list[str]:
        """列出全部已注册的 SPI 插件 rule_id。"""
        return sorted(self._plugins_by_rule_id.keys())

    def clear(self) -> None:
        """清空全部注册（仅用于测试）。"""
        self._factor_compute.clear()
        self._group_factors.clear()
        self._plugins_by_rule_id.clear()
        self._plugins_by_class.clear()


# ==================== 单例 ====================

_REGISTRY: OnDemandComputeRegistry | None = None


def get_registry() -> OnDemandComputeRegistry:
    """获取 OnDemandComputeRegistry 单例。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = OnDemandComputeRegistry()
    return _REGISTRY


def reset_registry() -> None:
    """重置单例（仅用于测试）。

    注意：本函数仅重置 registry 单例本身。若 trading 层的
    ``register_default_on_demand_computes`` 已执行过（``_registered=True``），
    需先调用 ``reset_default_on_demand_computes()`` 重置该标志，
    否则后续 ``register_default_on_demand_computes()`` 会因幂等检查而跳过注册。
    """
    global _REGISTRY
    _REGISTRY = None
