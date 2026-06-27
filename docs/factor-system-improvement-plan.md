# xqtrader 因子系统审查与改进计划（个人版）

> **版本**: v1.1
> **创建**: 2026-06-26
> **更新**: 2026-06-27（T1–T10 代码落地，待全量重评验收）
> **范围**: `worker` 因子计算/评估/合成管线（`factor_compute` / `factor_evaluate` / `factor_synthesize` / `factor_quarterly`）及领域服务
> **依赖**: [factor-architecture.md](./factor-architecture.md)、[factor-catalog.md](./factor-catalog.md)
> **定位**: 基于一次架构审查，记录代码与文档偏差、对标业界的功能缺失，并给出分级实施计划

---

## 0. 结论速览

三任务分层架构（逐标的预计算 → 截面合成 → 截面评估）落地扎实，工程化质量高（按因子滚动、月度分片、增量水位、PIT 财务存储）。但存在 **1 个使评估体系失灵的单位 Bug**、**1 处文档核心链路（财务/估值 PIT 加载）未实现**，以及若干会系统性高估因子表现的方法学偏差。

| 严重度 | 数量 | 代表问题 |
|--------|------|----------|
| 🔴 P0 | 2 | 评级阈值单位 Bug；CrossSectionReader 未加载财务/估值因子 |
| 🟠 P1 | 3 | 市值/行业中性化前视偏差；样本池存活者偏差；评估/合成池范围不一致 |
| 🟡 P2 | 3 | 分层回测无成本；合成因子无法复评；多周期 IC/显著性/去冗余缺失 |
| ⚪ P3 | 1 | ICIR 全样本 vs 文档「滚动 252」口径不一致 |

### 实施状态（2026-06-27）

| 任务 | 状态 | 关键改动 |
|------|------|----------|
| T1 评级单位 Bug | ✅ 完成 | `grade_evaluator.py` 阈值改小数；`tests/factor/test_grade_evaluator.py` |
| T2 财务/估值 PIT 加载 | ✅ 完成 | 新建 `factor_data_loader.py`；`cross_section_reader.py` 按 `data_origin` 分流 |
| T3 PIT 市值中性化 | ✅ 完成 | `load_market_cap_panel` + 截面日 PIT 回归 |
| T4 PIT 成分/上市状态 | ✅ 完成 | `build_pool_membership` / `filter_panel_by_membership` |
| T5 样本池收敛 | ✅ 完成 | `pool_init.py` 默认 `all+idx_300` active；评估/合成任务启动时 `sync_default_pools` |
| T6 成本调整回测 | ✅ 完成 | `layered_backtest.py` 多空扣双边 0.3% |
| T7 合成因子复评 | ✅ 完成 | `factor_data_loader.load_from_factor_value` pool_id 优先回退 all |
| T8 多周期 IC + 显著性 | ✅ 完成 | 收益率面板扩展 5/10/20d；`ic_tstat/ic_pvalue/ic_mean_*d` 持久化；DDL 已执行 |
| T9 相关矩阵去冗余 | ✅ 完成 | 新建 `factor_dedup.py`；`alpha_synthesizer` 组内合成前去冗余 |
| T10 ICIR 滚动 252 | ✅ 完成 | `calc_ic_stats(ic_series, window=252)` 取末 window 日 |

**质量验收**：ruff ✅ · mypy（改动文件）✅ · pytest 9/9 ✅ · API `/api/v1/factors` 黑盒 ✅

**待运维验收**：触发一次 `factor.evaluate_weekly` 全量重评，验证 B 类因子 stats 与等级分布；合成任务验证去冗余日志。

---

## 1. 代码与文档偏差清单

### 1.1 文档承诺但未实现 / 不符

| 编号 | 文档结论 | 代码现状 | 影响 |
|------|---------|---------|------|
| D1 | §5 CrossSectionReader 加载估值(Z-score) + 财务(PIT 前向填充)，是评估/合成核心入口 | `load_single_factor_panel` 仅从 `fac_factor_value`(`pool_id='all'`) 读数，无财务 PIT / 估值分支 | B 类基本面 40 因子算出后无人读取，`factor_quarterly` 产出成断头数据 |
| D2 | §4.2 多空年化 A>10%/B>5%/C>3%；换手 <50%/<70% | `grade_evaluator` 用 `>10/5/3` 与 `<50/70` 比较小数值 | 评级实质失灵（见 2.1） |
| D3 | §4.1 IC「滚动 252 日」 | `calc_ic_series` 的 `window` 显式未使用，ICIR 取全样本 mean/std | ICIR 掩盖区制变化，语义不符 |
| D4 | §4.3 相关系数矩阵去冗余，组内保留 ICIR 最高者 | 完全缺失 | 文档承诺功能未落地 |
| D5 | §8 评估默认收敛至 `all + 1 目标池` | 评估全部 7 个 active 池；合成硬编码仅 `idx_300/idx_1000` | 评估/合成池范围不一致，未按文档收敛 |

---

## 2. 缺陷详情（按严重度）

### 2.1 🔴 P0 — 评级单位 Bug（评估输出不可用）

**位置**: `src/xqtrader/domain/factor/services/grade_evaluator.py`

```python
if icir > 1.0 and long_short_annual_ret > 10 and turnover < 50:  # A
if icir > 0.5 and long_short_annual_ret > 5  and turnover < 70:  # B
if icir > 0.3 and long_short_annual_ret > 3:                     # C
```

- `LayeredBacktester._calc_annual_ret` 返回**小数**（10% = `0.10`）；`calc_turnover` 返回 `[0,1]` 小数。
- `long_short_annual_ret > 10` 等价于要求**年化 > 1000%**，几乎永不可达 → A/B/C 拿不到。
- `turnover < 50` 因换手率恒 ≤1 而**恒为真** → 换手过滤失效。

**净效果**: 几乎所有因子被判 D 级 → `_resolve_pool_factors` 取不到 A/B 因子 → 合成退化到 top30 兜底 → 评估优选闭环失效。

**修复**: 阈值改为 `0.10/0.05/0.03` 与 `0.50/0.70`；补单测覆盖 A/B/C/D 边界。

### 2.2 🔴 P0 — CrossSectionReader 未加载财务/估值因子（D1）

**位置**: `src/xqtrader/domain/factor/services/cross_section_reader.py`

`load_single_factor_panel` → `_load_per_security_factors` 只查 `fac_factor_value`，无任何分支按 `ann_date` PIT 读 `fac_financial_factor_value`、按日读 `daily_indicator` 估值。导致 B 类基本面因子（目录最大类）从不进入评估/合成。

**修复**: 在 Reader 中按因子 `data_origin`/`compute_engine` 分流——财务因子走 PIT(`ann_date<=截面日` 取最新 + 应用层前向填充 + Z-score)，估值因子走 `daily_indicator` 直读 + Z-score，再合并入截面面板。

### 2.3 🟠 P1 — 市值/行业中性化前视与陈旧偏差

**位置**: `cross_section_reader.py::load_market_cap_map` / `_industry_market_cap_neutralize`

取每只票**最新一天**总市值，对**全部 5 年历史截面**用同一值做 `log(mv)` 回归；行业同为当前分类。属前视 + 陈旧。

**修复**: 按截面日取 PIT 市值（`daily_indicator.total_mv` 当日值）与 PIT 行业。

### 2.4 🟠 P1 — 样本池存活者偏差

**位置**: `cross_section_reader.py::load_pool_symbols`

用**当前** `IndexWeight` 成分（及当前 `list_status`、当前 ST 名）回溯 5 年，未用历史成分，系统性高估 IC/多空收益。

**修复**: 引入 PIT 成分（指数成分历史表按截面日取值）；`all` 池按截面日的上市状态过滤。

### 2.5 🟠 P1 — 评估/合成池范围不一致（D5）

评估跑 7 池、合成硬编码 2 池，且未按文档 §8 收敛。

**修复**: 统一池配置来源（样本池 `status` + 调度参数），默认 `all + 目标池`。

### 2.6 🟡 P2 — 分层回测无交易成本

**位置**: `layered_backtest.py`

Q5−Q1 等权次日收益、按 `(1+日均)^252` 年化，不计费率/印花税、不计换手成本，且算术复利偏乐观。与交易系统“换手成本决定性”相矛盾，会让高换手因子虚高。

**修复**: 引入双边成本参数，多空/分层收益扣成本后再评级。

### 2.7 🟡 P2 — 合成因子无法被复评

合成结果写 `pool_id=idx_300` 等，而 Reader 硬编码 `pool_id="all"` 读取，`composite_*` 因子下周期读不到、无反馈闭环。

**修复**: Reader 读取按传入 `pool_id` 优先、回退 `all`；合成因子纳入评估范围。

### 2.8 🟡 P2 — 评估维度单一

仅 1 日前向收益 IC，缺多周期 IC（5/10/20 日）、IC 显著性（t-stat/p-value、Newey-West）、相关矩阵去冗余（D4）。

### 2.9 ⚪ P3 — ICIR 口径与文档不一致（D3）

`window` 参数未用，ICIR 为全样本。需二选一对齐：实现滚动 252 或修订文档为全样本口径。

---

## 3. 对标业界平台的功能缺失（取舍清单）

口径参考 Barra CNE6 / WorldQuant / Qlib / 华泰金工。个人版按性价比分级，**非全做**。

| 维度 | 缺失项 | 个人版建议 |
|------|--------|-----------|
| 评估 | 多周期 IC（5/10/20d） | 建议补（匹配调仓周期） |
| 评估 | IC 显著性检验（t/p、Newey-West） | 建议补（轻量） |
| 评估 | 相关矩阵去冗余（文档已承诺） | 必补（D4） |
| 评估 | 成本调整后收益 | 必补（P2.6） |
| 评估 | 滚动 ICIR 时序/区制监控 | 可选 |
| 方法 | PIT 成分 + PIT 市值/行业 | 必补（P1） |
| 方法 | 因子间对称正交化 | 可选（组内等权已稀释共线） |
| 方法 | 纯因子组合 / Fama-MacBeth | 远期可选 |
| 合成 | ML 合成 / Stacking | 不做（文档已裁剪） |
| 存储 | 热温冷分层 / 7 态状态机 | 不做（文档已裁剪） |

---

## 4. 分级实施计划

> 每项遵循闭环：**设计 → 规划 → 实施 → 质量测试（mypy/ruff/逻辑自查 + 重启服务 API 黑盒）→ 验收 → 总结并更新文档**。

### 阶段一（P0，恢复评估可用性）— 优先立即执行

| 任务 | 内容 | 验收标准 |
|------|------|----------|
| T1 修复评级单位 Bug | `grade_evaluator` 阈值改小数 + 单测覆盖边界 | 已知样本能正确产出 A/B/C/D，非全 D |
| T2 CrossSectionReader 财务/估值加载 | 财务 PIT(ann_date) + 前向填充 + Z-score；估值 `daily_indicator` 直读 + Z-score | B 类因子可被评估，`fac_factor_stats` 出现基本面因子统计 |

### 阶段二（P1，消除偏差与不一致）

| 任务 | 内容 | 验收标准 |
|------|------|----------|
| T3 PIT 市值/行业中性化 | 中性化按截面日取 PIT 市值/行业 | 中性化输入随日期变化，无固定最新值 |
| T4 PIT 成分/上市状态 | 样本池按历史成分与当日上市状态取标的 | IC/多空较修复前回落（偏差消除的合理表现） |
| T5 评估/合成池统一收敛 | 默认 `all + 目标池`，统一配置来源 | 评估与合成池一致，可配置 |

### 阶段三（P2/P3，方法学增强）

| 任务 | 内容 | 验收标准 |
|------|------|----------|
| T6 成本调整回测 | 分层/多空扣双边成本后评级 | stats 含成本后收益字段 |
| T7 合成因子复评 | Reader 按 `pool_id` 读取；合成因子纳入评估 | `composite_*` 出现在 stats |
| T8 多周期 IC + 显著性 | 5/10/20d IC + t/p 值 | stats 新增多周期 IC 字段 |
| T9 相关矩阵去冗余 | 组内相关 >0.9 保留 ICIR 最高者 | 合成输入剔除冗余因子 |
| T10 ICIR 口径对齐 | 实现滚动 252 或修订文档 | 代码与文档一致 |

---

## 5. 风险与注意事项

- **T4 PIT 成分**依赖历史成分数据可得性；若数据源仅有当前成分，需先评估补数成本，否则降级为“仅 `all` 池 + 当日上市过滤”。
- **阶段一修复后**，历史 `fac_factor_stats` 等级口径变化，建议触发一次全量重评以刷新等级。
- 所有改动遵循项目规则：**禁止 fallback / 静默吞异常 / mock 数据 / 兼容双轨**；按推荐方案一次性改到位。
- 涉及改表结构（如新增 stats 字段、PIT 成分表）须用 db-tools 验证。

---

*本文档为因子系统改进的权威计划，落地后同步更新 [factor-architecture.md](./factor-architecture.md) 对应章节并归档本文件。*
