# xqtrader 因子规格目录

> **版本**: v7.2  
> **更新**: 2026-07-07  
> **关联**: [factor-system-design.md](./factor-system-design.md)（系统架构）  
> **参考**: Barra CNE6 (MSCI) / WorldQuant Alpha101 / Qlib Alpha158 (Microsoft) / 华泰金工

---

## 一、元数据规格

每个因子在 `FactorDefinition` 中声明以下字段（详见系统设计 §3.3）：

| 字段 | 必填 | 说明 |
|------|------|------|
| `factor_id` | ✅ | 全局唯一标识 |
| `display_name` | ✅ | 展示名 |
| `category` | ✅ | 分类（momentum/tech_trend/...） |
| `direction` | ✅ | DESC / ASC |
| `compute_mode` | ✅ | precomputed / on_demand |
| `density` | ✅ | dense / sparse / discrete |
| `usage` | ✅ | cross_section / time_series / both |
| `preprocess_policy` | ✅ | cross_section_standard / raw |
| `update_freq` | ✅ | daily / weekly / quarterly |
| `compute_engine` | ✅ | plugin / synthesize / cross_section |
| `data_origin` | ✅ | computed / daily_indicator / fina_indicator / ... |
| `dependencies` | ✅ | 计算依赖列 |
| `min_periods` | ✅ | 最小有效样本 |
| `requires_full_history` | — | 有状态因子标记 |

### 1.1 默认元数据（按大类）

| 大类 | compute_mode | density | usage | preprocess_policy | update_freq |
|------|-------------|---------|-------|-------------------|-------------|
| C/D/A 技术量价风险 | precomputed | dense | both | cross_section_standard | daily |
| B1 估值 | precomputed | dense | cross_section | cross_section_standard | daily |
| B2–B5 财务 | precomputed | dense | cross_section | cross_section_standard | quarterly |
| E1 缠论 L1 | precomputed | sparse | time_series | raw | daily |
| E2 K线聚合 | precomputed | dense | both | cross_section_standard | daily |
| F 合成 | precomputed | dense | both | cross_section_standard | weekly |
| L0 信号 | on_demand | discrete | time_series | raw | daily |

---

## 二、任务归属总览

| 分类 | 因子数 | 计算任务 | 评估 | 合成 |
|------|--------|---------|------|------|
| C 技术因子 | 34 | Task1 | ✅ | L1 composite_technical |
| D1 Alpha101 | 6 | Task1 | ✅ | L1 composite_technical |
| D2 Alpha158 | 10 | Task1 | ✅ | L1 composite_technical |
| D3 资金流(逐标的) | 4+ | Task1 | ✅ | L1 composite_fund_flow |
| A 风险(逐标的) | 18 | Task1 | ✅ | L1 composite_volatility/liquidity |
| E2 K线聚合 | 6 | Task1 | ✅ | L1 composite_technical |
| 缠论 L0/L1 | 10+ 信号/特征 | on_demand | ❌ | ❌ |
| F 合成 Alpha | 7 | Task2 | OOS 独立评估 | — |
| D4 交互因子 | 6 | Task2 | OOS 独立评估 | — |
| B 基本面 | 40 | CrossSection / TaskQ1 | ✅ / TaskQ3 | L1/L2 季频 |
| A 风险(截面) | 6 | cross_section | ✅ | — |
| L0 信号 | 12+ | on_demand | ❌ | ❌ |
| **合计** | **~147 + 信号** | | | |

---

## 三、Task1 逐标的因子

> **数据血缘**: `sdc_candlestick_daily` → OHLCV + amount  
> **计算引擎**: FactorPlugin → talib / numpy / chanpy  
> **标准化原则**: 变化优先 — 比率/偏离度/变化率，确保截面可比

### 3.1 C1 动量/反转 (7)

| factor_id | 展示名 | direction | density | 计算逻辑 |
|-----------|--------|-----------|---------|----------|
| cs_pct_chg | 当日涨跌幅 | DESC | dense | close.pct_change() |
| mom_5d | 5日动量 | DESC | dense | close / close[-5] - 1 |
| mom_20d | 20日动量 | DESC | dense | close / close[-20] - 1 |
| mom_60d | 60日动量 | DESC | dense | close / close[-60] - 1 |
| roc_10 | 10日变化率 | DESC | dense | talib.ROC(close, 10) |
| barra_momentum | Barra动量 | DESC | dense | ewm(halflife=126) 累积收益，剔除近1月 |
| barra_strev | Barra短期反转 | ASC | dense | 近1月收益 × (-1) |

> Barra CNE6: momentum 与 strev 是不同现象，分别衡量中长期动量与短期反转。

### 3.2 C2 趋势 (10)

| factor_id | 展示名 | direction | density |
|-----------|--------|-----------|---------|
| macd_hist_ratio | MACD柱/价格 | DESC | dense |
| macd_hist_delta | MACD柱变化率 | DESC | dense |
| adx_14 | ADX趋势强度 | DESC | dense |
| adx_delta | ADX变化 | DESC | dense |
| adx_plus_di | +DI | DESC | dense |
| adx_minus_di | -DI | ASC | dense |
| boll_position | 布林带位置 | DESC | dense |
| boll_position_delta | 布林带位置变化 | DESC | dense |
| boll_width | 布林带宽度 | DESC | dense |
| sar_deviation | SAR偏离度 | DESC | dense |

### 3.3 C3 超买超卖 (12)

| factor_id | 展示名 | direction | density |
|-----------|--------|-----------|---------|
| rsi_6 / rsi_14 / rsi_24 | RSI | DESC | dense |
| rsi_delta_14 | RSI(14)变化 | DESC | dense |
| kdj_k / kdj_d / kdj_j | KDJ | DESC | dense |
| bias_6 / bias_12 / bias_24 | 乖离率 | DESC | dense |
| cci_14 | CCI(14) | DESC | dense |
| wr_14 | 威廉指标 | ASC | dense |

### 3.4 C4 均线偏离 (5)

| factor_id | 展示名 | direction | density |
|-----------|--------|-----------|---------|
| ma_bias_5/10/20/60 | MA偏离度 | DESC | dense |
| ma_bias_delta_20 | MA20偏离度变化 | DESC | dense |

### 3.5 D1 Alpha101 (6)

| factor_id | 展示名 | direction | density |
|-----------|--------|-----------|---------|
| alpha_1 | 量价偏离极值日 | DESC | dense |
| alpha_12 | 量增价跌反转 | DESC | dense |
| alpha_33 | 收开盘比衰减 | DESC | dense |
| alpha_41 | 几何均价VWAP偏离 | DESC | dense |
| alpha_55 | 日内涨跌量相关 | DESC | dense |
| alpha_101 | 日内K线形态 | DESC | dense |

> WorldQuant "101 Formulaic Alphas" (Kakushadze, 2015)

### 3.6 D2 Alpha158 (10)

| factor_id | 展示名 | direction | density |
|-----------|--------|-----------|---------|
| kmid_5 / klen_5 / kup2_5 / klow2_5 | K线结构均值 | mixed | dense |
| rsv_9 | 9日随机值 | DESC | dense |
| cntp_20 | 20日上涨天数占比 | DESC | dense |
| imax_20 | 20日最高价位置 | ASC | dense |
| roc5_close | 5日收盘变化率 | DESC | dense |
| std20_close | 20日收盘波动率 | ASC | dense |
| corr_pv_10 | 10日价量相关 | ASC | dense |

> Qlib Alpha158 (Microsoft, 2020)

### 3.7 D3 资金流 — 逐标的 (4)

| factor_id | 展示名 | direction | density | 计算逻辑 |
|-----------|--------|-----------|---------|----------|
| cs_main_net_pct | 主力净流入占比 | DESC | dense | main_net_amt / amount |
| cs_net_mf_pct | 全部净流入占比 | DESC | dense | net_mf_amt / amount |
| huge_net_pct | 超大单净流入占比 | DESC | dense | huge_net_amt / amount |
| big_net_pct | 大单净流入占比 | DESC | dense | big_net_amt / amount |

> 华泰金工《个股资金流向因子研究》— 占比形式确保截面可比。数据起始：2023-09-11。

### 3.8 A 风险 — 逐标的 (18)

#### A1 规模 (1)

| factor_id | direction | density |
|-----------|-----------|---------|
| cs_log_mv | DESC | dense |

#### A3 波动率 (10)

| factor_id | direction | density |
|-----------|-----------|---------|
| hist_vol_10/20/60 | ASC | dense |
| downside_vol | ASC | dense |
| dastd | ASC | dense |
| cmra | ASC | dense |
| atr_ratio / atr_ratio_delta | ASC | dense |
| natr_14 | ASC | dense |

#### A4 流动性 (7)

| factor_id | direction | density |
|-----------|-----------|---------|
| cs_turnover / turnover_f | DESC | dense |
| amihud | ASC | dense |
| cs_log_amount | DESC | dense |
| cs_volume_ratio | DESC | dense |
| adv_20 | DESC | dense |
| vol_osc | DESC | dense |

### 3.9 E2 K线聚合 (6)

| factor_id | 展示名 | direction | density |
|-----------|--------|-----------|---------|
| cdl_bull_freq_20 | 20日看涨形态频次 | DESC | dense |
| cdl_bear_freq_20 | 20日看跌形态频次 | ASC | dense |
| cdl_net_score_20 | 20日形态净得分 | DESC | dense |
| cdl_upper_shadow_ratio | 上影线占比均值 | ASC | dense |
| cdl_lower_shadow_ratio | 下影线占比均值 | DESC | dense |
| cdl_body_ratio | 实体占比均值 | DESC | dense |

---

## 四、Task2 合成因子

### 4.1 F 类 — 合成 Alpha (7)

| factor_id | 层级 | composite_method | update_freq | density |
|-----------|------|-----------------|-------------|---------|
| composite_value | L1 | equal_weight | weekly | dense |
| composite_momentum | L1 | equal_weight | weekly | dense |
| composite_volatility | L1 | equal_weight | weekly | dense |
| composite_liquidity | L1 | equal_weight | weekly | dense |
| composite_technical | L1 | equal_weight | weekly | dense |
| composite_fund_flow | L1 | equal_weight | weekly | dense |
| composite_alpha | L2 | icir_weight | weekly | dense |

L1 输入因子清单见系统设计 §11.1。`composite_technical` 输入不含 E1 缠论 sparse 因子。

### 4.2 D4 交互因子 (6)

| factor_id | 组合 | update_freq | density |
|-----------|------|-------------|---------|
| mom_vol_cross | mom_20d × atr_ratio | weekly | dense |
| adx_rsi_cross | adx_14 × rsi_14 | weekly | dense |
| vol_ratio_mom_cross | cs_volume_ratio × mom_20d | weekly | dense |
| rsi_bbands_cross | rsi_14 × boll_position | weekly | dense |
| macd_adx_cross | macd_hist_ratio × adx_14 | weekly | dense |
| vol_mom_accel_cross | atr_ratio × macd_hist_delta | weekly | dense |

category=`interaction`，OOS 独立评估，不参与子因子评估。

---

## 五、截面因子 — CrossSection 按需加载

### 5.1 B1 价值 (8)

| factor_id | direction | data_origin | update_freq |
|-----------|-----------|-------------|-------------|
| ep / bp / sp / dp / ev_ebitda | DESC | daily_indicator | daily |
| pe_ttm / pb / ps_ttm | ASC | daily_indicator | daily |

### 5.2 B2 盈利 (8) — 季频

roe, roe_waa, roe_dt, roa, roic, grossprofit_margin, netprofit_margin, gp_to_assets

### 5.3 B3 成长 (10) — 季频

q_or_yoy, q_netprofit_yoy, q_dtprofit_yoy, q_op_yoy, q_ocf_yoy, q_roe_yoy, q_netprofitgrow_qoq, q_orgrow_qoq, q_opgrow_qoq, q_roegrow_qoq

### 5.4 B4 质量 (8) — 季频

ocf_to_profit, ocf_to_or, salescash_to_or, dtprofit_to_profit, assets_turn, inv_turn, ar_turn, accra

### 5.5 B5 杠杆 (6) — 季频

debt_to_assets, current_ratio, eqt_to_talcapital, ebit_to_interest, ocf_to_debt, mlev

> Barra CNE6 价值/盈利/成长/质量/杠杆分类体系。财务因子 PIT：`ann_date ≤ trade_date`。

### 5.6 A 风险 — 截面 (6)

| factor_id | compute_engine | direction |
|-----------|---------------|-----------|
| nl_size | cross_section | ASC |
| beta_250 | cross_section | DESC |
| beta_down | cross_section | ASC |
| z_turnover | cross_section | DESC |
| stom | cross_section | DESC |
| stoq | cross_section | DESC |

### 5.7 D3 截面 Z-score (1)

| factor_id | 计算 | density |
|-----------|------|---------|
| z_main_net_pct | 全市场 cs_main_net_pct 截面 Z-score | dense |

---

## 六、季频合成因子

| factor_id | 层级 | update_freq |
|-----------|------|-------------|
| composite_growth | L1 | quarterly |
| composite_quality | L1 | quarterly |
| composite_leverage | L1 | quarterly |
| composite_efficiency | L1 | quarterly |
| composite_alpha_quarterly | L2 | quarterly |

---

## 七、缠论与 on_demand 信号/特征

> **不入 Alpha 因子库**：仅 catalog 定义，不写入 `fac_factor_registry` / `fac_factor_value`；业务按需实时计算（chanpy / talib）。

### 7.1 L0 离散信号

| signal_id | 展示名 | 引擎 |
|-----------|--------|------|
| chan_buy_point / chan_sell_point | 缠论买卖点 | chanpy |
| chan_bi_direction | 笔方向 | chanpy |
| chan_multi_resonance | 多级别共振 | chanpy |
| chan_interval_signal | 区间套 | chanpy |
| chan_weekly_trend / chan_weekly_position | 周线趋势/中枢位置 | chanpy |
| td_seq_buy / td_seq_sell / td_seq_count | 神奇九转 | 自研 |
| donchian_high_20 / donchian_low_10 | 唐奇安通道 | talib |

### 7.2 L1 缠论分析特征（sparse，不评估）

| feature_id | 展示名 | 说明 |
|------------|--------|------|
| chan_fractal_strength | 分型强度 | 分型确认 bar 写入 |
| chan_bi_length / chan_bi_kcount / chan_bi_slope | 笔属性 | 笔结束 bar 写入 |
| chan_bi_amplitude / chan_bi_strength | 笔质量 | 笔结束 bar 写入 |
| chan_zs_height_ratio / chan_zs_range | 中枢属性 | 中枢结束 bar 写入 |
| chan_divergence_ratio / chan_macd_area | 背驰/动能 | 事件 bar 写入 |

### 7.3 K线形态离散信号 (21)

吞没、十字星、锤头线、启明星、黄昏星等 — TA-Lib CDL 识别，归信号层。

---

## 八、风格标签（样本池维度）

数据源：`stock.sdc_tag_definition`（15 个标签）→ `stock.sdc_stock_tag`（个股标注）。

| dimension | tag_key | pool_id |
|-----------|---------|---------|
| style | growth / value / core / momentum | `style_growth` … `style_momentum` |
| quality | blue_chip / white_horse / dividend / tech / consumption / cyclical / high_vol / low_vol | `style_<tag_key>` |
| size | large_cap / mid_cap / small_cap | `style_large_cap` … `style_small_cap` |

15 标签与 `fac_factor_pool` 一一对应，规则见 [factor-system-design.md §14.3](./factor-system-design.md)。

---

## 九、评估标签（非 Alpha）

| factor_id | 用途 | 评估 |
|-----------|------|------|
| fwd_ret_1d / fwd_ret_5d / fwd_ret_20d | IC 因变量 | 不参与因子评估 |

category=`return`，Task1 计算，Task3 排除。

---

## 附录 A：命名规范

| 前缀 | 含义 | 示例 |
|------|------|------|
| cs_ | 截面直取/比值 | cs_pct_chg, cs_turnover |
| z_ | 截面 Z-score | z_turnover |
| ma_bias_ | 均线偏离度 | ma_bias_20 |
| mom_ | 动量 | mom_20d |
| rsi_ | RSI（含周期） | rsi_14 |
| adx_ | ADX（含周期） | adx_14 |
| macd_ | MACD 衍生 | macd_hist_ratio |
| chan_ | 缠论 | chan_bi_slope |
| cdl_ | K线聚合 | cdl_bull_freq_20 |
| composite_ | 合成 Alpha | composite_alpha |
| barra_ | Barra 标准 | barra_momentum |

规则：小写字母+数字+下划线；全局唯一；注册前校验。

---

## 附录 B：数据血缘

| 原始表 | 频率 | 产出因子 |
|--------|------|---------|
| sdc_candlestick_daily | 日 | C, D1, D2, A3, E1, E2 |
| sdc_daily_indicator | 日 | A1, A4, B1 |
| sdc_fina_indicator | 季 | B2–B5 |
| sdc_fund_flow_individual | 日 | D3 |
| sdc_index_weight | 日 | 样本池 |
| sdc_sw_industry_member | 日 | 行业中性化 |

---

*系统架构与消费契约见 [factor-system-design.md](./factor-system-design.md)。*
