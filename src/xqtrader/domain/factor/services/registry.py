"""因子注册表 — 自动发现、注册、变体管理。

设计原则：
  - 代码声明为唯一真相源（FactorPlugin 子类）
  - Worker 启动时自动发现 factors/ 目录下的所有因子插件
  - 组合因子（如 MACD）通过 group_id 关联子因子
  - 变体因子（如 MA(5)/MA(10)）通过 _FACTOR_VARIANTS 延迟注册
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from framework.commons.logger import get_logger
from xqtrader.domain.factor.base import FactorDefinition, FactorPlugin
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry

logger = get_logger("factor.registry")

_REGISTRY: dict[str, FactorPlugin] = {}
_GROUP_MAP: dict[str, FactorPlugin] = {}
_CHILD_TO_GROUP: dict[str, str] = {}
_DISCOVERED = False
_VARIANTS_REGISTERED = False


def register_factor(factor: FactorPlugin, overwrite: bool = True) -> None:
    """注册因子插件到全局注册表。"""
    if factor.factor_id in _REGISTRY and not overwrite:
        return
    _REGISTRY[factor.factor_id] = factor
    logger.debug("Registered factor: %s (%s)", factor.factor_id, factor.display_name)
    if factor.is_composite and factor.group_id:
        _GROUP_MAP[factor.group_id] = factor
        for child_id in factor.composite_factor_ids:
            _CHILD_TO_GROUP[child_id] = factor.group_id


def get_factor(factor_id: str) -> FactorPlugin | None:
    """获取已注册的因子插件。"""
    return _REGISTRY.get(factor_id)


def get_all_factors() -> dict[str, FactorPlugin]:
    """获取所有已注册的因子插件。"""
    return dict(_REGISTRY)


async def get_factors_by_ids(factor_ids: list[str]) -> list[FactorPlugin]:
    """根据因子ID列表解析因子插件，自动展开组合因子。"""
    factors: list[FactorPlugin] = []
    seen_ids: set[str] = set()

    for fid in factor_ids:
        # 直接命中
        f = _REGISTRY.get(fid)
        if f and f.factor_id not in seen_ids:
            factors.append(f)
            seen_ids.add(f.factor_id)
            continue

        # 子因子 → 找到组合因子组
        group_id = _CHILD_TO_GROUP.get(fid)
        if group_id:
            group_plugin = _GROUP_MAP.get(group_id)
            if group_plugin and group_plugin.factor_id not in seen_ids:
                factors.append(group_plugin)
                seen_ids.add(group_plugin.factor_id)
            continue

        # group_id 本身
        group_plugin = _GROUP_MAP.get(fid)
        if group_plugin and group_plugin.factor_id not in seen_ids:
            factors.append(group_plugin)
            seen_ids.add(group_plugin.factor_id)
            continue

        logger.warning("Factor not found: %s", fid)

    return factors


async def get_active_factors() -> list[FactorPlugin]:
    """获取所有活跃因子（默认返回全部已注册因子）。"""
    return list(_REGISTRY.values())


def get_factor_definitions() -> list[FactorDefinition]:
    """获取所有因子的元数据声明。"""
    return [f.get_definition() for f in _REGISTRY.values()]


def auto_discover_factors() -> int:
    """自动发现 factors/ 目录下的所有因子插件。"""
    global _DISCOVERED
    if _DISCOVERED:
        return len(_REGISTRY)
    _DISCOVERED = True

    import worker.plugins.factor_compute.factors as factors_pkg

    count = 0
    for _importer, modname, _ispkg in pkgutil.iter_modules(factors_pkg.__path__):
        if modname.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"worker.plugins.factor_compute.factors.{modname}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, FactorPlugin)
                    and attr is not FactorPlugin
                    and hasattr(attr, "factor_id")
                ):
                    if not attr.factor_id and not getattr(attr, "is_composite", False):
                        continue
                    try:
                        instance = attr()
                        register_factor(instance, overwrite=False)
                        count += 1
                    except TypeError:
                        continue
                    except Exception as e:
                        logger.warning("Failed to instantiate %s: %s", attr_name, e, exc_info=True)
        except Exception as e:
            logger.warning("Failed to import factor module %s: %s", modname, e, exc_info=True)

    logger.info("Auto-discovered %d factor plugins", count)
    return count


def register_factor_variants() -> int:
    """注册参数化变体因子（如 MA(5)/MA(10)/MA(20) 等）。"""
    global _VARIANTS_REGISTERED
    if _VARIANTS_REGISTERED:
        return 0
    _VARIANTS_REGISTERED = True

    count = 0
    for module_class, params in _FACTOR_VARIANTS:
        module_path, class_name = module_class.rsplit(":", 1)
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            instance = cls(**params)
            register_factor(instance, overwrite=False)
            count += 1
        except Exception as e:
            logger.warning("Failed to register variant %s(%s): %s", module_class, params, e, exc_info=True)
    logger.info("Registered %d factor variants", count)
    return count


async def resolve_factor_list(factor_ids: list[str] | None) -> list[FactorPlugin]:
    """解析因子列表 — 自动发现+注册后按ID或全量返回。"""
    auto_discover_factors()
    register_factor_variants()
    if not factor_ids:
        return await get_active_factors()
    return await get_factors_by_ids(factor_ids)


def has_stateful_factors(factors: list[FactorPlugin]) -> bool:
    """检查因子列表中是否包含有状态因子（需要全量历史数据）。"""
    return any(f.requires_full_history for f in factors)


async def sync_to_registry() -> int:
    """将内存注册表同步到 fac_factor_registry 表。

    代码为唯一真相源：以内存中的 FactorDefinition 为准 upsert 到 DB，
    DB 专有字段（factor_grade, status, report_lag_days）不会被覆盖。
    """
    if not _REGISTRY:
        logger.warning("[sync] registry is empty, skip sync")
        return 0

    rows: list[FacFactorRegistry] = []
    for plugin in _REGISTRY.values():
        defn = plugin.get_definition()
        rows.append(FacFactorRegistry(
            factor_id=defn.factor_id,
            display_name=defn.display_name,
            category=defn.category,
            group_id=defn.group_id or "",
            direction=defn.direction,
            scope=defn.scope,
            signal_type=defn.signal_type,
            base_factor=defn.base_factor or "",
            dependencies=",".join(defn.dependencies),
            min_periods=defn.min_periods,
            compute_module=defn.compute_module or "",
            params=defn.params if defn.params else {},
            data_origin=defn.data_origin or "computed",
            update_freq=defn.update_freq,
            compute_engine=defn.compute_engine,
            tags=defn.tags or "",
            status="draft",
            factor_grade=None,
            report_lag_days=0,
            is_composite=1 if defn.is_composite else 0,
            composite_factor_ids=",".join(defn.composite_factor_ids),
            skip_preprocess=1 if getattr(plugin, "skip_preprocess", False) else 0,
            description=defn.description or "",
        ))

        # 组合因子的子因子自动注册（如 macd_dif / macd_dea / macd_hist）
        if defn.is_composite and defn.composite_factor_ids:
            for child_id in defn.composite_factor_ids:
                rows.append(FacFactorRegistry(
                    factor_id=child_id,
                    display_name=f"{defn.display_name}·{child_id}",
                    category=defn.category,
                    group_id=defn.group_id or "",
                    direction=defn.direction,
                    scope=defn.scope,
                    signal_type=defn.signal_type,
                    base_factor=defn.factor_id,
                    dependencies=",".join(defn.dependencies),
                    min_periods=defn.min_periods,
                    compute_module=defn.compute_module or "",
                    params=defn.params if defn.params else {},
                    data_origin=defn.data_origin or "computed",
                    update_freq=defn.update_freq,
                    compute_engine=defn.compute_engine,
                    tags=defn.tags or "",
                    status="draft",
                    factor_grade=None,
                    report_lag_days=0,
                    is_composite=0,
                    composite_factor_ids="",
                    skip_preprocess=1 if getattr(plugin, "skip_preprocess", False) else 0,
                    description=f"{defn.display_name}子因子",
                ))

    count = await FacFactorRegistry.bulk_create_or_update(
        rows,  # type: ignore[arg-type]
        on_conflict=["factor_id"],
        update_fields=[
            "display_name", "category", "group_id", "direction", "scope",
            "signal_type", "base_factor", "dependencies", "min_periods",
            "compute_module", "params", "data_origin", "update_freq",
            "compute_engine", "tags", "is_composite",
            "composite_factor_ids", "skip_preprocess", "description",
        ],
        batch_size=100,
    )
    logger.info("[sync] synced %d factor definitions to DB", count)
    return count


# ── 参数化变体定义 ──
# 格式：(模块路径:类名, 构造参数)
_FACTOR_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    # A1 规模因子
    ("worker.plugins.factor_compute.factors.risk:CsLogMvFactor", {}),
    # A3 波动率因子（Barra 风险因子）
    ("worker.plugins.factor_compute.factors.risk:DastdFactor", {}),
    ("worker.plugins.factor_compute.factors.risk:CmraFactor", {}),
    # A4 流动性因子
    ("worker.plugins.factor_compute.factors.risk:CsTurnoverFactor", {}),
    ("worker.plugins.factor_compute.factors.risk:TurnoverFFactor", {}),
    ("worker.plugins.factor_compute.factors.risk:CsLogAmountFactor", {}),
    ("worker.plugins.factor_compute.factors.risk:CsVolumeRatioFactor", {}),
    # C4 均线偏离（替代原始均线值，偏离度截面可比）
    ("worker.plugins.factor_compute.factors.tech_ma:MABiasFactor", {"period": 5}),
    ("worker.plugins.factor_compute.factors.tech_ma:MABiasFactor", {"period": 10}),
    ("worker.plugins.factor_compute.factors.tech_ma:MABiasFactor", {"period": 20}),
    ("worker.plugins.factor_compute.factors.tech_ma:MABiasFactor", {"period": 60}),
    ("worker.plugins.factor_compute.factors.tech_ma:MABiasDeltaFactor", {"period": 20}),
    # C3 超买超卖
    ("worker.plugins.factor_compute.factors.tech_oscillator:RSIFactor", {"period": 6}),
    ("worker.plugins.factor_compute.factors.tech_oscillator:RSIFactor", {"period": 14}),
    ("worker.plugins.factor_compute.factors.tech_oscillator:RSIFactor", {"period": 24}),
    ("worker.plugins.factor_compute.factors.tech_oscillator:RSIDeltaFactor", {"period": 14}),
    ("worker.plugins.factor_compute.factors.tech_oscillator:KDJFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_oscillator:CCIFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_oscillator:WILLRFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_oscillator:BIASFactor", {"period": 6}),
    ("worker.plugins.factor_compute.factors.tech_oscillator:BIASFactor", {"period": 12}),
    ("worker.plugins.factor_compute.factors.tech_oscillator:BIASFactor", {"period": 24}),
    # C2 趋势（MACD标准化 + ADX + BOLL位置 + SAR偏离）
    ("worker.plugins.factor_compute.factors.tech_trend:MACDHistRatioFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_trend:MACDHistDeltaFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_trend:ADXFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_trend:ADXDeltaFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_trend:BOLLPositionFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_trend:SARDeviationFactor", {}),
    # A3 波动率（ATR标准化替代原始ATR）
    ("worker.plugins.factor_compute.factors.tech_volatility:ATRRatioFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_volatility:ATRRatioDeltaFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_volatility:VolatilityFactor", {"period": 10}),
    ("worker.plugins.factor_compute.factors.tech_volatility:VolatilityFactor", {"period": 20}),
    ("worker.plugins.factor_compute.factors.tech_volatility:VolatilityFactor", {"period": 60}),
    ("worker.plugins.factor_compute.factors.tech_volatility:NatrFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_volatility:DownsideVolFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_volatility:AmihudFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_volatility:VolOscFactor", {}),
    ("worker.plugins.factor_compute.factors.tech_volatility:ADVFactor", {"period": 20}),
    # C1 动量/反转（删除ReversalFactor，与Momentum完全共线）
    ("worker.plugins.factor_compute.factors.momentum:CsPctChgFactor", {}),
    ("worker.plugins.factor_compute.factors.momentum:MomentumFactor", {"period": 5}),
    ("worker.plugins.factor_compute.factors.momentum:MomentumFactor", {"period": 20}),
    ("worker.plugins.factor_compute.factors.momentum:MomentumFactor", {"period": 60}),
    ("worker.plugins.factor_compute.factors.momentum:BarraMomentumFactor", {}),
    ("worker.plugins.factor_compute.factors.momentum:BarraShortTermReversalFactor", {}),
    ("worker.plugins.factor_compute.factors.momentum:RocFactor", {"period": 10}),
    # D3 资金流（占比形式替代绝对金额，截面可比）
    ("worker.plugins.factor_compute.factors.fund_flow:CsMainNetPctFactor", {}),
    ("worker.plugins.factor_compute.factors.fund_flow:CsNetMfPctFactor", {}),
    ("worker.plugins.factor_compute.factors.fund_flow:HugeNetPctFactor", {}),
    ("worker.plugins.factor_compute.factors.fund_flow:BigNetPctFactor", {}),
    # D类 Alpha101 量价因子
    ("worker.plugins.factor_compute.factors.alpha101:Alpha12Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha101:Alpha101Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha101:Alpha55Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha101:Alpha1Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha101:Alpha33Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha101:Alpha41Factor", {}),
    # D类 Alpha158 量价因子
    ("worker.plugins.factor_compute.factors.alpha158:Kmid5Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha158:Klen5Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha158:Kup25Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha158:Klow25Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha158:Rsv9Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha158:Cntp20Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha158:Imax20Factor", {}),
    ("worker.plugins.factor_compute.factors.alpha158:Roc5CloseFactor", {}),
    ("worker.plugins.factor_compute.factors.alpha158:Std20CloseFactor", {}),
    ("worker.plugins.factor_compute.factors.alpha158:CorrPv10Factor", {}),
    # 前向收益率（评估标签）
    ("worker.plugins.factor_compute.factors.return_factor:ReturnFactor", {"period": 1}),
    ("worker.plugins.factor_compute.factors.return_factor:ReturnFactor", {"period": 5}),
    ("worker.plugins.factor_compute.factors.return_factor:ReturnFactor", {"period": 20}),
    # E2 K线形态聚合因子
    ("worker.plugins.factor_compute.factors.candle_pattern:CdlBullFreqFactor", {}),
    ("worker.plugins.factor_compute.factors.candle_pattern:CdlBearFreqFactor", {}),
    ("worker.plugins.factor_compute.factors.candle_pattern:CdlNetScoreFactor", {}),
    ("worker.plugins.factor_compute.factors.candle_pattern:CdlUpperShadowRatioFactor", {}),
    ("worker.plugins.factor_compute.factors.candle_pattern:CdlLowerShadowRatioFactor", {}),
    ("worker.plugins.factor_compute.factors.candle_pattern:CdlBodyRatioFactor", {}),
]
