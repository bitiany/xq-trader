# 机器学习量化平台架构设计

> 版本: v1.0 | 日期: 2026-07-07
> 硬件基准: RTX 5060Ti 16GB + 64GB DDR4/DDR5 内存
> 设计依据: AQR / Two Sigma / Renaissance / 幻方量化 / 微软 RD-Agent 业界实践

## 目录

1. [设计目标与边界](#1-设计目标与边界)
2. [硬件能力评估](#2-硬件能力评估)
3. [整体架构](#3-整体架构)
4. [Forward-Walk 持续学习机制](#4-forward-walk-持续学习机制)
5. [方案 A：截面 ML 因子组合](#5-方案-a截面-ml-因子组合)
6. [方案 B：LLM 因子挖掘](#6-方案-bllm-因子挖掘)
7. [方案 C：另类数据 LLM 因子](#7-方案-c另类数据-llm-因子)
8. [Celery 任务架构](#8-celery-任务架构)
9. [模型工件管理](#9-模型工件管理)
10. [API 服务层](#10-api-服务层)
11. [调度编排](#11-调度编排)
12. [与现有系统的边界](#12-与现有系统的边界)
13. [实施路线图](#13-实施路线图)
14. [风险与缓解](#14-风险与缓解)

---

## 1. 设计目标与边界

### 1.1 设计目标

- **截面 ML 因子组合**：用 LightGBM 学习多因子非线性组合，预测股票截面收益排序，OOS Rank IC 目标 0.05-0.10
- **LLM 因子挖掘**：参考微软 RD-Agent 模式，LLM 自动生成因子假设 → 代码 → 回测 → 反馈闭环
- **另类数据 LLM 因子**：对研报/新闻/舆情文本用 LLM 抽取情感因子，纳入 ML 组合
- **Forward-Walk 持续学习**：月频重训 + 日频推理，避免模型衰减与数据泄漏
- **训练-推理解耦**：训练任务产出模型工件，推理任务落表因子值，API 无状态消费

### 1.2 设计边界

| 范围 | 说明 |
|------|------|
| 不修改现有因子评估/合成管线 | ML 作为新合成方式并行存在，不影响 ICIR 加权合成 |
| 不修改 API 层 | ML 推理结果落 `fac_factor_value` 表后，现有 API 自动可见 |
| 不引入新的服务进程 | 复用现有 Celery Worker，新增 `ml` 队列 |
| 不修改 ORM 表结构 | 复用 `FacFactorRegistry` / `FacFactorValue` / `FacFactorStats` |

---

## 2. 硬件能力评估

### 2.1 硬件配置

| 组件 | 规格 | 关键参数 |
|------|------|---------|
| GPU | NVIDIA RTX 5060Ti | 16GB GDDR7, 4608 CUDA Cores, 144 Tensor Cores, Blackwell 架构 |
| 内存 | 64GB | DDR4/DDR5, 双通道 |
| 存储 | NVMe SSD | 假设 ≥1TB |
| CPU | 未明确 | 假设 8 核以上 |

### 2.2 任务适配性分析

#### 2.2.1 截面 ML 因子组合（方案 A）

| 资源 | 需求 | 硬件能力 | 评估 |
|------|------|---------|------|
| GPU 显存 | <1GB（LightGBM 默认 CPU） | 16GB | ✅ 远超需求 |
| 内存 | ~8-12GB（252日 × 5000标的 × 114因子 float32） | 64GB | ✅ 充足，可全量加载 |
| CPU | LightGBM 多线程训练 | 8+ 核 | ✅ 训练 5-15 分钟 |
| 存储 | 模型工件 <100MB/版本 | NVMe | ✅ 可保留 12+ 历史版本 |

**结论**：方案 A 完全在 CPU 上运行，GPU 不参与。LightGBM 树模型不适合 GPU 加速，64GB 内存可一次性加载全量因子面板，无需分块。

#### 2.2.2 LLM 因子挖掘（方案 B）

| 资源 | 需求 | 硬件能力 | 评估 |
|------|------|---------|------|
| GPU 显存 | 8-14GB（本地 7B/14B 模型推理） | 16GB | ⚠️ 可运行 7B 量化模型，14B 需 4bit 量化 |
| 内存 | ~16GB（模型加载 + 上下文） | 64GB | ✅ 充足 |
| 推理速度 | 7B Q4: 30-50 tok/s; 14B Q4: 15-25 tok/s | — | ⚠️ 单次因子假设生成 5-10 秒 |

**推荐方案**：
- **本地模型**：Qwen2.5-7B-Instruct（Q4 量化，显存 ~5GB）用于因子代码生成
- **远程 API**：DeepSeek-V3 / Claude Sonnet 用于复杂因子假设推演（[agent 默认配置](file:///d:/ProgramData/xq-trader/src/xqtrader/domain/agent)）
- **混合策略**：本地模型处理高频代码生成，远程 API 处理低频战略决策

#### 2.2.3 另类数据 LLM 因子（方案 C）

| 资源 | 需求 | 硬件能力 | 评估 |
|------|------|---------|------|
| GPU 显存 | 8-14GB（Embedding + 生成模型） | 16GB | ⚠️ 需分时复用 |
| 内存 | ~32GB（文本缓存 + 批处理） | 64GB | ✅ 充足 |
| 存储 | 新闻/研报文本 ~10GB/年 | NVMe | ✅ 充足 |
| 吞吐量 | 每日 ~5000 条新闻 × 200 token | — | ⚠️ 本地 7B 约 2-3 小时/日 |

**推荐方案**：
- **Embedding**：`bge-large-zh-v1.5`（本地 GPU，1024 维，1GB 显存）
- **情感抽取**：Qwen2.5-7B 量化（本地 GPU，批量调用）
- **复杂事件抽取**：DeepSeek-V3 API（成本控制，每日 ~5000 调用）
- **吞吐优化**：批量 prompt + 增量处理 + Redis 缓存

### 2.3 GPU 资源调度

由于三个方案共享单张 GPU，需分时复用：

```
每日时间线:
  18:00-18:15  方案 A 推理（CPU，不占 GPU）
  18:15-20:15  方案 C 另类数据因子抽取（GPU，2h）
  22:00-23:00  方案 A 训练（CPU，不占 GPU）
  23:00-23:30  方案 B LLM 因子挖掘（GPU，30min）

每月1日:
  22:00-23:00  方案 A 月频训练（CPU）
  23:00-23:30  方案 B 月频因子挖掘（GPU）
```

### 2.4 显存预算（峰值）

| 任务 | 模型 | 显存占用 | 时机 |
|------|------|---------|------|
| 方案 B 代码生成 | Qwen2.5-7B Q4 | ~5GB | 23:00-23:30 |
| 方案 C Embedding | bge-large-zh | ~1GB | 18:15-20:15 |
| 方案 C 情感抽取 | Qwen2.5-7B Q4 | ~5GB | 18:15-20:15 |
| 峰值同时占用 | — | ~6GB（不重叠） | — |

**结论**：16GB 显存足以支撑所有任务，无 OOM 风险。

---

## 3. 整体架构

### 3.1 分层架构

```
┌─────────────────────────────────────────────────────────────────┐
│  API 服务层（无状态，同步查询）                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 现有 /factors API 零修改                                  │    │
│  │ ML 因子作为普通因子注册到 FacFactorRegistry               │    │
│  │ 推理结果写入 FacFactorValue，API 直接查表                │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                           ▲
                           │ 因子值落表
┌─────────────────────────────────────────────────────────────────┐
│  推理层（Celery 日频任务）                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ ml_predict   │  │ llm_factor_  │  │ alternative_data_    │  │
│  │ _daily       │  │ extract_daily│  │ factor_daily         │  │
│  │              │  │              │  │                      │  │
│  │ 加载模型     │  │ LLM 因子     │  │ 新闻/研报/舆情        │  │
│  │ → 截面 rank  │  │ 计算         │  │ LLM 情感抽取          │  │
│  │ → 落表       │  │ → 落表       │  │ → 落表               │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                           ▲
                           │ 加载模型工件
┌─────────────────────────────────────────────────────────────────┐
│  训练层（Celery 月频任务）                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ ml_train_     │  │ llm_factor_  │  │ alternative_data_    │  │
│  │ monthly       │  │ discover_   │  │ train_monthly         │  │
│  │               │  │ monthly     │  │                      │  │
│  │ Walk-Forward │  │ RD-Agent    │  │ LLM 情感模型          │  │
│  │ LightGBM 训练│  │ 反馈循环    │  │ 微调/校准             │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                           ▲
                           │ 复用基础设施
┌─────────────────────────────────────────────────────────────────┐
│  现有基础设施层（零修改复用）                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ CrossSectionReader│  │ factor_data_     │  │ ic_calculator│  │
│  │ (五步预处理)      │  │ loader (批量加载) │  │ (IC/ICIR)   │  │
│  └──────────────────┘  └──────────────────┘  └──────────────┘  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ layered_backtest │  │ alpha_synthesizer │  │ FacFactor*   │  │
│  │ (分层回测)        │  │ (ICIR 合成 baseline)│  │ (ORM 表)    │  │
│  └──────────────────┘  └──────────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流

```
日频数据流:
  行情采集 → 因子计算 → ML 推理 → 因子值落表 → API 可见
                ↑                      ↓
                └─── 模型工件仓库 ─────┘

月频训练流:
  历史因子面板 → Walk-Forward 切分 → LightGBM 训练
                                      ↓
                                   OOS 评估 → 模型工件保存
                                      ↓
                                   因子注册表更新
```

---

## 4. Forward-Walk 持续学习机制

### 4.1 设计原则

| 原则 | 说明 |
|------|------|
| 无前瞻偏差 | 训练只用过去数据，Gap 防标签泄漏 |
| 滚动重训 | 月频重训模型，适应市场环境变化 |
| 样本外验证 | 训练/验证/测试三段切分 |
| PIT 成分过滤 | 使用时点股票池，避免生存者偏差 |
| OOS 评估 | 用样本外 IC / Sharpe 评估泛化能力 |

### 4.2 时间窗口划分

```
时间轴 ──────────────────────────────────────────────────────────▶
              ←── Train 252d ──→←Gap 5d→←Val 42d→←Gap 5d→←Test 42d→
                                                      ↑
                                                   当前日 T

每月滚动：T 每月前进 21 个交易日，重训模型
```

### 4.3 窗口参数

| 参数 | 值 | 依据 |
|------|-----|------|
| 训练窗 | 252 日（1年） | AQR/Two Sigma 默认 1-3 年，国内 A 股 1 年最优 |
| 验证窗 | 42 日（2月） | 用于早停和超参调优 |
| 测试窗 | 42 日（2月） | 样本外评估，不参与训练 |
| Gap | 5 日 | 与 `fwd_ret_5d` 标签 horizon 对齐，防泄漏 |
| 重训间隔 | 21 日（1月） | AQR 月频重训，平衡计算成本与新鲜度 |

### 4.4 Walk-Forward 引擎设计

**新建文件**：`src/xqtrader/domain/factor/services/walk_forward_engine.py`

```python
from datetime import date
from typing import NamedTuple

class WalkForwardWindow(NamedTuple):
    """单个 walk-forward 窗口"""
    train_start: date
    train_end: date
    validate_start: date       # = train_end + gap
    validate_end: date
    test_start: date           # = validate_end + gap
    test_end: date             # = test_start + test_window
    predict_start: date        # = test_end（用于实盘预测）
    predict_end: date


class WalkForwardConfig:
    train_window: int = 252    # 训练窗（交易日）
    val_window: int = 42       # 验证窗
    test_window: int = 42      # 测试窗
    gap: int = 5               # Gap（防泄漏，与标签 horizon 对齐）
    step: int = 21             # 滚动步长（月频）


class WalkForwardEngine:
    """Forward-walk 训练循环引擎（三方案共享）"""

    def __init__(self, config: WalkForwardConfig):
        self.config = config

    def generate_windows(
        self, start: date, end: date,
        trading_days: list[date],
    ) -> list[WalkForwardWindow]:
        """生成所有 walk-forward 窗口

        Args:
            start: 回测起始日
            end: 回测结束日
            trading_days: 交易日历（从 DB 加载）

        Returns:
            窗口列表，每个窗口包含 train/val/test/predict 四段
        """
        ...

    def run_fold(
        self,
        window: WalkForwardWindow,
        dataset_factory: Callable,    # 数据集构建（抽象接口）
        model_factory: Callable,      # 模型构建（抽象接口）
    ) -> FoldResult:
        """执行单次 walk-forward 折叠

        1. 加载训练/验证/测试数据（复用 CrossSectionReader）
        2. 训练模型（LightGBM / LLM）
        3. 验证集早停
        4. 测试集 OOS 评估
        5. 返回 OOS IC / OOS Sharpe / 预测值
        """
        ...
```

### 4.5 数据集构建（防泄漏）

```python
class MLDatasetBuilder:
    """ML 数据集构建器 — 复用现有基础设施"""

    async def build_train_dataset(
        self, window: WalkForwardWindow, pool_id: str,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """构建训练数据集

        1. 复用 factor_data_loader.preload_factor_raw_panels 加载因子面板
        2. 复用 CrossSectionReader.process_preloaded_factor_panel 五步预处理
        3. 复用 CrossSectionReader.load_returns_panel 加载未来收益
        4. 复用 CrossSectionReader.filter_panel_by_membership PIT 成分过滤
        5. 对齐因子矩阵 X 和标签 Y
        """
        ...

    def build_label(self, returns_panel: pd.DataFrame, horizon: int) -> pd.Series:
        """构建标签 — 截面收益 rank（非 good/bad 二分类）

        y = fwd_ret_5d.groupby(level="trade_date").rank(pct=True)
        y ∈ [0, 1]，1 = 当日收益最高的股票
        """
        ...
```

### 4.6 防泄漏机制

| 风险点 | 防护措施 |
|--------|---------|
| 标签泄漏 | 训练-测试 Gap = 5d（与 fwd_ret_5d 对齐） |
| 生存者偏差 | `CrossSectionReader.build_pool_membership` PIT 成分过滤 |
| 因子泄漏 | 因子计算只用 t 日及之前数据，收益用 t+5 日 |
| 时间泄漏 | 严格按日期切分，训练集最大日期 < 测试集最小日期 |
| 横截面泄漏 | 每日截面 rank 标签，避免跨日信息泄漏 |

---

## 5. 方案 A：截面 ML 因子组合

### 5.1 流程

```
┌─────────────────────────────────────────────────────────────┐
│  1. 因子加载（复用 factor_data_loader.preload_factor_raw_panels)│
│     → 100+ 因子 × (trade_date, symbol) 面板                  │
├─────────────────────────────────────────────────────────────┤
│  2. 截面预处理（复用 CrossSectionReader.process_preloaded_...）│
│     → MAD 去极值 → Z-score → 行业市值中性化 → 再 Z-score      │
├─────────────────────────────────────────────────────────────┤
│  3. 特征矩阵构建                                             │
│     X[t, s, f] = 因子 f 在 t 日股票 s 的预处理值              │
│     Y[t, s] = fwd_ret_5d 截面 rank（0-1 之间）              │
├─────────────────────────────────────────────────────────────┤
│  4. Walk-Forward 训练                                        │
│     for window in WalkForwardEngine.generate_windows():     │
│       model.fit(X[train], Y[train], eval_set=(X[val],...))   │
│       oos_pred = model.predict(X[test])                     │
│       oos_ic = spearmanr(oos_pred, Y[test])                │
├─────────────────────────────────────────────────────────────┤
│  5. 组合构建                                                 │
│     每日按 oos_pred 截面 rank 选 top_decile 构建组合          │
├─────────────────────────────────────────────────────────────┤
│  6. 回测评估（复用 layered_backtest + ic_calculator）         │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 标签设计

采用截面收益 rank 作为标签，而非绝对收益或二分类：

```python
y = fwd_ret_5d.groupby(level="trade_date").rank(pct=True)
# y ∈ [0, 1]，1 = 当日收益最高的股票
```

**设计依据**：
- 截面 rank 标签的分布稳定，避免标签漂移
- 直接对应截面选股目标（选 top 10% 股票）
- 与 IC 评估指标天然对齐（Spearman 秩相关）

### 5.3 特征工程

| 特征类别 | 来源 | 数量 | 说明 |
|---------|------|------|------|
| 基础因子 | `FacFactorRegistry` 中 `status='active'` 因子 | 100+ | 复用 `preload_factor_raw_panels` 批量加载 |
| 时序特征 | 因子的 5d/10d/20d 变化率 | 100+ | `factor_t / factor_t-5 - 1` |
| 截面特征 | 行业内 Z-score、市值分组 Z-score | — | 由 CrossSectionReader 预处理完成 |
| 行业代码 | 申万行业分类 | 1 | LightGBM `categorical_feature` |
| 市值因子 | log(总市值) | 1 | 作为中性化残差或特征 |

### 5.4 模型选择

**主模型：LightGBM**

| 配置项 | 值 | 说明 |
|--------|-----|------|
| objective | `regression` | 预测截面 rank |
| learning_rate | 0.02 | 慢学习防过拟合 |
| num_leaves | 15 | 限制复杂度 |
| max_depth | 4 | 浅树防过拟合 |
| min_child_samples | 30 | 叶子节点最小样本数 |
| feature_fraction | 0.7 | 特征采样比例 |
| bagging_fraction | 0.7 | 样本采样比例 |
| lambda_l1 | 0.1 | L1 正则化 |
| lambda_l2 | 1.0 | L2 正则化 |
| num_boost_round | 500 | 最大迭代次数 |
| early_stopping | 50 | 验证集早停 |

### 5.5 预期效果

| 指标 | 业界水平 | 预期值 |
|------|---------|--------|
| OOS Rank IC | 0.05-0.10 | 0.06-0.08 |
| 多空年化收益 | 15-25% | 10-20% |
| 多头年化超额 | 5-15% | 5-10% |
| 夏普比率 | 1.5-2.5 | 1.2-2.0 |

---

## 6. 方案 B：LLM 因子挖掘

### 6.1 流程（参考微软 RD-Agent）

```
┌──────────────────────────────────────────────────────────────┐
│  1. 基线评估                                                  │
│     现有因子库 → CrossSectionReader → ICCalculator            │
│     → 输出每个因子的 IC/ICIR/覆盖度/换手率                    │
├──────────────────────────────────────────────────────────────┤
│  2. LLM 假设生成                                             │
│     Prompt: "现有因子表现 + 市场知识 + 缺失维度"             │
│     → LLM 生成新因子假设（如"机构调研频率×市值因子"）         │
│     → 输出因子定义 + 计算公式 + 数据源                       │
├──────────────────────────────────────────────────────────────┤
│  3. 代码生成                                                 │
│     LLM 生成因子计算代码（Python）                           │
│     → 复用现有因子计算框架（SPI 机制 / 表达式引擎）           │
├──────────────────────────────────────────────────────────────┤
│  4. 隔离回测                                                 │
│     在 walk-forward 窗口内回测新因子                          │
│     → 复用 CrossSectionReader + ICCalculator                 │
├──────────────────────────────────────────────────────────────┤
│  5. 反馈循环                                                 │
│     IC > 0.05 且 ICIR > 0.3 → 加入因子库                    │
│     IC < 0 或换手率 > 0.4 → 反馈 LLM 失败原因                │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 LLM 模型选择

| 用途 | 模型 | 部署方式 | 显存 | 备注 |
|------|------|---------|------|------|
| 因子假设推演 | DeepSeek-V3 / Claude Sonnet | 远程 API | — | 复杂推理能力强 |
| 因子代码生成 | Qwen2.5-7B-Instruct | 本地 GPU（Q4 量化） | ~5GB | 代码生成质量足够 |
| 因子假设验证 | DeepSeek-V3 | 远程 API | — | 判断假设合理性 |

### 6.3 提示词模板

```python
FACTOR_DISCOVERY_PROMPT = """
你是量化因子研究员。现有因子库表现如下：
{existing_factors_ic_table}

市场知识：
- 当前市场环境：{market_state}
- 行业热点：{hot_sectors}
- 宏观经济：{macro_indicators}

可用数据源（sdc_* 表）：
- sdc_research_report: 研报评级、盈利预测、研报文本
- sdc_stock_news: 新闻、公告文本、关键词
- sdc_stock_sentiment: 舆情热度、情感分
- sdc_daily_indicator: PE/PB/PS/DV/换手率等
- sdc_fund_flow_individual: 资金流向
- sdc_financial_indicator: 财务指标（200+）

请生成 3 个新因子假设，要求：
1. 与现有因子相关性低（提供差异化 alpha）
2. 有经济学逻辑（不是数据挖掘）
3. 数据来源在现有表中
4. 输出格式：
   - factor_id: 因子标识
   - category: 因子分类（value/momentum/quality/...）
   - definition: 因子定义（文字描述）
   - formula: 计算公式（Python 表达式）
   - data_source: 数据源表
   - direction: DESC（因子值大→收益差）或 ASC（因子值大→收益好）
"""
```

### 6.4 代码生成约束

- 生成的代码必须符合现有 SPI 插件接口（`RulePlugin`）
- 或符合表达式引擎格式（`buy_expr`/`sell_expr` 字符串）
- 自动注入因子注册（`FacFactorRegistry`）
- 在沙箱环境执行，捕获异常并反馈 LLM

### 6.5 预期效果

参考微软 RD-Agent 实测：36 轮 loop，IC 提升 0.07。预期 10-20 轮 loop 可挖掘 3-5 个有效新因子。

---

## 7. 方案 C：另类数据 LLM 因子

### 7.1 数据源

| 数据源 | 表 | LLM 抽取内容 | 因子设计 |
|--------|-----|--------------|---------|
| 研报 | `sdc_research_report` | 评级变化、盈利预测调整、研报情绪 | `research_rating_chg`（评级上调）<br>`eps_forecast_chg`（盈利预测调整）<br>`research_sentiment`（研报情绪） |
| 新闻/公告 | `sdc_stock_news` | 新闻事件类型、情感倾向、关键词 | `news_event_factor`（事件类型）<br>`news_sentiment_5d`（5日新闻情绪）<br>`news_volume_spike`（新闻量异常） |
| 舆情 | `sdc_stock_sentiment` | 热度、情感分、关键词 | `heat_score_5d`（5日热度变化）<br>`sentiment_momentum`（情感动量）<br>`sentiment_divergence`（情感背离） |

### 7.2 流程

```
┌──────────────────────────────────────────────────────────────┐
│  1. 数据加载                                                 │
│     从 sdc_research_report / sdc_stock_news / sdc_stock_..  │
│     按日期+symbol 加载文本数据                               │
├──────────────────────────────────────────────────────────────┤
│  2. LLM 因子抽取                                             │
│     对每条记录调用 LLM 抽取结构化因子：                      │
│     - 情感分（-1 ~ 1）                                       │
│     - 事件类型（枚举）                                       │
│     - 关键词列表                                             │
│     - 信息强度（0-1）                                        │
├──────────────────────────────────────────────────────────────┤
│  3. 因子聚合（截面）                                         │
│     按日 + symbol 聚合为截面因子值                          │
│     - mean / sum / count / weighted_avg                     │
│     - 时间衰减加权（近期权重高）                            │
├──────────────────────────────────────────────────────────────┤
│  4. 截面预处理 + 评估                                        │
│     复用 CrossSectionReader + ICCalculator                  │
├──────────────────────────────────────────────────────────────┤
│  5. 纳入方案 A 的 ML 组合                                   │
│     作为新特征加入 LightGBM 训练                            │
└──────────────────────────────────────────────────────────────┘
```

### 7.3 LLM 调用优化（成本控制）

| 策略 | 说明 | 节省比例 |
|------|------|---------|
| 批量调用 | 一次处理多个 symbol 的多条新闻 | 70% |
| Redis 缓存 | 相同内容不重复调用 LLM | 50% |
| 增量处理 | 只处理新增数据，历史因子值缓存 | 90% |
| 分级调用 | 先用规则过滤，再对重要新闻调用 LLM | 60% |

### 7.4 因子设计示例

```python
# 研报评级变化因子
async def research_rating_change_factor(symbol: str, date: date) -> float:
    """过去30天内评级变化（升级=+1，降级=-1，首次=0.5）"""
    reports = await ResearchReport.filter(
        symbol=symbol, publish_date__gte=date-30, publish_date__lte=date
    )
    if not reports:
        return 0.0
    latest = max(reports, key=lambda r: r.publish_date)
    prev = [r for r in reports if r.id != latest.id]
    if not prev:
        return 0.5  # 首次覆盖
    prev_latest = max(prev, key=lambda r: r.publish_date)
    return rating_to_score(latest.rating) - rating_to_score(prev_latest.rating)

# 新闻情绪因子（LLM 抽取）
async def news_sentiment_factor(symbol: str, date: date) -> float:
    """过去5天新闻情绪加权平均"""
    news = await StockNews.filter(
        symbol=symbol,
        publish_time__gte=date-5, publish_time__lte=date,
    )
    if not news:
        return 0.0
    sentiments = [await llm_extract_sentiment(n.content) for n in news]  # 缓存
    weights = [decay_weight(n.publish_time, date) for n in news]
    return float(np.average(sentiments, weights=weights))
```

---

## 8. Celery 任务架构

### 8.1 新增队列配置

**修改** `src/worker/celery_app.py`（新增 `ml` 队列路由）：

```python
task_routes={
    "market.*": {"queue": "market"},
    "factor.*": {"queue": "factor"},
    "ml.*": {"queue": "ml"},        # 新增 ML 队列
    "llm.*": {"queue": "ml"},       # LLM 任务复用 ml 队列
},
```

**Worker 启动参数**（追加 `ml` 队列）：

```bash
celery -A worker.celery_entry worker -c 4 -P threads -Q celery,factor,market,ml
```

### 8.2 任务清单

| 任务名 | 频率 | 队列 | 耗时 | 资源 | 说明 |
|--------|------|------|------|------|------|
| `ml.train_monthly` | 月频（每月1日 22:00） | `ml` | 30-60min | CPU | Walk-Forward 训练 |
| `ml.predict_daily` | 日频（盘后 18:10） | `ml` | 3-5min | CPU | 加载模型推理，落表 |
| `llm.factor_discover_monthly` | 月频（每月1日 23:00） | `ml` | 30min | GPU | LLM 因子挖掘 |
| `llm.alternative_data_factor_daily` | 日频（盘后 18:15） | `ml` | 2h | GPU | 另类数据因子抽取 |

### 8.3 训练任务设计

**新建** `src/worker/plugins/ml_train/`：

```
src/worker/plugins/ml_train/
├── __init__.py
├── plugin.yaml      # 任务配置
└── task.py          # 任务实现
```

**plugin.yaml**：

```yaml
name: ml_train
queue: ml
time_limit: 7200
max_retries: 2
prevent_concurrent: true
schedule:
  cron: "0 22 1 * *"    # 每月1日 22:00
```

**task.py**：

```python
class MLTrainTask(BaseTask):
    task_name = "ml.train_monthly"
    description = "Walk-Forward ML 因子组合模型训练"
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        pool_ids = parse_list_param(kwargs.get("pool_ids"))
        train_window = int(kwargs.get("train_window", 252))
        horizon = int(kwargs.get("horizon", 5))

        # 1. 初始化组件
        engine = WalkForwardEngine(WalkForwardConfig(train_window=train_window))
        combiner = MLCombiner()

        # 2. 生成 walk-forward 窗口
        trading_days = await self._load_trading_days(start, end)
        windows = engine.generate_windows(start, end, trading_days)

        # 3. 逐折训练
        fold_results = []
        for i, window in enumerate(windows, 1):
            logger.info("[ml.train] >>> 折叠 %d/%d train=%s~%s",
                        i, len(windows), window.train_start, window.train_end)

            # 构建数据集（复用 CrossSectionReader）
            X_train, y_train = await dataset_builder.build_train_dataset(window, pool_id)
            X_val, y_val = await dataset_builder.build_val_dataset(window, pool_id)
            X_test, y_test = await dataset_builder.build_test_dataset(window, pool_id)

            # 训练
            model = combiner.train(X_train, y_train, X_val, y_val)

            # OOS 评估
            oos_pred = model.predict(X_test)
            oos_ic = spearmanr(oos_pred, y_test)[0]
            oos_sharpe = calc_sharpe(oos_pred, y_test)

            fold_results.append({
                "fold": i, "window": window._asdict(),
                "oos_ic": oos_ic, "oos_sharpe": oos_sharpe,
            })
            logger.info("[ml.train] <<< 折叠 %d OOS IC=%.4f Sharpe=%.2f",
                        i, oos_ic, oos_sharpe)

        # 4. 最终模型用最近窗口训练并保存
        latest_window = windows[-1]
        final_model = combiner.train(X_train, y_train, X_val, y_val)

        # 5. 保存模型工件
        version = date.today().isoformat()
        model_path = self._save_model_artifact(final_model, version, fold_results)

        # 6. 注册 ML 因子
        await self._register_ml_factor(pool_id, version, fold_results)

        return {
            "version": version,
            "model_path": str(model_path),
            "avg_oos_ic": np.mean([r["oos_ic"] for r in fold_results]),
            "avg_oos_sharpe": np.mean([r["oos_sharpe"] for r in fold_results]),
        }
```

### 8.4 推理任务设计

**新建** `src/worker/plugins/ml_predict/`：

```python
class MLPredictTask(BaseTask):
    task_name = "ml.predict_daily"
    description = "日频 ML 因子推理 → 落表 FacFactorValue"

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        # 1. 加载 latest 模型
        model_path = self._get_latest_model_path()
        model = lgb.Booster(model_file=str(model_path / "model.lgb"))

        # 2. 加载当日因子面板（复用 factor_data_loader）
        trade_date = kwargs.get("trade_date", date.today())
        factor_panels = await self._load_factor_panels(trade_date)

        # 3. 截面预处理（复用 CrossSectionReader）
        processed_panels = await self._preprocess_factors(factor_panels)

        # 4. 构建特征矩阵
        X = self._build_feature_matrix(processed_panels)

        # 5. 推理 → 截面 rank
        pred = model.predict(X)
        pred_rank = pd.Series(pred).rank(pct=True)

        # 6. 落表 FacFactorValue
        rows = [
            FacFactorValue(
                symbol=symbol,
                trade_date=trade_date,
                factor_id="ml_alpha_v1",
                pool_id=pool_id,
                factor_value=float(rank),
            )
            for symbol, rank in pred_rank.items()
        ]
        total = await FacFactorValue.bulk_create_or_update(
            rows,
            on_conflict=["symbol", "trade_date", "factor_id", "pool_id"],
            update_fields=["factor_value"],
        )
        logger.info("[ml.predict] 落表 %d 条因子值", total)
        return {"trade_date": str(trade_date), "count": total}
```

---

## 9. 模型工件管理

### 9.1 存储结构

```
storage/
└── models/
    └── ml_combiner/
        ├── 2026-07-07/              # 月频版本
        │   ├── model.lgb            # LightGBM 模型
        │   ├── metadata.json        # 训练元数据
        │   ├── feature_importance.json
        │   ├── oos_metrics.json     # OOS IC/Sharpe
        │   └── config.yaml          # 训练配置（可复现）
        ├── 2026-06-07/
        └── latest -> 2026-07-07     # 符号链接（Windows 用 junction）
```

### 9.2 metadata.json 内容

```json
{
  "model_version": "2026-07-07",
  "trained_at": "2026-07-07T22:00:00",
  "train_window": ["2025-07-07", "2026-07-01"],
  "val_window": ["2026-07-02", "2026-07-07"],
  "test_window": ["2026-07-08", "2026-07-14"],
  "oos_rank_ic": 0.0723,
  "oos_sharpe": 1.85,
  "feature_count": 114,
  "sample_count": 28512,
  "hyperparameters": {
    "num_leaves": 15,
    "max_depth": 4,
    "learning_rate": 0.02
  },
  "factor_id": "ml_alpha_v1",
  "fold_results": [
    {"fold": 1, "oos_ic": 0.068, "oos_sharpe": 1.72},
    {"fold": 2, "oos_ic": 0.075, "oos_sharpe": 1.91}
  ]
}
```

### 9.3 版本管理

- **保留策略**：保留最近 12 个月版本
- **回滚机制**：通过更新 `latest` 符号链接指向历史版本
- **A/B 测试**：同时部署两个版本（`ml_alpha_v1` / `ml_alpha_v2`），对比 OOS 表现

---

## 10. API 服务层

### 10.1 现有 API 零修改

ML 推理结果写入 `FacFactorValue` 表后，以下 API 端点**自动可见**：

| API 端点 | 行为 |
|---------|------|
| `GET /factors` | 列出因子，包含 `ml_alpha_v1` |
| `GET /factors/ml_alpha_v1/values` | 查询 ML 因子值 |
| `GET /factors/ml_alpha_v1/stats` | 查询 ML 因子统计（IC/ICIR） |
| `GET /factors/series/{symbol}` | 个股因子时序，包含 ML 因子 |

### 10.2 因子注册

训练成功后，自动注册到 `FacFactorRegistry`：

```python
await FacFactorRegistry.update_or_create(
    factor_id="ml_alpha_v1",
    defaults={
        "category": "composite_ml",
        "data_origin": "ml_combiner",
        "composite_method": "ml",          # 使用已预留的枚举值
        "update_freq": "daily",
        "status": "active",
        "factor_grade": "A",               # 根据 OOS IC 评定
        "data_start_date": train_end_date,
    },
)
```

### 10.3 新增 API（可选）

如需查询模型元数据和版本信息，可新增端点：

```
GET /ml/models                     # 列出所有模型版本
GET /ml/models/latest              # 获取最新模型元数据
GET /ml/models/{version}/metrics   # 查询特定版本的 OOS 指标
```

---

## 11. 调度编排

### 11.1 日频流水线

**修改** `schedules/daily_pipeline.yml`：

```yaml
name: daily_pipeline
mode: canvas
steps:
  - name: daily_incremental
    task: daily.incremental
  - name: factor_compute
    task: factor.compute_daily
    depends_on: [daily_incremental]
  - name: ml_predict
    task: ml.predict_daily
    depends_on: [factor_compute]        # 因子计算完成后推理
  - name: llm_alternative_data_factor
    task: llm.alternative_data_factor_daily
    depends_on: [daily_incremental]      # 与 ml_predict 并行
```

### 11.2 月频训练调度

**新建** `schedules/monthly_ml_train.yml`：

```yaml
name: monthly_ml_train
mode: canvas
schedule:
  cron: "0 22 1 * *"    # 每月1日 22:00
steps:
  - name: ml_train
    task: ml.train_monthly
    args:
      train_window: 252
      horizon: 5
  - name: llm_factor_discover
    task: llm.factor_discover_monthly
    depends_on: [ml_train]
```

### 11.3 周频评估调度

ML 因子作为普通因子参与周频评估，**无需修改** `weekly_factor_pipeline.yml`：

```yaml
steps:
  - name: factor_evaluate
    task: factor.evaluate_weekly
    # ML 因子自动被评估
  - name: alpha_synthesize
    task: factor.synthesize_weekly
    depends_on: [factor_evaluate]
```

### 11.4 调度时间线

```
每日:
  18:00  daily_incremental          (行情采集)
  18:05  factor_compute_daily       (因子计算, 5-10min)
  18:10  ml_predict_daily           (ML推理, 3-5min, CPU)
  18:15  llm.alternative_data_factor_daily  (另类数据, 2h, GPU)
  → 推理结果落表，API 可见

每月1日:
  22:00  ml.train_monthly           (Walk-Forward训练, 30-60min, CPU)
  23:00  llm.factor_discover_monthly (LLM因子挖掘, 30min, GPU)
  → 保存新模型版本，更新 latest 链接
  → 下个交易日 ml.predict_daily 自动使用新模型

每周日:
  22:00  factor_evaluate_weekly     (因子评估, 含 ML 因子)
  22:30  factor.synthesize_weekly   (ICIR 合成, 含 ML 因子)
```

---

## 12. 与现有系统的边界

### 12.1 复用清单

| 现有组件 | 复用方式 | 修改情况 |
|---------|---------|---------|
| `CrossSectionReader` | 直接调用 `process_preloaded_factor_panel` | ❌ 不修改 |
| `factor_data_loader` | 直接调用 `preload_factor_raw_panels` | ❌ 不修改 |
| `ICCalculator` | 直接调用 `calc_all_ic_series` | ❌ 不修改 |
| `AlphaSynthesizer` | 作为 baseline 对比 | ❌ 不修改 |
| `FacFactorRegistry` | 插入 ML 因子记录 | ❌ 不修改（仅插入） |
| `FacFactorValue` | 推理结果落表 | ❌ 不修改（仅插入） |
| `FacFactorStats` | ML 因子评估统计 | ❌ 不修改（仅插入） |
| `layered_backtest` | ML 因子分层回测 | ❌ 不修改 |
| `BaseTask` | ML 任务继承 | ❌ 不修改 |
| `plugin.yaml` 机制 | 自动发现注册 | ❌ 不修改 |

### 12.2 修改清单

| 文件 | 修改内容 | 改动量 |
|------|---------|--------|
| `src/worker/celery_app.py` | 新增 `ml` 队列路由 | 1 行 |
| `src/worker/celery_entry.py` | Worker 启动追加 `-Q ml` | 1 行 |
| `schedules/daily_pipeline.yml` | 串联 `ml_predict` 步骤 | 3 行 |
| `requirements.txt` | 新增 `lightgbm` 依赖 | 1 行 |

### 12.3 新建清单

| 文件 | 说明 |
|------|------|
| `src/xqtrader/domain/factor/services/walk_forward_engine.py` | Forward-walk 引擎 |
| `src/xqtrader/domain/factor/services/ml_combiner.py` | LightGBM 训练器 |
| `src/xqtrader/domain/factor/services/feature_matrix_builder.py` | 特征矩阵构建 |
| `src/xqtrader/domain/factor/services/llm_factor_discoverer.py` | LLM 因子挖掘 |
| `src/xqtrader/domain/factor/services/alternative_data_factorizer.py` | 另类数据因子化 |
| `src/xqtrader/domain/factor/services/llm_sentiment_extractor.py` | LLM 情感抽取 |
| `src/worker/plugins/ml_train/task.py` | 训练任务（月频） |
| `src/worker/plugins/ml_predict/task.py` | 推理任务（日频） |
| `src/worker/plugins/llm_factor_discover/task.py` | LLM 因子挖掘任务（月频） |
| `src/worker/plugins/alternative_data_factor/task.py` | 另类数据因子任务（日频） |
| `schedules/monthly_ml_train.yml` | 月频训练编排 |

### 12.4 新增依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| `lightgbm` | ≥4.0 | 截面 ML 因子组合 |
| `openai` | ≥1.0 | LLM API 调用（方案 B/C） |
| `tenacity` | ≥8.0 | LLM 调用重试 |
| `transformers` | ≥4.40 | 本地 LLM 推理（方案 B/C） |
| `accelerate` | ≥0.20 | 模型加载加速 |
| `bitsandbytes` | ≥0.41 | 4bit 量化（节省显存） |

---

## 13. 实施路线图

### 13.1 阶段 1：Forward-Walk 引擎 + 方案 A 基线（2-3 周）

**交付物**：
- `walk_forward_engine.py` — Forward-walk 训练循环引擎
- `feature_matrix_builder.py` — 多因子特征矩阵构建
- `ml_combiner.py` — LightGBM 截面组合训练器
- `ml_train` 任务 — 月频训练
- `ml_predict` 任务 — 日频推理
- 端到端验证脚本（沪深300 测试）

**验收标准**：
- Walk-forward 引擎正确切分窗口，无数据泄漏
- OOS Rank IC ≥ 0.05
- 多空年化收益 ≥ 10%
- 与现有 ICIR 加权合成（`AlphaSynthesizer`）对比有提升

### 13.2 阶段 2：LLM 因子挖掘（方案 B）（2-3 周）

**交付物**：
- `llm_factor_discoverer.py` — LLM 因子假设生成
- `factor_code_generator.py` — 因子代码自动生成
- `llm_factor_discover` 任务 — 月频挖掘
- 反馈循环验证

**验收标准**：
- LLM 因子挖掘闭环跑通
- 挖掘 3-5 个新因子，IC > 0.05
- 新因子纳入 ML 组合后 OOS IC 提升

### 13.3 阶段 3：另类数据 LLM 因子（方案 C）（3-4 周）

**交付物**：
- `alternative_data_factorizer.py` — 另类数据因子化
- `llm_sentiment_extractor.py` — LLM 情感抽取
- `alternative_data_factor` 任务 — 日频因子抽取
- 3 类另类数据因子（研报/新闻/舆情）

**验收标准**：
- 3 类另类数据因子入库
- 纳入 ML 组合后 OOS IC 提升 ≥ 0.01
- LLM 调用成本可控（每日 < 5000 次远程 API 调用）

---

## 14. 风险与缓解

### 14.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| ML 模型过拟合 | 高 | OOS IC 衰减 | Walk-forward + Gap + 正则化（L1/L2 + max_depth ≤ 5） |
| 因子衰减 | 中 | 模型失效 | 月频重训 + IC 衰减监控（半衰期 < 30d 触发预警） |
| LLM 幻觉 | 中 | 因子代码错误 | 沙箱执行 + 因子 IC 验证后才入库 |
| LLM 成本超支 | 中 | 任务中断 | 缓存 + 批量 + 分级调用 + 月度预算监控 |
| 数据泄漏 | 高 | 模型评估失真 | PIT 成分过滤 + Gap 机制 + 严格时间切分 |
| GPU 显存不足 | 低 | 任务失败 | Q4 量化 + 分批处理 + 显存监控 |

### 14.2 业务风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| ML 因子与现有因子相关性高 | 中 | 增量 alpha 有限 | 因子去冗余（`factor_dedup`，相关系数 > 0.9 去除） |
| 市场环境变化 | 高 | 模型失效 | Walk-forward 滚动重训 + 人工干预开关 |
| LLM 生成的因子无经济学逻辑 | 中 | 因子不可解释 | LLM 提示词约束 + 人工审核 + 因子注册时填写 `definition` |

### 14.3 监控指标

| 指标 | 阈值 | 告警动作 |
|------|------|---------|
| OOS Rank IC | < 0.03 | 触发模型重训 |
| OOS Rank IC | < 0.01 | 暂停 ML 因子使用，回滚到 ICIR 合成 |
| IC 衰减半衰期 | < 30d | 触发因子新鲜度预警 |
| LLM 调用失败率 | > 10% | 切换到备用 LLM API |
| 训练任务耗时 | > 90min | 优化数据加载或降低样本量 |
| GPU 显存占用 | > 14GB | 减小批处理大小 |

---

## 附录 A：业界参考

| 机构 | 方案 | 参考 |
|------|------|------|
| AQR | ML 增强传统因子 | [AQR Machine Learning](https://www.aqr.com/Insights/Research/Journal-Article/Machine-Learning-and-Alternative-Data) |
| Two Sigma | 另类数据 + 非线性关系 | [Two Sigma ML Framework](https://www.twosigma.com/articles/a-framework-for-machine-learning-at-scale/) |
| Renaissance | LLM 分析电话会议 | 大奖章基金 2025 年新增 AI 因子 |
| 幻方量化 | 200+ 因子 + 遗传算法筛选 | 2025 年 +56.55% 收益 |
| 微软 RD-Agent | LLM 自动化因子挖掘 | 36 轮 loop，IC 提升 0.07 |

## 附录 B：硬件配置参考

| 组件 | 规格 | 用途 |
|------|------|------|
| GPU | NVIDIA RTX 5060Ti 16GB | LLM 推理（方案 B/C） |
| 内存 | 64GB | 因子面板全量加载（方案 A） |
| 存储 | NVMe SSD ≥1TB | 模型工件 + 文本数据缓存 |
| CPU | 8 核+ | LightGBM 多线程训练 |

## 附录 C：参数调优指南

### C.1 Walk-Forward 参数

| 参数 | 默认值 | 调优范围 | 说明 |
|------|--------|---------|------|
| `train_window` | 252 | 126/252/504 | 短窗反应快但噪声大 |
| `val_window` | 42 | 21/42/63 | 验证集大小 |
| `test_window` | 42 | 21/42/63 | 测试集大小 |
| `gap` | 5 | 1/5/10 | 与标签 horizon 对齐 |
| `step` | 21 | 5/21/63 | 重训频率 |

### C.2 LightGBM 参数

| 参数 | 默认值 | 调优范围 | 说明 |
|------|--------|---------|------|
| `learning_rate` | 0.02 | 0.01-0.1 | 慢学习防过拟合 |
| `num_leaves` | 15 | 7-63 | 限制复杂度 |
| `max_depth` | 4 | 3-6 | 浅树防过拟合 |
| `min_child_samples` | 30 | 10-100 | 叶子节点最小样本数 |
| `feature_fraction` | 0.7 | 0.5-1.0 | 特征采样比例 |
| `bagging_fraction` | 0.7 | 0.5-1.0 | 样本采样比例 |
| `lambda_l1` | 0.1 | 0-1.0 | L1 正则化 |
| `lambda_l2` | 1.0 | 0-10 | L2 正则化 |

### C.3 LLM 参数

| 参数 | 默认值 | 调优范围 | 说明 |
|------|--------|---------|------|
| 本地模型 | Qwen2.5-7B Q4 | 7B/14B | 显存限制 |
| 远程 API | DeepSeek-V3 | Claude/GPT-4 | 复杂推理 |
| 批量大小 | 8 | 4-16 | 显存与吞吐平衡 |
| 最大 token | 2048 | 1024-4096 | 代码生成长度 |
| 温度 | 0.7 | 0.3-1.0 | 创造性 vs 确定性 |
