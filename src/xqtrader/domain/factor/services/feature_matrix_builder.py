"""ML 特征矩阵构建器 — 复用 CrossSectionReader + factor_data_loader。

职责单一：仅负责将多因子面板对齐为 ML 特征矩阵 (X) 和标签 (y)。
不做模型训练（由 MLCombiner 负责），不做时间窗口切分（由 WalkForwardEngine 负责）。

核心设计：
  - 标签：截面收益 rank（pct=True, 0-1 之间），避免标签漂移
  - 特征：所有 status='active' 因子，复用 preload_factor_raw_panels 批量加载
  - 因子数据统一使用 pool_id="all"：单因子按单标的计算，不区分股池
  - 预处理：复用 CrossSectionReader.process_preloaded_factor_panel 五步管线
  - Rank变换：截面内转为 [0,1] 均匀分布，消除非线性/偏态/厚尾
  - 防泄漏：PIT 成分过滤 + 严格按 walk-forward 窗口日期切分
  - 数据完整性：训练前预检查所有因子数据覆盖率，不完整直接报错结束
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.services import factor_data_loader as fdl
from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader
from xqtrader.domain.factor.services.factor_data_loader import _BATCH_LOADABLE_ORIGINS
from xqtrader.domain.factor.services.walk_forward_engine import WalkForwardWindow

logger = get_logger("factor.feature_matrix")

# 不参与 ML 训练的因子类别（与 factor_evaluate 任务保持一致）：
# - return: 评估标签（fwd_ret_*），作为 y 而非 X
# - chanlun: 非截面连续值，覆盖率仅 6%
# - composite_*/interaction: 合成产物，避免与底层因子重复
_EXCLUDED_CATEGORIES: tuple[str, ...] = (
    "return", "chanlun", "composite_group", "composite_cross", "interaction",
    "composite_ml",  # ML 合成产物自身不作为输入特征
)
_EXCLUDED_UPDATE_FREQS: tuple[str, ...] = ("quarterly",)


class FeatureMatrixBuilder:
    """ML 特征矩阵构建器。

    使用方式：
        builder = FeatureMatrixBuilder(reader)
        X_train, y_train, feature_names = await builder.build_dataset(window, pool_id, horizon=5)
    """

    def __init__(
        self,
        reader: CrossSectionReader | None = None,
        rank_transform: bool = False,
    ) -> None:
        """初始化特征矩阵构建器。

        Args:
            reader: 截面数据读取器，None 则自动创建
            rank_transform: 是否对特征做截面 rank 变换（默认 False）
                - False: 仅依赖 CrossSectionReader 五步预处理（MAD/Z-score/中性化）
                - True: 额外做截面 rank 变换（消除非线性/偏态/厚尾）
        """
        self.reader = reader or CrossSectionReader()
        self.rank_transform = rank_transform

    def _apply_cross_section_rank(self, x: pd.DataFrame) -> pd.DataFrame:
        """对特征矩阵做截面 rank 变换。

        每个截面日（trade_date）内，将每列因子值转为 [0,1] 均匀分布的 rank。
        这能同时解决三个问题：
          1. 非线性单调关系：rank 变换后变为线性，便于树模型学习分裂
          2. 分布偏态/厚尾：rank 后为均匀分布，无偏态无厚尾
          3. 极值影响：rank 有界 [0,1]，天然去极值

        NaN 值保持不变（不参与 rank），LightGBM 原生支持 NaN 处理。

        Args:
            x: 特征矩阵, MultiIndex(trade_date, symbol), columns=因子名

        Returns:
            rank 变换后的特征矩阵（同形状）
        """
        if x.empty:
            return x

        # 按截面日分组，每列做 pct rank
        ranked = x.groupby(level="trade_date").rank(pct=True)
        logger.info(
            "[feature_matrix] rank 变换完成: shape=%s", ranked.shape,
        )
        return ranked

    async def load_active_factor_ids(
        self,
        min_grade: str = "C",
    ) -> list[str]:
        """加载所有参与 ML 训练的活跃因子 ID。

        筛选规则：
          - status='active'
          - category 不在排除集合（return/chanlun/composite_*/interaction）
          - update_freq 不在排除集合（quarterly 由独立任务处理）
          - factor_grade >= min_grade（默认 C 级，剔除 D 级噪声因子）

        因子等级评定：
          A: IC > 0.08
          B: IC > 0.05
          C: IC > 0.03
          D: IC <= 0.03（无显著预测力，剔除）

        Args:
            min_grade: 最低因子等级，默认 "C"（保留 A+B+C，剔除 D）
        """
        all_factors = await FacFactorRegistry.filter(status="active")
        excluded_cat = set(_EXCLUDED_CATEGORIES)
        excluded_freq = set(_EXCLUDED_UPDATE_FREQS)
        grade_order = {"A": 4, "B": 3, "C": 2, "D": 1}
        min_grade_val = grade_order.get(min_grade, 2)

        factors = [
            f for f in all_factors
            if f.category not in excluded_cat
            and (f.update_freq or "daily") not in excluded_freq
            and grade_order.get(f.factor_grade or "D", 1) >= min_grade_val
        ]
        factor_ids = [f.factor_id for f in factors]

        # 统计各等级分布
        grade_dist: dict[str, int] = {}
        for f in factors:
            g = f.factor_grade or "D"
            grade_dist[g] = grade_dist.get(g, 0) + 1

        logger.info(
            "[feature_matrix] 活跃因子: %d 个 (全量=%d, 排除类别=%s, 排除频率=%s, "
            "最低等级=%s, 等级分布=%s)",
            len(factor_ids), len(all_factors), excluded_cat, excluded_freq,
            min_grade, dict(sorted(grade_dist.items())),
        )
        return factor_ids

    async def verify_data_completeness(
        self,
        start_date: date,
        end_date: date,
        factor_ids: list[str],
    ) -> None:
        """训练前预检查存储在 fac_factor_value 表中的因子数据覆盖率。

        仅检查实际持久化到 fac_factor_value 表中的因子：
          - data_origin in {"computed", "fund_flow", "market"}：按 factor_id 直接查

        跳过两类不存储在 fac_factor_value 的因子：
          1. data_origin 非 batch_loadable（cross_section / SPI / fundamental 等）：
             由运行时按需计算或从其他表加载
          2. SPI 虚拟父因子（如 kdj/adx/boll）：
             同一插件类多输出场景下的"命名空间标识"，自身无数据，
             只有子因子（kdj_k/kdj_d/kdj_j 等）才存储。
             判定：被 data_origin in batch_loadable 的子因子引用为 base_factor。

        Args:
            start_date: 训练起始日
            end_date: 训练结束日
            factor_ids: 待检查的因子 ID 列表

        Raises:
            ValueError: 若任一应检查因子在 [start_date, end_date] 范围内无数据
        """
        # 批量查询注册表元数据，按 data_origin 分组
        regs = await FacFactorRegistry.filter(factor_id__in=factor_ids)
        reg_map: dict[str, FacFactorRegistry] = {r.factor_id: r for r in regs}

        # 收集 SPI 虚拟父因子 ID：被 data_origin in batch_loadable 的子因子引用
        # 这类父因子是插件命名空间标识（如 kdj 被 kdj_k/kdj_d/kdj_j 共享），
        # 自身不在 fac_factor_value 中存储，只有子因子才存储。
        batch_loadable_base_factors: set[str] = {
            r.base_factor for r in reg_map.values()
            if r.base_factor and (r.data_origin or "computed") in _BATCH_LOADABLE_ORIGINS
        }

        # 收集需要检查的物理列 ID：
        #   - batch_loadable (computed/fund_flow/market) → 因子自身 ID
        check_factor_ids: list[str] = []
        skipped_factors: list[tuple[str, str]] = []  # (factor_id, reason)
        for fid in factor_ids:
            reg = reg_map.get(fid)
            if reg is None:
                skipped_factors.append((fid, "未在注册表"))
                continue
            # SPI 虚拟父因子：被 batch_loadable 子因子引用，自身无数据，跳过
            if fid in batch_loadable_base_factors:
                skipped_factors.append((fid, "SPI 虚拟父因子（子因子才存储数据）"))
                continue
            origin = reg.data_origin or "computed"
            if origin in _BATCH_LOADABLE_ORIGINS:
                check_factor_ids.append(fid)
            else:
                skipped_factors.append((fid, f"origin={origin}"))

        # 去重：derived 的 base_factor 可能本身也是 batch_loadable 因子
        check_factor_ids = list(dict.fromkeys(check_factor_ids))

        logger.info(
            "[feature_matrix] 数据完整性预检查: total=%d check=%d skip=%d range=%s~%s",
            len(factor_ids), len(check_factor_ids), len(skipped_factors),
            start_date, end_date,
        )

        missing_factor_ids: list[str] = []
        for fid in check_factor_ids:
            count = await FacFactorValue.count(
                factor_id=fid,
                pool_id="all",
                trade_date__gte=start_date,
                trade_date__lte=end_date,
            )
            if count == 0:
                missing_factor_ids.append(fid)
                logger.error(
                    "[feature_matrix] 因子 %s 在 %s~%s 范围内无数据",
                    fid, start_date, end_date,
                )

        if missing_factor_ids:
            raise ValueError(
                f"数据完整性检查失败：以下 {len(missing_factor_ids)} 个因子在 "
                f"{start_date}~{end_date} 范围内无数据，"
                f"请补充数据后再训练: {missing_factor_ids}"
            )

        if skipped_factors:
            logger.info(
                "[feature_matrix] 跳过非 fac_factor_value 因子（前 10 个）: %s",
                skipped_factors[:10],
            )

        logger.info(
            "[feature_matrix] 数据完整性检查通过: %d 个物理因子列均有数据 (跳过 %d 个非批量因子)",
            len(check_factor_ids), len(skipped_factors),
        )

    async def preload_all_data(
        self,
        start_date: date,
        end_date: date,
        pool_id: str,
        horizon: int = 5,
    ) -> dict[str, Any]:
        """训练前一次性预加载全期数据并完成截面预处理。

        将原本每个 fold 重复执行的 DB 查询和截面预处理集中到训练前一次完成，
        后续 walk-forward 各 fold 通过 build_dataset_from_cache 内存切片获取数据。

        预加载内容：
          1. 样本池标的列表（稳定，一次加载）
          2. 行业映射（稳定，一次加载）
          3. PIT 市值面板（全期，一次加载）
          4. PIT 成分过滤映射（全期，一次加载）
          5. 活跃因子列表（稳定，一次加载）
          6. 因子原始面板批量加载 + 五步截面预处理（全期，一次加载）
          7. 前向收益面板（全期含 horizon 延伸，一次加载）

        Args:
            start_date: 全期起始日（通常为训练最早窗口的 train_start）
            end_date: 全期结束日（通常为最后一个窗口的 test_end）
            pool_id: 样本池标识
            horizon: 前向收益 horizon（天数，与 walk_forward gap 对齐）

        Returns:
            预加载缓存字典，包含：
              - symbols: 标的列表
              - factor_ids: 因子 ID 列表
              - feature_matrix: 预处理后的特征矩阵 X（含 rank 变换）
              - feature_names: 因子名列表
              - membership: PIT 成分映射（用于切片过滤）
              - returns_panel: 前向收益面板
              - start_date / end_date: 全期范围
              - horizon: 前向收益周期
        """
        t0 = pd.Timestamp.now()
        logger.info(
            "[feature_matrix] === 全量预加载开始 === pool=%s range=%s~%s horizon=%d",
            pool_id, start_date, end_date, horizon,
        )

        # 1. 加载样本池标的 + 行业映射 + 市值面板（全期）
        symbols = await self.reader.load_pool_symbols(pool_id)
        if not symbols:
            logger.warning("[feature_matrix] pool=%s 无标的", pool_id)
            return {}

        industry_map = await self.reader.load_industry_map(symbols)
        # 市值面板按全期加载，后续切片复用
        market_cap_panel = await self.reader.load_market_cap_panel(
            symbols, start_date, end_date,
        )
        membership = await self.reader.build_pool_membership(
            pool_id, start_date, end_date,
        )

        # 2. 加载活跃因子 ID
        factor_ids = await self.load_active_factor_ids()
        if not factor_ids:
            logger.warning("[feature_matrix] 无可用活跃因子")
            return {}

        # 3. 批量预加载因子原始面板（全期，单因子不区分股池，统一使用 all 池）
        raw_panels = await fdl.preload_factor_raw_panels(
            start_date, end_date, factor_ids, symbols, "all",
        )

        # 4. 逐因子做截面预处理（复用 CrossSectionReader 五步管线，全期一次执行）
        processed_panels: dict[str, pd.DataFrame] = {}
        for fid in factor_ids:
            raw = raw_panels.get(fid)
            if raw is None or raw.empty:
                continue
            processed = self.reader.process_preloaded_factor_panel(
                raw, "all", fid, industry_map, market_cap_panel,
            )
            if not processed.empty:
                processed_panels[fid] = processed

        if not processed_panels:
            logger.warning("[feature_matrix] pool=%s 所有因子预处理后为空", pool_id)
            return {}

        # 5. 拼接为全期特征矩阵 X（MultiIndex: trade_date, symbol）
        feature_frames = []
        feature_names: list[str] = []
        for fid, panel in processed_panels.items():
            if fid not in panel.columns:
                continue
            feature_frames.append(panel[[fid]])
            feature_names.append(fid)

        x_full = pd.concat(feature_frames, axis=1) if feature_frames else pd.DataFrame()

        # PIT 成分过滤（避免生存者偏差）
        if not x_full.empty and membership:
            x_full = CrossSectionReader.filter_panel_by_membership(x_full, membership)

        # 5.5 截面 rank 变换（全期一次执行）：消除非线性/偏态/厚尾
        # rank 按 trade_date 分组，全期执行与分段执行结果完全等价
        if self.rank_transform and not x_full.empty:
            x_full = self._apply_cross_section_rank(x_full)

        # 6. 加载前向收益面板（全期含 horizon 延伸，确保 test_end 标签可用）
        returns_end = date.fromordinal(end_date.toordinal() + horizon)
        returns_panel = await self.reader.load_returns_panel(
            start_date, returns_end, symbols, horizons=(horizon,),
        )

        elapsed = (pd.Timestamp.now() - t0).total_seconds()
        logger.info(
            "[feature_matrix] === 全量预加载完成 === shape=%s features=%d "
            "symbols=%d range=%s~%s 耗时=%.1fs",
            x_full.shape, len(feature_names), len(symbols),
            start_date, end_date, elapsed,
        )

        return {
            "symbols": symbols,
            "factor_ids": factor_ids,
            "feature_matrix": x_full,
            "feature_names": feature_names,
            "membership": membership,
            "returns_panel": returns_panel,
            "start_date": start_date,
            "end_date": end_date,
            "horizon": horizon,
        }

    def build_dataset_from_cache(
        self,
        cache: dict[str, Any],
        window: WalkForwardWindow,
        segment: str = "train",
    ) -> tuple[pd.DataFrame, pd.Series, list[str]]:
        """从预加载缓存按 segment 切片构建数据集（无 DB 查询）。

        从 preload_all_data 产出的全期缓存中，按 segment 对应的日期范围切片，
        避免 walk-forward 每个 fold 重复执行 DB 查询和截面预处理。

        Args:
            cache: preload_all_data 返回的缓存字典
            window: Walk-forward 窗口
            segment: 窗口段（train/validate/test/predict）
                     - predict 段不返回标签（y 为空 Series）

        Returns:
            (X, y, feature_names)
            - X: DataFrame, MultiIndex(trade_date, symbol), columns=因子名
            - y: Series, MultiIndex(trade_date, symbol), 截面收益 rank
            - feature_names: 因子名列表
        """
        if segment == "train":
            start, end = window.train_start, window.train_end
        elif segment == "validate":
            start, end = window.validate_start, window.validate_end
        elif segment == "test":
            start, end = window.test_start, window.test_end
        elif segment == "predict":
            start, end = window.predict_start, window.predict_end
        else:
            raise ValueError(f"未知 segment: {segment}")

        x_full: pd.DataFrame = cache["feature_matrix"]
        feature_names: list[str] = cache["feature_names"]
        returns_panel: pd.DataFrame = cache["returns_panel"]
        horizon: int = cache["horizon"]

        if x_full.empty:
            return pd.DataFrame(), pd.Series(dtype=float), feature_names

        # 按日期范围切片（MultiIndex 第一级 trade_date）
        # 注意：x_full.index 的 trade_date 可能是 datetime64[ns]（DB 查询结果），
        # 而 window.train_start 等是 date 对象，需统一为 Timestamp 比较
        trade_dates = pd.to_datetime(x_full.index.get_level_values("trade_date"))
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        mask = (trade_dates >= start_ts) & (trade_dates <= end_ts)
        x = x_full.loc[mask].copy()

        # 构建标签 y
        if segment == "predict":
            y = pd.Series(dtype=float, name="label")
        else:
            if returns_panel.empty:
                y = pd.Series(dtype=float, name="label")
            else:
                ret_col = f"fwd_ret_{horizon}d"
                if ret_col not in returns_panel.columns:
                    logger.warning("[feature_matrix] 收益率面板缺列 %s", ret_col)
                    y = pd.Series(dtype=float, name="label")
                else:
                    ret_dates = pd.to_datetime(returns_panel.index.get_level_values("trade_date"))
                    ret_mask = (ret_dates >= start_ts) & (ret_dates <= end_ts)
                    ret_slice = returns_panel.loc[ret_mask, ret_col]
                    # 标签使用二分类（5日前向收益 > 0 = 1，否则 = 0）
                    # 设计依据：示例代码 CASE-机器学习因子挖掘
                    # 二分类信噪比高于回归，LightGBM 分类任务更稳定
                    y = (ret_slice > 0).astype(int).rename("label")

        # 对齐 x 和 y 的索引
        if not x.empty and not y.empty:
            common_idx = x.index.intersection(y.index)
            x = x.loc[common_idx]
            y = y.loc[common_idx]

        logger.info(
            "[feature_matrix] %s 切片完成: x.shape=%s y.shape=%s range=%s~%s",
            segment, x.shape, y.shape, start, end,
        )
        return x, y, feature_names

    async def build_dataset(
        self,
        window: WalkForwardWindow,
        pool_id: str,
        horizon: int = 5,
        segment: str = "train",
    ) -> tuple[pd.DataFrame, pd.Series, list[str]]:
        """构建 ML 数据集（特征矩阵 X + 标签 y）。

        Args:
            window: Walk-forward 窗口
            pool_id: 样本池标识
            horizon: 前向收益 horizon（天数，与 walk_forward gap 对齐）
            segment: 窗口段（train/validate/test/predict）
                     - predict 段不返回标签（y 为空 Series）

        Returns:
            (X, y, feature_names)
            - X: DataFrame, MultiIndex(trade_date, symbol), columns=因子名
            - y: Series, MultiIndex(trade_date, symbol), 截面收益 rank
            - feature_names: 因子名列表
        """
        if segment == "train":
            start, end = window.train_start, window.train_end
        elif segment == "validate":
            start, end = window.validate_start, window.validate_end
        elif segment == "test":
            start, end = window.test_start, window.test_end
        elif segment == "predict":
            start, end = window.predict_start, window.predict_end
        else:
            raise ValueError(f"未知 segment: {segment}")

        logger.info(
            "[feature_matrix] 构建 %s 数据集: pool=%s segment=%s range=%s~%s",
            pool_id, pool_id, segment, start, end,
        )

        # 1. 加载样本池标的 + 行业映射 + 市值面板
        symbols = await self.reader.load_pool_symbols(pool_id)
        if not symbols:
            logger.warning("[feature_matrix] pool=%s 无标的", pool_id)
            return pd.DataFrame(), pd.Series(dtype=float), []

        industry_map = await self.reader.load_industry_map(symbols)
        market_cap_panel = await self.reader.load_market_cap_panel(symbols, start, end)
        membership = await self.reader.build_pool_membership(pool_id, start, end)

        # 2. 加载活跃因子 ID
        factor_ids = await self.load_active_factor_ids()
        if not factor_ids:
            logger.warning("[feature_matrix] 无可用活跃因子")
            return pd.DataFrame(), pd.Series(dtype=float), []

        # 3. 批量预加载因子原始面板（单因子不区分股池，统一使用 all 池）
        raw_panels = await fdl.preload_factor_raw_panels(
            start, end, factor_ids, symbols, "all",
        )

        # 4. 逐因子做截面预处理（复用 CrossSectionReader 五步管线）
        processed_panels: dict[str, pd.DataFrame] = {}
        for fid in factor_ids:
            raw = raw_panels.get(fid)
            if raw is None or raw.empty:
                continue
            processed = self.reader.process_preloaded_factor_panel(
                raw, "all", fid, industry_map, market_cap_panel,
            )
            if not processed.empty:
                processed_panels[fid] = processed

        if not processed_panels:
            logger.warning("[feature_matrix] pool=%s 所有因子预处理后为空", pool_id)
            return pd.DataFrame(), pd.Series(dtype=float), []

        # 5. 拼接为特征矩阵 x（MultiIndex: trade_date, symbol）
        feature_frames = []
        feature_names: list[str] = []
        for fid, panel in processed_panels.items():
            if fid not in panel.columns:
                continue
            feature_frames.append(panel[[fid]])
            feature_names.append(fid)

        x = pd.concat(feature_frames, axis=1) if feature_frames else pd.DataFrame()

        # PIT 成分过滤（避免生存者偏差）
        if not x.empty and membership:
            x = CrossSectionReader.filter_panel_by_membership(x, membership)

        # 5.5 截面 rank 变换（可选）：消除非线性/偏态/厚尾
        if self.rank_transform and not x.empty:
            x = self._apply_cross_section_rank(x)

        # 6. 构建标签 y（predict 段不返回标签）
        if segment == "predict":
            y = pd.Series(dtype=float, name="label")
        else:
            # 加载前向收益面板（horizon+gap 天，确保窗口末日的标签可用）
            # 注意：窗口末日的 fwd_ret_h 需要未来 h 天的数据
            # test 段的标签需要 test_end + horizon 天的行情数据
            returns_start = start
            returns_end = date.fromordinal(end.toordinal() + horizon)
            returns_panel = await self.reader.load_returns_panel(
                returns_start, returns_end, symbols, horizons=(horizon,),
            )
            if returns_panel.empty:
                logger.warning("[feature_matrix] pool=%s 收益率面板为空", pool_id)
                y = pd.Series(dtype=float, name="label")
            else:
                ret_col = f"fwd_ret_{horizon}d"
                if ret_col not in returns_panel.columns:
                    logger.warning("[feature_matrix] 收益率面板缺列 %s", ret_col)
                    y = pd.Series(dtype=float, name="label")
                else:
                    # 标签使用二分类（5日前向收益 > 0 = 1，否则 = 0）
                    # 与 build_dataset_from_cache 保持一致
                    y = (returns_panel[ret_col] > 0).astype(int).rename("label")

        # 7. 对齐 x 和 y 的索引
        if not x.empty and not y.empty:
            common_idx = x.index.intersection(y.index)
            x = x.loc[common_idx]
            y = y.loc[common_idx]

        logger.info(
            "[feature_matrix] %s 数据集构建完成: x.shape=%s y.shape=%s features=%d",
            segment, x.shape, y.shape, len(feature_names),
        )
        return x, y, feature_names

    async def build_predict_features(
        self,
        predict_date: date,
        pool_id: str,
    ) -> tuple[pd.DataFrame, list[str]]:
        """构建实盘预测特征矩阵（单日，无标签）。

        用于 ml_predict 日频任务：加载 predict_date 当日的因子值，
        截面预处理后返回特征矩阵供模型推理。

        Args:
            predict_date: 预测日期
            pool_id: 样本池标识

        Returns:
            (X, feature_names)
        """
        logger.info(
            "[feature_matrix] 构建预测特征: pool=%s date=%s", pool_id, predict_date,
        )

        symbols = await self.reader.load_pool_symbols(pool_id)
        if not symbols:
            return pd.DataFrame(), []

        industry_map = await self.reader.load_industry_map(symbols)
        market_cap_panel = await self.reader.load_market_cap_panel(
            symbols, predict_date, predict_date,
        )
        membership = await self.reader.build_pool_membership(
            pool_id, predict_date, predict_date,
        )

        factor_ids = await self.load_active_factor_ids()
        if not factor_ids:
            return pd.DataFrame(), []

        raw_panels = await fdl.preload_factor_raw_panels(
            predict_date, predict_date, factor_ids, symbols, "all",
        )

        processed_panels: dict[str, pd.DataFrame] = {}
        for fid in factor_ids:
            raw = raw_panels.get(fid)
            if raw is None or raw.empty:
                continue
            processed = self.reader.process_preloaded_factor_panel(
                raw, "all", fid, industry_map, market_cap_panel,
            )
            if not processed.empty:
                processed_panels[fid] = processed

        if not processed_panels:
            return pd.DataFrame(), []

        feature_frames = []
        feature_names: list[str] = []
        for fid, panel in processed_panels.items():
            if fid not in panel.columns:
                continue
            feature_frames.append(panel[[fid]])
            feature_names.append(fid)

        x = pd.concat(feature_frames, axis=1) if feature_frames else pd.DataFrame()

        if not x.empty and membership:
            x = CrossSectionReader.filter_panel_by_membership(x, membership)

        # 截面 rank 变换（与训练保持一致）
        if self.rank_transform and not x.empty:
            x = self._apply_cross_section_rank(x)

        logger.info(
            "[feature_matrix] 预测特征构建完成: x.shape=%s features=%d",
            x.shape, len(feature_names),
        )
        return x, feature_names


def rank_ic(y_true: pd.Series, y_pred: np.ndarray) -> float:
    """计算 Rank IC（Spearman 秩相关）。

    用于 OOS 评估：y_true 为截面收益 rank，y_pred 为模型预测值。

    Args:
        y_true: 真实截面收益 rank（MultiIndex: trade_date, symbol）
        y_pred: 模型预测值（与 y_true 同长度对齐）

    Returns:
        Rank IC 值（-1 到 1），无效返回 NaN
    """
    from scipy.stats import spearmanr  # type: ignore[import-untyped]

    valid = np.isfinite(y_pred) & np.isfinite(y_true.values)
    if valid.sum() < 20:
        return float("nan")
    corr, _ = spearmanr(y_pred[valid], y_true.values[valid])
    return float(corr) if np.isfinite(corr) else float("nan")


def daily_rank_ic(y_true: pd.Series, y_pred: pd.Series) -> pd.Series:
    """计算每日截面 Rank IC 序列。

    Args:
        y_true: 真实截面收益 rank（MultiIndex: trade_date, symbol）
        y_pred: 模型预测值（MultiIndex: trade_date, symbol）

    Returns:
        Series indexed by trade_date, values = 当日截面 Spearman IC
    """
    from scipy.stats import spearmanr  # type: ignore[import-untyped]

    if y_true.empty or y_pred.empty:
        return pd.Series(dtype=float, name="daily_ic")

    # 对齐索引
    common = y_true.index.intersection(y_pred.index)
    if len(common) == 0:
        return pd.Series(dtype=float, name="daily_ic")

    y_true_aligned = y_true.loc[common]
    y_pred_aligned = y_pred.loc[common]

    # 用 groupby 代替 xs，避免日期类型不匹配导致 KeyError
    ic_records: list[tuple] = []
    # 合并为单 DataFrame 便于按日期分组
    combined = pd.DataFrame({"true": y_true_aligned, "pred": y_pred_aligned})
    for td, group in combined.groupby(level="trade_date"):
        true_vals = group["true"].values
        pred_vals = group["pred"].values

        valid = np.isfinite(true_vals) & np.isfinite(pred_vals)
        if valid.sum() < 20:
            continue

        corr, _ = spearmanr(true_vals[valid], pred_vals[valid])
        if np.isfinite(corr):
            ic_records.append((td, corr))

    if not ic_records:
        return pd.Series(dtype=float, name="daily_ic")
    return pd.Series(dict(ic_records), name="daily_ic").sort_index()
