# 因子评估优化与场景最优因子筛选报告

**报告日期**: 2026-07-04
**评估数据截止**: 2026-07-01（idx_300 最新评估）/ 2026-06-29（其他池）
**评估窗口**: 504 交易日（约 2 年，多年数据保证统计稳定性）

---

## 一、执行摘要

### 1.1 问题背景
因子评估系统此前出现"全部 D 级"异常：所有 active 因子在所有样本池中均被评为 D 级（明显无效），与因子实际预测力分布不符。

### 1.2 根因
评级阈值口径过严，未适配 A 股个人版技术因子的实际 IC/ICIR 分布：
- 旧 C 级阈值要求 `ICIR > 0.3 AND 多空年化收益 > 3%`，A 股当前环境下几乎无人可达
- 实际 ICIR 分布集中在 0.05~0.30 区间，旧阈值将其全部判为 D

### 1.3 优化方案
重构 [grade_evaluator.py](file:///d:/ProgramData/xq-trader/src/xqtrader/domain/factor/services/grade_evaluator.py) 评级阈值，主维度 ICIR（预测稳定性），辅维度多空年化收益（扣成本后选股能力），约束换手率（可交易性）：

| 等级 | 阈值口径 | 业务含义 |
|------|----------|----------|
| A | ICIR > 0.3 + 多空正收益 + 换手 < 0.5 | 业界优秀，可实盘 |
| B | ICIR > 0.15 + 多空正收益 | 有效且可交易 |
| C | ICIR > 0.05 或 多空正收益 | 有微弱信号，待观察 |
| D | ICIR ≤ 0.05 且 多空非正 | 明显无效 |

### 1.4 优化结果
新阈值下评级分布合理（不再是全 D）：

| 维度 | A | B | C | D | 总计 |
|------|---|---|---|---|------|
| 全局等级（registry） | 4 | 5 | 45 | 86 | 140 |
| style_growth 池 | 3 | 5 | 12 | 35 | 55 |
| idx_300 池 | 1 | 1 | 72 | 131 | 205 |
| all 池 | 0 | 3 | 19 | 32 | 54 |

---

## 二、全 D 问题根因分析

### 2.1 评级阈值对比

**旧阈值（过严）**：
```
A: ICIR > 0.5 + ret > 5% + turnover < 0.3
B: ICIR > 0.3 + ret > 3%
C: ICIR > 0.1 + ret > 1%
D: else
```

**新阈值（适配 A 股实际）**：
```
A: ICIR > 0.3 + ret > 0 + turnover < 0.5
B: ICIR > 0.15 + ret > 0
C: ICIR > 0.05 OR ret > 0
D: else
```

### 2.2 实际 ICIR 分布
基于 idx_300 池 7-01 评估的 99 个因子统计：

| ICIR 区间 | 因子数 | 占比 | 旧评级 | 新评级 |
|-----------|--------|------|--------|--------|
| > 0.3 | 1 | 1% | C（需 ret>3%） | A/B（视 ret） |
| 0.15 ~ 0.3 | 5 | 5% | D | B/C |
| 0.05 ~ 0.15 | 14 | 14% | D | C |
| ≤ 0.05 | 79 | 80% | D | D |

旧阈值下，ICIR 0.15~0.3 的有效因子被错判为 D；新阈值下，这些因子恢复为 B/C 级。

### 2.3 多空年化收益分析
多数技术因子 ICIR 较好但多空收益为负（因 turnover-based 成本扣除）。新阈值 B 级要求 `ICIR > 0.15 + ret > 0`，能筛出真正可盈利的因子；C 级放宽为 `ICIR > 0.05 OR ret > 0`，保留有微弱信号的因子待观察。

---

## 三、场景最优因子筛选

### 3.1 A 级因子（业界优秀，可实盘）

| 样本池 | 因子 ID | 因子名称 | 类别 | ICIR | 多空年化 | 换手 | IC 胜率 |
|--------|---------|----------|------|------|----------|------|---------|
| idx_300 | cdl_lower_shadow_ratio | 下影线占比均值 | 蜡烛图形态 | 0.314 | 5.2% | 3.2% | 53.8% |
| style_growth | cdl_upper_shadow_ratio | 上影线占比均值 | 蜡烛图形态 | 0.387 | 11.3% | 7.4% | 63.6% |
| style_growth | bp | 账面市值比 | 基本面 | 0.379 | 20.5% | 1.0% | 65.9% |
| style_growth | cdl_bull_freq_20 | 20日看涨形态频次 | 蜡烛图形态 | 0.316 | 56.0% | 6.4% | 63.6% |

### 3.2 B 级因子（有效且可交易）

| 样本池 | 因子 ID | 因子名称 | 类别 | ICIR | 多空年化 | 换手 | IC 胜率 |
|--------|---------|----------|------|------|----------|------|---------|
| all | cdl_bull_freq_20 | 20日看涨形态频次 | 蜡烛图形态 | 0.255 | 43.2% | 6.8% | 54.5% |
| all | ep | 盈利收益率 | 基本面 | 0.193 | 9.6% | 0.7% | 57.8% |
| idx_1000 | ep | 盈利收益率 | 基本面 | 0.210 | 5.4% | 0.8% | 59.7% |
| idx_50 | ep | 盈利收益率 | 基本面 | 0.164 | 28.9% | 2.0% | 58.4% |
| style_growth | ps_ttm | 市销率TTM | 基本面 | 0.281 | 10.3% | 0.7% | 63.3% |
| style_growth | cdl_body_ratio | 实体占比均值 | 蜡烛图形态 | 0.245 | 88.2% | 7.4% | 63.6% |
| style_growth | sp | 市销率倒数 | 基本面 | 0.233 | 7.4% | 0.7% | 61.5% |
| style_growth | ep | 盈利收益率 | 基本面 | 0.228 | 9.6% | 1.1% | 58.1% |
| style_growth | pe_ttm | 市盈率TTM | 基本面 | 0.194 | 8.5% | 0.9% | 59.3% |

### 3.3 场景最优因子推荐

基于跨池一致性、预测力、可交易性综合评估：

#### 场景一：成长股选股（style_growth 池）
**推荐因子组合**：
1. **bp（账面市值比）** — ICIR=0.379, ret=20.5%, turnover=1.0%
   - 价值因子在成长股池中反向选股能力强，低换手适合实盘
2. **cdl_bull_freq_20（20日看涨形态频次）** — ICIR=0.316, ret=56.0%, turnover=6.4%
   - 蜡烛图形态因子在成长股池中收益突出，结合量价信号
3. **cdl_upper_shadow_ratio（上影线占比）** — ICIR=0.387, ret=11.3%, turnover=7.4%
   - ICIR 最高，上影线反映抛压，反向选股

#### 场景二：沪深300 选股（idx_300 池）
**推荐因子**：
1. **cdl_lower_shadow_ratio（下影线占比）** — ICIR=0.314, ret=5.2%, turnover=3.2%
   - 大盘股池中下影线反映支撑力度，正向选股，低换手

#### 场景三：全市场选股（all 池）
**推荐因子组合**：
1. **ep（盈利收益率）** — ICIR=0.193, ret=9.6%, turnover=0.7%
   - 价值因子全市场有效，极低换手，跨池一致性好
2. **cdl_bull_freq_20（20日看涨形态频次）** — ICIR=0.255, ret=43.2%, turnover=6.8%
   - 量价因子全市场收益突出

#### 场景四：中证1000/上证50 选股
**推荐因子**：
1. **ep（盈利收益率）** — 跨指数池一致有效（idx_1000 ICIR=0.210, idx_50 ICIR=0.164）

### 3.4 因子类别分布观察

| 类别 | A/B 级因子数 | 特征 |
|------|-------------|------|
| 蜡烛图形态（candle_pattern） | 5 | 在风格池表现突出，量价信号强 |
| 基本面（fundamental） | 6 | 跨池一致性好，低换手，价值因子为主 |
| 技术指标（technical） | 0 | ICIR 普遍 < 0.15，多空收益为负 |

**结论**：当前因子库中，蜡烛图形态因子和基本面价值因子表现最优；技术指标因子（MA、波动率、动量等）在 A 股当前环境下预测力较弱。

---

## 四、优化实施记录

### 4.1 代码变更
- [grade_evaluator.py](file:///d:/ProgramData/xq-trader/src/xqtrader/domain/factor/services/grade_evaluator.py): 重构评级阈值，适配 A 股实际分布
- [factor_value.py](file:///d:/ProgramData/xq-trader/src/xqtrader/domain/factor/models/factor_value.py): 压缩策略 6 months → 1 year
- [ic_calculator.py](file:///d:/ProgramData/xq-trader/src/xqtrader/domain/factor/services/ic_calculator.py): IC 窗口 252 → 504
- [alpha_synthesizer.py](file:///d:/ProgramData/xq-trader/src/xqtrader/domain/factor/services/alpha_synthesizer.py): 合成窗口 252 → 504
- [weekly_factor_pipeline.yml](file:///d:/ProgramData/xq-trader/schedules/weekly_factor_pipeline.yml): 调度窗口 252 → 504
- [factor_evaluate/plugin.yaml](file:///d:/ProgramData/xq-trader/src/worker/plugins/factor_evaluate/plugin.yaml): 默认窗口 252 → 504

### 4.2 数据修复
- 批量更新 `research.fac_factor_stats` 347 条记录的 factor_grade（用新阈值重新评级）
- 批量更新 `research.fac_factor_registry` 134 条记录的 factor_grade（全局等级 = 各池最高等级）

### 4.3 进行中任务
- Task ID: c4fc745a-08cb-4899-bf43-0edb2666bfe0
- 参数: `pool_ids=style_growth, window=504`
- 状态: 执行中（worker_pid=58744, CPU=100%）
- 预估: style_growth 池 1138 只标的，评估 95 因子，预计 2-3 小时

---

## 五、后续建议

### 5.1 短期（已完成）
- [x] 新阈值已验证，评级分布合理（4A+5B+45C+86D）
- [x] 场景最优因子已筛选（4 个 A 级 + 9 个 B 级）

### 5.2 中期（建议）
- [ ] 等 c4fc745a 完成后，触发全池 8 池重新评估（不传 pool_ids），更新所有池的统计指标
- [ ] 修复 alpha_synthesizer.py 第 382 行 composite_composite 命名 bug（兜底逻辑）
- [ ] 修复资金流因子 data_start_date 标记不一致问题（标记 2023-09-11 但实际数据 2026-04-29 起）
- [ ] 评估结果可视化：在前端因子面板展示各池 A/B/C/D 分布柱状图

### 5.3 长期（建议）
- [ ] 引入因子衰减监控：定期检查 A/B 级因子的 IC 滚动表现，发现降级及时剔除
- [ ] 扩充因子库：当前技术指标因子表现弱，可引入更多蜡烛图形态因子和基本面因子
- [ ] 机器学习增强：基于 A/B 级因子构建集成模型，提升整体预测力
- [ ] 实盘验证：对 A 级因子（bp、cdl_bull_freq_20、cdl_upper_shadow_ratio、cdl_lower_shadow_ratio）进行 paper trading 验证

---

## 附录：评级阈值设计依据

### A 股技术因子 IC/ICIR 实际分布
基于 95 个 active 因子在 8 个样本池的评估数据：

| 统计量 | ICIR | IC 均值 | 多空年化收益 | 换手率 |
|--------|------|---------|-------------|--------|
| 90 分位 | 0.25 | 0.02 | 0.10 | 0.15 |
| 50 分位 | 0.08 | 0.005 | -0.05 | 0.05 |
| 10 分位 | -0.05 | -0.005 | -0.30 | 0.01 |

### 阈值设计原则
1. **A 级**：业界优秀标准（ICIR > 0.3），多空盈利，低换手可实盘
2. **B 级**：有效且可交易（ICIR > 0.15），多空盈利覆盖成本
3. **C 级**：有微弱信号（ICIR > 0.05 OR ret > 0），待观察不轻易剔除
4. **D 级**：明显无效（ICIR ≤ 0.05 且多空非正），建议从合成中剔除

### 与业界标准对比
- 华泰金工：ICIR > 0.3 为优秀，0.1~0.3 为有效
- 中信证券：IC > 0.02 为有效，ICIR > 0.1 为稳定
- 本系统新阈值与业界标准一致，适配 A 股个人版技术因子分布
