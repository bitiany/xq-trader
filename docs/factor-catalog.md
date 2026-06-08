# xqtrader 因子库架构设计

> **版本**: v4.0 | **更新**: 2026-06-07
> **定位**: 因子库顶层架构与分类体系，指导因子注册、评估与融合

---

## 一、架构总览

### 1.1 设计原则

| 原则 | 说明 |
|------|------|
| 截面优先 | 因子库以截面因子为核心，支持横截面排序与比较 |
| 风险/收益分离 | 风险因子解释方差，Alpha因子预测收益，两者分层管理 |
| 三级层次 | 原始因子 → 加工因子 → 复合Alpha因子，逐层提纯 |
| 评估驱动 | 因子入库须经 IC/ICIR/换手率等统计检验，不合格因子降级或淘汰 |
| 信号独立 | 非截面形态信号不纳入因子库，由信号/策略层独立管理 |

### 1.2 因子体系全景

```
┌─────────────────────────────────────────────────────────────┐
│                    因子体系 (Factor Universe)                │
├──────────────────────┬──────────────────────────────────────┤
│   截面因子           │   非截面信号                          │
│   (Cross-Sectional)  │   (Non-Cross-Sectional)              │
│                      │                                      │
│  ┌────────────────┐  │  ┌────────────────────────────────┐  │
│  │ 基本面因子      │  │  │ 缠论信号 (chan_signal)         │  │
│  │  估值/规模      │  │  │  一买/三买/一卖/三卖           │  │
│  │  盈利/成长      │  │  │  多级别共振/区间套             │  │
│  │  质量/杠杆      │  │  ├────────────────────────────────┤  │
│  ├────────────────┤  │  │ K线形态信号 (candlestick)      │  │
│  │ 技术因子        │  │  │  吞没/十字星/锤头线等          │  │
│  │  趋势/动量      │  │  └────────────────────────────────┘  │
│  │  波动/流动性    │  │                                      │
│  │  超买超卖       │  │  → 由信号引擎管理，不入因子库      │
│  ├────────────────┤  │  → 输出可量化连续值时可升级为因子    │
│  │ 量价因子        │  │                                      │
│  │  Alpha101/158   │  │                                      │
│  │  资金流         │  │                                      │
│  ├────────────────┤  │                                      │
│  │ 复合Alpha因子   │  │                                      │
│  │  多因子融合     │  │                                      │
│  └────────────────┘  │                                      │
└──────────────────────┴──────────────────────────────────────┘
```

---

## 二、与业界主流方案对比

### 2.1 MSCI Barra CNE6 风险模型

Barra 是全球机构最广泛使用的多因子风险模型，CNE6 为中国A股版本。

| 维度 | Barra CNE6 | 当前文档 (v3.4) | 差距分析 |
|------|-----------|----------------|---------|
| **架构层次** | 市场因子 → 行业因子 → 风格因子（三层） | 扁平分类，无层次 | 缺少分层架构 |
| **风险/Alpha分离** | 风险因子解释方差，Alpha因子预测收益 | 未区分 | 混为一谈 |
| **规模因子** | Size + Non-linear Size（立方项） | 仅有 cs_log_mv | 缺少非线性规模 |
| **Beta因子** | 有（系统性风险） | 无 | 缺失 |
| **价值因子** | Book-to-Price（BP） | PE/PB/PS 分散 | 未聚合为统一价值因子 |
| **动量因子** | Momentum（12M剔除近1M）+ Short-term Reversal | 有 barra_momentum / barra_strev | 基本对齐 |
| **波动率因子** | Residual Volatility（DASTD/CMRA/HISVOL） | hist_vol_20/60, downside_vol | 缺少残差波动率 |
| **盈利因子** | Earnings Yield（EP/Cash EY/Analyst EP） | ROE/ROA/ROIC 分散 | 未聚合为盈利收益率 |
| **成长因子** | Growth（长期盈利增长/营收增长） | 同比/环比齐全 | 基本对齐 |
| **杠杆因子** | Leverage（MLEV/FMLEV/DTOA） | debt_to_assets 等 | 缺少市场杠杆 |
| **流动性因子** | Liquidity（STOM/STOQ/STOA/TO） | 换手率/Amihud | 缺少月/季/年换手 |
| **行业中性化** | 必做 | 无 | 缺失 |
| **因子评估** | IC/ICIR/换手率/衰减 | 无 | 完全缺失 |

### 2.2 Axioma 风险模型

| 维度 | Axioma | 当前文档 | 差距 |
|------|--------|---------|------|
| 因子类型 | 基本面因子模型 + 统计因子模型 | 仅有基本面+技术 | 缺少统计因子（PCA） |
| 因子正交化 | 施密特正交化，确保因子间低共线性 | 无 | 因子间可能高度共线 |
| 特质风险 | 建模个股特质波动率 | 无 | 缺失 |

### 2.3 WorldQuant Alpha101 / Qlib Alpha158

| 维度 | Alpha101/158 | 当前文档 | 差距 |
|------|-------------|---------|------|
| 因子数量 | Alpha101: 101个; Alpha158: 158个 | 各取6/10个代表 | 覆盖不足，但代表子集可接受 |
| 因子评估 | IC/换手率/衰减/分层回测 | 无 | 完全缺失 |
| 因子合成 | IC加权/ICIR加权/ML融合 | 仅有6个交叉因子 | 缺少系统化融合框架 |

### 2.4 国内平台（聚宽/米筐/DolphinDB）

| 维度 | 国内平台 | 当前文档 | 差距 |
|------|---------|---------|------|
| 因子分类 | 基本面/技术/另类 三大类 | 19个细分类 | 过细，缺少顶层归纳 |
| 因子存储 | 分区+时间序列优化 | sdc_factor_value | 存储层可优化 |
| 因子评估 | IC/ICIR/分层回测/衰减 | 无 | 完全缺失 |

### 2.5 核心差距总结

| # | 差距 | 严重程度 | 说明 |
|---|------|---------|------|
| 1 | **无风险/Alpha因子分离** | 高 | Barra/Axioma 均区分风险因子与Alpha因子 |
| 2 | **无因子评估体系** | 高 | IC/ICIR/换手率/衰减是因子入库的必要门槛 |
| 3 | **无复合Alpha因子层** | 高 | 多因子融合是机构Alpha的核心来源 |
| 4 | **无行业中性化** | 高 | 截面因子不做行业中性化，IC严重受行业偏移影响 |
| 5 | **缺少关键风险因子** | 中 | Beta、非线性规模、残差波动率、盈利收益率 |
| 6 | **缠论/K线形态混入因子库** | 中 | 离散信号不应作为截面因子管理 |
| 7 | **分类过细无层次** | 中 | 19个平级分类，缺少大类归纳 |
| 8 | **因子间共线性未处理** | 中 | PE/PB/PS 高度相关，未正交化 |

---

## 三、因子分类体系

### 3.1 截面因子 vs 非截面信号

**截面因子**的核心特征：在某一时间截面上，可对全市场股票进行排序比较，因子值具有横截面可比性。

| 特征 | 截面因子 | 非截面信号 |
|------|---------|-----------|
| 值类型 | 连续实数 | 离散/布尔/枚举 |
| 横截面可比 | 可排序、可分层 | 不可排序比较 |
| 统计检验 | IC/ICIR/分层回测 | 胜率/盈亏比/信号回测 |
| 典型例子 | PE、RSI、动量、波动率 | 一买信号、吞没形态 |
| 管理归属 | 因子库 | 信号/策略引擎 |
| 融合方式 | 加权/ML合成 | 逻辑组合/规则叠加 |

### 3.2 缠论因子定位分析

| 缠论输出 | 值类型 | 截面可比 | 归属建议 |
|----------|--------|---------|---------|
| 顶/底分型 | 布尔(0/1) | 否 | 信号层 |
| 分型强度 | 连续实数 | **是** | 因子库（chan_fractal_strength） |
| 分型确认 | 布尔(0/1) | 否 | 信号层 |
| 包含合并标志 | 布尔(0/1) | 否 | 信号层 |
| 笔方向 | 枚举(+1/-1) | 否 | 信号层 |
| 笔长度 | 连续实数 | **是** | 因子库（chan_bi_length） |
| 笔内K线数 | 连续实数 | **是** | 因子库（chan_bi_kcount） |
| 笔斜率 | 连续实数 | **是** | 因子库（chan_bi_slope） |
| 笔振幅 | 连续实数 | **是** | 因子库（chan_bi_amplitude） |
| 笔强度 | 连续实数 | **是** | 因子库（chan_bi_strength） |
| 中枢上沿/下沿 | 连续实数 | **是** | 因子库（chan_zs_zg/zd） |
| 中枢区间 | 连续实数 | **是** | 因子库（chan_zs_range） |
| 中枢高度比 | 连续实数 | **是** | 因子库（chan_zs_height_ratio） |
| 背驰强度 | 连续实数 | **是** | 因子库（chan_divergence_ratio） |
| MACD面积 | 连续实数 | **是** | 因子库（chan_macd_area） |
| 一买/三买/一卖/三卖 | 离散信号 | 否 | **信号层** |
| 周线趋势方向 | 枚举 | 否 | 信号层 |
| 多级别共振 | 布尔 | 否 | 信号层 |
| 区间套信号 | 布尔 | 否 | 信号层 |
| 周线中枢位置 | 枚举 | 否 | 信号层 |

**结论**：缠论输出中，连续值指标（笔斜率、笔强度、中枢高度比、背驰强度等）可作为截面因子管理；离散信号（买卖点、共振、区间套）应归入信号/策略层。

### 3.3 K线形态定位分析

| K线形态输出 | 值类型 | 截面可比 | 归属建议 |
|------------|--------|---------|---------|
| 单根形态识别（吞没/十字星/锤头等） | 布尔(0/1) | 否 | 信号层 |
| N日形态出现频次 | 连续实数 | **是** | 因子库（cdl_freq_*） |
| 加权影线频率 | 连续实数 | **是** | 因子库（cdl_shadow_ratio） |
| 形态信号强度聚合 | 连续实数 | **是** | 因子库（cdl_signal_score） |

**结论**：单根K线形态识别为离散信号，归信号层；但形态的统计聚合（频次、影线比、信号强度评分）可形成截面因子。业界研究（华创证券《形态因子研究初探》、西南证券《加权影线频率与K线形态因子》）已验证此类聚合因子的有效性。

---

## 四、截面因子分类体系

### 4.1 大类划分

参照 Barra CNE6 + Axioma + 国内实践，截面因子分为 **五大类**：

```
截面因子
├── A. 风险因子 (Risk Factors)          — 解释收益方差，用于风险控制
│   ├── A1 规模 (Size)
│   ├── A2 Beta (系统性风险)
│   ├── A3 波动率 (Volatility)
│   └── A4 流动性 (Liquidity)
│
├── B. 基本面因子 (Fundamental Factors)  — 预测收益，Alpha来源
│   ├── B1 价值 (Value)
│   ├── B2 盈利 (Profitability)
│   ├── B3 成长 (Growth)
│   ├── B4 质量 (Quality)
│   └── B5 杠杆 (Leverage)
│
├── C. 技术因子 (Technical Factors)      — 量价信息，Alpha来源
│   ├── C1 动量/反转 (Momentum/Reversal)
│   ├── C2 趋势 (Trend)
│   ├── C3 超买超卖 (Oscillator)
│   └── C4 均线 (Moving Average)
│
├── D. 量价因子 (Price-Volume Factors)   — 高阶量价关系，Alpha来源
│   ├── D1 Alpha101 (WorldQuant)
│   ├── D2 Alpha158 (Qlib)
│   ├── D3 资金流 (Money Flow)
│   └── D4 交互因子 (Interaction)
│
└── E. 复合Alpha因子 (Composite Alpha)   — 多因子融合产出
    ├── E1 等权复合
    ├── E2 IC加权复合
    ├── E3 ICIR加权复合
    └── E4 ML融合复合
```

### 4.2 风险因子（Risk Factors）

风险因子解释收益方差，是组合风险控制的基石。参照 Barra，风险因子不做Alpha预测，但必须纳入风险模型。

#### A1 规模因子 (Size)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| cs_log_mv | 对数总市值 | DESC | log(1+total_mv) | Barra Size |
| nl_size | 非线性规模 | ASC | (log_mv)³ 正交化 | Barra Non-linear Size，捕捉规模非线性效应 |

#### A2 Beta因子 (Beta)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| beta_250 | 250日Beta | DESC | Cov(ret, mkt_ret)/Var(mkt_ret) | Barra Beta，系统性风险暴露 |
| beta_down | 下行Beta | ASC | 负收益日Cov/Var | 不对称风险度量 |

> 当前文档缺失Beta因子，为重大缺口。

#### A3 波动率因子 (Volatility)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| hist_vol_20 | 20日历史波动率 | ASC | STD(20,daily_ret)*sqrt(252) | 短期波动 |
| hist_vol_60 | 60日历史波动率 | ASC | STD(60,daily_ret)*sqrt(252) | 中期波动 |
| downside_vol | 下行波动率 | ASC | STD(负收益日)*sqrt(252) | 不对称波动 |
| dastd | 日收益标准差 | ASC | 加权标准差(252日) | Barra DASTD |
| cmra | 累计收益范围 | ASC | log(1+max_cum)-log(1+min_cum) | Barra CMRA |
| atr_14 | ATR(14) | DESC | talib.ATR(14) | 绝对波动 |
| atr_ratio | ATR/价格 | ASC | ATR(14)/close | 标准化波动 |
| boll_width | 布林带宽度 | DESC | (upper-lower)/middle | 波动率代理 |

> Barra 将波动率因子定义为 Residual Volatility（残差波动率），由 DASTD + CMRA + HISVOL 正交化后合成。当前文档仅有原始波动率，缺少残差波动率。

#### A4 流动性因子 (Liquidity)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| cs_turnover | 换手率 | DESC | turnover_rate | 日换手 |
| turnover_f | 流通换手率 | DESC | turnover_rate_f | 流通股换手 |
| z_turnover | 换手率Z-score | DESC | 截面标准化换手率 | 标准化换手 |
| amihud | Amihud非流动性 | ASC | abs(ret)/amount | 价格冲击 |
| cs_log_amount | 对数成交额 | DESC | log(1+amount) | 成交规模 |
| cs_volume_ratio | 量比 | DESC | volume_ratio | 量能异动 |
| stom | 月换手率 | DESC | sum(turnover, 21) | Barra STOM |
| stoq | 季换手率 | DESC | avg(STOM, 3) | Barra STOQ |
| adv_20 | 20日均成交量 | DESC | MA(volume,20) | 均量 |
| vol_osc | 量振荡 | DESC | MA(V,5)/MA(V,20) | 量能趋势 |

> Barra 流动性因子由 STOM/STOQ/STOA 合成，当前文档缺少月/季/年换手率。

---

### 4.3 基本面因子（Fundamental Factors）

基本面因子是 Alpha 的核心来源，需做行业中性化处理。

#### B1 价值因子 (Value)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| pe_ttm | 市盈率TTM | ASC | 总市值/净利润TTM | EP = 1/PE 更常用 |
| ep_ttm | 盈利收益率TTM | DESC | 1/PE_TTM | Barra Earnings Yield 核心项 |
| pb | 市净率 | ASC | daily_indicator.pb | BP = 1/PB 更常用 |
| bp | 账面市值比 | DESC | 1/PB | Barra Book-to-Price |
| ps_ttm | 市销率TTM | ASC | daily_indicator.ps_ttm | SP = 1/PS |
| sp_ttm | 销售收益率TTM | DESC | 1/PS_TTM | 销售估值 |
| pe | 市盈率(动态) | ASC | daily_indicator.pe | 短期估值 |
| ps | 市销率(动态) | ASC | daily_indicator.ps | 短期估值 |
| dv_ratio | 股息率(%) | DESC | daily_indicator.dv_ratio | 分红收益 |
| dv_ttm | 股息率TTM(%) | DESC | daily_indicator.dv_ttm | 分红收益TTM |
| cfp | 现金收益率 | DESC | 经营现金流/总市值 | Barra Cash Earnings Yield |

> Barra 价值因子 = Book-to-Price；盈利收益率因子 = EP + Cash EY + Analyst EP。当前文档缺少 EP/BP/CFP 的倒数形式和现金收益率。

#### B2 盈利因子 (Profitability)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| roe | 净资产收益率 | DESC | fina_indicator.roe | 核心盈利 |
| roe_waa | 加权平均ROE | DESC | fina_indicator.roe_waa | 杜邦分析 |
| roe_dt | ROE(扣非) | DESC | fina_indicator.roe_dt | 剔除非经常 |
| roa | 总资产报酬率 | DESC | fina_indicator.roa | 资产效率 |
| roic | 投入资本回报率 | DESC | fina_indicator.roic | 资本效率 |
| grossprofit_margin | 销售毛利率 | DESC | fina_indicator.grossprofit_margin | 毛利水平 |
| netprofit_margin | 销售净利率 | DESC | fina_indicator.netprofit_margin | 净利水平 |
| eps | 基本每股收益 | DESC | fina_indicator.eps | 每股盈利 |

#### B3 成长因子 (Growth)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| q_or_yoy | 营收同比增长率 | DESC | fina_indicator.q_or_yoy | 营收增长 |
| q_netprofit_yoy | 净利润同比增长率 | DESC | fina_indicator.q_netprofit_yoy | 利润增长 |
| q_dtprofit_yoy | 扣非净利润同比增长率 | DESC | fina_indicator.q_dtprofit_yoy | 核心利润增长 |
| q_op_yoy | 营业利润同比增长率 | DESC | fina_indicator.q_op_yoy | 经营增长 |
| q_tr_yoy | 营业总收入同比增长率 | DESC | fina_indicator.q_tr_yoy | 总收入增长 |
| q_ocf_yoy | 经营现金流同比增长率 | DESC | fina_indicator.q_ocf_yoy | 现金流增长 |
| q_roe_yoy | ROE同比增长率 | DESC | fina_indicator.q_roe_yoy | 效率提升 |
| q_netprofitgrow_qoq | 净利润环比增长率 | DESC | fina_indicator.q_netprofitgrow_qoq | 短期加速 |
| q_orgrow_qoq | 营收环比增长率 | DESC | fina_indicator.q_orgrow_qoq | 短期加速 |
| q_opgrow_qoq | 营业利润环比增长率 | DESC | fina_indicator.q_opgrow_qoq | 短期加速 |
| q_roegrow_qoq | ROE环比增长率 | DESC | fina_indicator.q_roegrow_qoq | 短期加速 |
| q_equitygrow_qoq | 净资产环比增长率 | DESC | fina_indicator.q_equitygrow_qoq | 资本积累 |

#### B4 质量因子 (Quality)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| ocf_to_profit | 经营现金流/净利润 | DESC | fina_indicator.ocf_to_profit | 盈利质量 |
| ocf_to_or | 经营现金流/营业收入 | DESC | fina_indicator.ocf_to_or | 收入质量 |
| salescash_to_or | 销售收现/营业收入 | DESC | fina_indicator.salescash_to_or | 收入含金量 |
| dtprofit_to_profit | 扣非净利/净利润 | DESC | fina_indicator.dtprofit_to_profit | 利润持续性 |
| assets_turn | 总资产周转率 | DESC | fina_indicator.assets_turn | 运营效率 |
| inv_turn | 存货周转率 | DESC | fina_indicator.inv_turn | 库存管理 |
| ar_turn | 应收账款周转率 | DESC | fina_indicator.ar_turn | 回款效率 |
| capitalized_to_da | 资本支出/折旧摊销 | ASC | fina_indicator.capitalized_to_da | 投资强度 |

#### B5 杠杆因子 (Leverage)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| debt_to_assets | 资产负债率 | ASC | fina_indicator.debt_to_assets | Barra DTOA |
| current_ratio | 流动比率 | DESC | fina_indicator.current_ratio | 短期偿债 |
| quick_ratio | 速动比率 | DESC | fina_indicator.quick_ratio | 短期偿债 |
| eqt_to_talcapital | 归母权益/全部投入资本 | DESC | fina_indicator.eqt_to_talcapital | Barra FMLEV |
| ebit_to_interest | 利息保障倍数 | DESC | fina_indicator.ebit_to_interest | 偿债安全 |
| ocf_to_debt | 经营现金流/负债合计 | DESC | fina_indicator.ocf_to_debt | 现金偿债 |
| mlev | 市场杠杆 | ASC | 总市值/(总市值-净负债) | Barra MLEV |

> 当前文档缺少市场杠杆（MLEV），Barra 杠杆因子由 MLEV + FMLEV + DTOA 合成。

---

### 4.4 技术因子（Technical Factors）

#### C1 动量/反转因子 (Momentum/Reversal)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| cs_pct_chg | 当日涨跌幅 | DESC | pct_chg 截面 | 日度动量 |
| mom_ret5d | 5日动量收益 | DESC | close/close[-5]-1 | 短期动量 |
| mom_20d | 20日动量 | DESC | close/close[-20]-1 | 中期动量 |
| mom_60d | 60日动量 | DESC | close/close[-60]-1 | 长期动量 |
| roc_10 | 10日变化率 | DESC | talib.ROC(10) | 变化率 |
| barra_momentum | Barra动量 | DESC | 12月收益(剔除近1月) | Barra标准动量 |
| rev_5d | 5日反转 | ASC | -1×mom_ret5d | 短期反转 |
| rev_20d | 20日反转 | ASC | -1×roc_20 | 中期反转 |
| barra_strev | Barra短期反转 | ASC | 近1月收益×(-1) | Barra标准反转 |

#### C2 趋势因子 (Trend)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| macd_dif | MACD-DIF线 | DESC | EMA(12)-EMA(26) | 趋势方向 |
| macd_dea | MACD-DEA线 | DESC | EMA(DIF,9) | 信号线 |
| macd_hist | MACD-柱状图 | DESC | DIF-DEA | 趋势强度 |
| adx_14 | ADX(14)趋势强度 | DESC | talib.ADX(14) | 趋势确定性 |
| adx_plus_di | +DI上升方向 | DESC | talib.PLUS_DI(14) | 上升力度 |
| adx_minus_di | -DI下降方向 | ASC | talib.MINUS_DI(14) | 下降力度 |
| sar | 抛物线指标 | DESC | talib.SAR | 趋势跟踪 |
| boll_upper | 布林上轨 | DESC | MA(20)+2σ | 压力位 |
| boll_middle | 布林中轨 | DESC | MA(20) | 趋势中值 |
| boll_lower | 布林下轨 | ASC | MA(20)-2σ | 支撑位 |

#### C3 超买超卖因子 (Oscillator)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| rsi_14 | RSI(14) | DESC | talib.RSI(14) | 超买超卖 |
| kdj_k | KDJ-K值 | DESC | talib.STOCH(K=9,slowK=3) | 短线方向 |
| kdj_d | KDJ-D值 | DESC | K的3日平滑 | 中线方向 |
| kdj_j | KDJ-J值 | DESC | 3K-2D | 超买超卖 |
| bias_6 | BIAS(6)乖离率 | DESC | (C-MA6)/MA6*100 | 短期偏离 |
| bias_12 | BIAS(12)乖离率 | DESC | (C-MA12)/MA12*100 | 中期偏离 |
| bias_24 | BIAS(24)乖离率 | DESC | (C-MA24)/MA24*100 | 长期偏离 |
| cci_14 | CCI(14) | DESC | talib.CCI(14) | 顺势指标 |
| wr_14 | WR(14)威廉指标 | ASC | talib.WILLR(14) | 超买超卖 |

#### C4 均线因子 (Moving Average)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| ma_5 | MA5 | DESC | talib.MA(5) | 短期均线 |
| ma_10 | MA10 | DESC | talib.MA(10) | 短期均线 |
| ma_20 | MA20 | DESC | talib.MA(20) | 中期均线 |
| ma_30 | MA30 | DESC | talib.MA(30) | 中期均线 |
| ma_60 | MA60 | DESC | talib.MA(60) | 中长期均线 |
| ma_120 | MA120 | DESC | talib.MA(120) | 长期均线 |
| ma_250 | MA250年线 | DESC | talib.MA(250) | 长期均线 |
| ema_12 | EMA12 | DESC | talib.EMA(12) | 指数均线 |

---

### 4.5 量价因子（Price-Volume Factors）

#### D1 Alpha101 因子 (WorldQuant)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| alpha_1 | 量价偏离极值日 | DESC | rank(ts_argmax((vwap-0.5*open)^2,5)) | WQ#1 |
| alpha_12 | 量增价跌反转 | DESC | sign(Δvolume)*(-Δ(close-open)) | WQ#12 |
| alpha_33 | 收开盘比衰减 | DESC | -rank(decay_linear(close/open,5)) | WQ#33 |
| alpha_41 | 几何均价VWAP偏离 | DESC | sqrt(high*low)-vwap | WQ#41 |
| alpha_55 | 日内涨跌量相关 | DESC | -corr(rank(close-open),rank(volume),5) | WQ#55 |
| alpha_101 | 日内K线形态 | DESC | (close-open)/(high-low+0.001) | WQ#101 |

#### D2 Alpha158 因子 (Qlib)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| kmid_5 | 5日K线实体均值 | DESC | MA(5,(C-O)/O) | 实体比例 |
| klen_5 | 5日K线振幅均值 | DESC | MA(5,(H-L)/O) | 振幅 |
| kup2_5 | 5日上影线占比均值 | ASC | MA(5,(H-max(O,C))/(H-L)) | 上影线 |
| klow2_5 | 5日下影线占比均值 | DESC | MA(5,(min(O,C)-L)/(H-L)) | 下影线 |
| rsv_9 | 9日随机值 | DESC | (C-L9)/(H9-L9) | 随机指标 |
| cntp_20 | 20日上涨天数占比 | DESC | count(C>C1,20)/20 | 涨跌比 |
| sumd_20 | 20日净上涨贡献比 | DESC | SUMP-SUMN | 净上涨 |
| imax_20 | 20日最高价位置 | ASC | argmax(C,20)/20 | 高点位置 |
| roc5_close | 5日收盘变化率 | DESC | C/C[-5]-1 | 变化率 |
| std20_close | 20日收盘标准差 | ASC | STD(20,C)/C | 波动率代理 |

#### D3 资金流因子 (Money Flow)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| cs_net_mf_amt | 全部净流入额 | DESC | net_mf_amt | 资金净流入 |
| cs_main_net_pct | 主力净流入占比 | DESC | main_net_pct | 主力动向 |
| huge_net_amt | 超大单净流入 | DESC | huge_net_amt | 大资金 |
| big_net_amt | 大单净流入 | DESC | big_net_amt | 中大资金 |
| main_net_amt | 主力净流入额 | DESC | main_net_amt | 主力金额 |
| z_main_net_pct | 主力净流入Z-score | DESC | 截面标准化 main_net_pct | 标准化主力 |

#### D4 交互因子 (Interaction)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| mom_vol_cross | 动量×波动 | DESC | momentum × ATR_norm | 非线性交互 |
| adx_rsi_cross | ADX×RSI偏离 | DESC | ADX × (RSI-50)/50 | 趋势+超买 |
| vol_ratio_mom_cross | 量比×动量 | DESC | vol_ratio × momentum | 量价配合 |
| rsi_bbands_cross | RSI×布林位置 | DESC | RSI × bbands_position | 超买+通道 |
| macd_adx_cross | MACD×ADX | DESC | MACD_hist × ADX | 趋势确认 |
| vol_mom_accel_cross | 波动×动量加速度 | DESC | volatility × momentum_accel | 波动加速 |

---

### 4.6 缠论连续值因子（Chan Continuous Factors）

> 仅保留缠论输出中具有截面可比性的连续值指标。离散信号归入信号层。

| factor_id | 展示名 | group_id | 方向 | 计算逻辑 | 说明 |
|-----------|--------|----------|------|----------|------|
| chan_fractal_strength | 分型强度 | chan_fractal | DESC | 极值与两侧差之和 | 分型显著度 |
| chan_bi_length | 笔长度 | chan_bi | DESC | abs(顶H-底L) | 趋势幅度 |
| chan_bi_kcount | 笔内K线数 | chan_bi | DESC | 一笔内K线数 | 趋势持续 |
| chan_bi_slope | 笔斜率 | chan_bi | DESC | (终点价-起点价)/K线数*100 | 趋势强度 |
| chan_bi_amplitude | 笔振幅 | chan_bi | ASC | 笔内最大回撤/笔长度 | 趋势质量 |
| chan_bi_strength | 笔强度 | chan_bi | DESC | 笔长度/笔内K线数 | 趋势效率 |
| chan_zs_zg | 中枢上沿ZG | chan_zs | DESC | min(各笔最高价) | 阻力位 |
| chan_zs_zd | 中枢下沿ZD | chan_zs | DESC | max(各笔最低价) | 支撑位 |
| chan_zs_range | 中枢区间 | chan_zs | DESC | ZG-ZD | 震荡幅度 |
| chan_zs_height_ratio | 中枢高度比 | chan_zs | DESC | (ZG-ZD)/price | 标准化中枢 |
| chan_divergence_ratio | 背驰强度 | chan_div | DESC | A_curr/A_prev面积比 | 背驰程度 |
| chan_macd_area | MACD面积 | chan_div | DESC | 笔内MACD柱状图绝对值之和 | 动能衰减 |

---

### 4.7 K线形态聚合因子（Candlestick Aggregate Factors）

> 单根K线形态识别为离散信号，归信号层。以下为形态的统计聚合，具有截面可比性。

| factor_id | 展示名 | group_id | 方向 | 计算逻辑 | 说明 |
|-----------|--------|----------|------|----------|------|
| cdl_bull_freq_20 | 20日看涨形态频次 | cdl_agg | DESC | 20日内看涨形态出现次数 | 看涨信号密度 |
| cdl_bear_freq_20 | 20日看跌形态频次 | cdl_agg | ASC | 20日内看跌形态出现次数 | 看跌信号密度 |
| cdl_net_score_20 | 20日形态净得分 | cdl_agg | DESC | (看涨次数-看跌次数)/总次数 | 形态方向 |
| cdl_upper_shadow_ratio | 上影线占比均值 | cdl_agg | ASC | MA(20,(H-max(O,C))/(H-L)) | 压力强度 |
| cdl_lower_shadow_ratio | 下影线占比均值 | cdl_agg | DESC | MA(20,(min(O,C)-L)/(H-L)) | 支撑强度 |
| cdl_body_ratio | 实体占比均值 | cdl_agg | DESC | MA(20,abs(C-O)/(H-L+0.001)) | 趋势确定性 |

---

## 五、非截面信号层

### 5.1 信号层定位

非截面信号由**信号引擎**独立管理，不入因子库，不参与因子评估和融合。

```
信号引擎 (Signal Engine)
├── 缠论信号
│   ├── 顶/底分型识别 (chan_fractal_top/bottom)
│   ├── 分型确认 (chan_fractal_confirmed)
│   ├── 包含合并标志 (chan_inclusion_merged)
│   ├── 笔方向 (chan_bi_direction)
│   ├── 买卖信号 (chan_signal_buy1/buy3/sell1/sell3)
│   ├── 周线趋势方向 (chan_weekly_trend)
│   ├── 多级别共振 (chan_multi_resonance)
│   ├── 区间套信号 (chan_interval_signal)
│   └── 周线中枢位置 (chan_weekly_position)
│
├── K线形态信号
│   ├── 看涨形态 (cdl_engulfing_bull, cdl_hammer, cdl_morning_star, ...)
│   ├── 看跌形态 (cdl_engulfing_bear, cdl_hanging_man, cdl_evening_star, ...)
│   └── 中性形态 (cdl_doji, cdl_spinning_top, ...)
│
└── 信号输出
    ├── signal_id (信号唯一标识)
    ├── signal_type (信号类型)
    ├── signal_value (0/1 或枚举)
    ├── signal_strength (信号强度评分，0-100)
    └── signal_context (信号上下文：趋势环境、位置等)
```

### 5.2 信号与因子的关系

```
信号 ──聚合统计──→ 截面因子
  │                    │
  │  例：20日看涨形态次数  │  例：cdl_bull_freq_20
  │                    │
  └──直接使用──→ 策略/交易决策
       │
       例：一买信号 → 触发买入
```

- 信号可**聚合**为因子（频次、比率、强度评分）
- 因子**不可**还原为信号（聚合不可逆）
- 信号可直接驱动交易策略，不必须经过因子层

---

## 六、因子评估体系

### 6.1 评估指标

| 指标 | 公式 | 阈值标准 | 说明 |
|------|------|---------|------|
| **IC** | Spearman秩相关(因子值, 下期收益) | \|IC\| > 0.03 可用 | 因子预测能力 |
| **ICIR** | IC_mean / IC_std | ICIR > 0.5 可用, > 1.0 优良 | 预测稳定性 |
| **IC胜率** | IC > 0 的期数 / 总期数 | > 55% | 预测一致性 |
| **因子换手率** | Σ\|w_t - w_{t-1}\| / 2 | < 70% 为佳 | 因子稳定性 |
| **因子衰减** | IC(h=1,2,...,20) | 衰减半衰期 > 3日 | 预测持续性 |
| **分层收益单调性** | 5分层多空收益单调递增/递减 | 多空年化 > 5% | 因子区分度 |
| **因子覆盖度** | 非空值占比 | > 80% | 数据可用性 |
| **因子共线性** | 与已有因子的秩相关 | \|ρ\| < 0.7 | 因子独立性 |

### 6.2 评估流程

```
因子候选
  │
  ▼
① 预处理
  Winsorize(3σ) → 行业中性化 → Z-score标准化
  │
  ▼
② IC/ICIR 检验
  滚动252日IC序列 → 计算IC_mean, IC_std, ICIR, IC胜率
  │
  ├── ICIR < 0.3 → 淘汰
  │
  ▼
③ 分层回测
  5分位 → 各层收益/风险 → 多空收益/夏普
  │
  ├── 多空年化 < 3% → 淘汰
  │
  ▼
④ 衰减分析
  IC(h=1..20) → 半衰期
  │
  ├── 半衰期 < 2日 → 降级为日内因子
  │
  ▼
⑤ 共线性检验
  与已有因子秩相关 → |ρ| > 0.7 → 考虑合并或正交化
  │
  ▼
⑥ 入库 / 降级 / 淘汰
```

### 6.3 因子等级

| 等级 | 标准 | 用途 |
|------|------|------|
| **A级** | ICIR > 1.0, 多空年化 > 10%, 换手率 < 50% | 核心Alpha因子，可独立使用 |
| **B级** | ICIR > 0.5, 多空年化 > 5%, 换手率 < 70% | 辅助Alpha因子，需组合使用 |
| **C级** | ICIR > 0.3, 多空年化 > 3% | 弱Alpha因子，仅作ML特征 |
| **D级** | ICIR < 0.3 或 多空年化 < 3% | 无效因子，淘汰或降级为信号 |

---

## 七、多因子融合与复合Alpha因子

### 7.1 因子预处理流水线

```
原始因子值
  │
  ▼
① 缺失值处理
  行业均值填充 或 丢弃
  │
  ▼
② 去极值 (Winsorize)
  MAD法: |x - median| > 5*MAD → clip
  │
  ▼
③ 行业中性化
  因子值 = 原始值 - 行业均值 (或回归残差)
  │
  ▼
④ 标准化 (Z-score)
  (x - μ) / σ，截面标准化
  │
  ▼
⑤ 正交化 (可选)
  对风险因子回归取残差，消除风险暴露
  │
  ▼
加工因子值 → 用于融合
```

### 7.2 融合方法

| 方法 | 公式 | 优点 | 缺点 | 适用场景 |
|------|------|------|------|---------|
| **等权** | α = (1/N) Σ f_i | 简单稳健 | 忽略因子质量差异 | 因子数量少、质量相近 |
| **IC加权** | α = Σ(IC_i × f_i) / Σ\|IC_i\| | 赋权与预测力成正比 | IC不稳定时权重波动 | 因子IC稳定 |
| **ICIR加权** | α = Σ(ICIR_i × f_i) / Σ\|ICIR_i\| | 兼顾预测力与稳定性 | 需较长IC历史 | 因子ICIR分化明显 |
| **最大化ICIR** | w = Σ⁻¹ × IC | 理论最优 | 协方差矩阵估计敏感 | 因子数量适中 |
| **ML融合** | XGBoost/LightGBM/NN | 捕捉非线性 | 过拟合风险 | 因子数量多、交互复杂 |

### 7.3 复合Alpha因子定义

| factor_id | 展示名 | 融合方法 | 输入因子 | 说明 |
|-----------|--------|---------|---------|------|
| alpha_eq | 等权Alpha | 等权 | B类+C类+D类全部A级因子 | 基线Alpha |
| alpha_ic | IC加权Alpha | IC加权 | B类+C类+D类全部A级因子 | 自适应Alpha |
| alpha_icir | ICIR加权Alpha | ICIR加权 | B类+C类+D类全部A级因子 | 稳健Alpha |
| alpha_xgb | XGBoost Alpha | ML | 全部A级+B级因子 | 非线性Alpha |
| alpha_lgb | LightGBM Alpha | ML | 全部A级+B级因子 | 非线性Alpha |
| alpha_ensemble | 集成Alpha | Stacking | alpha_ic + alpha_icir + alpha_xgb + alpha_lgb | 最终Alpha |

### 7.4 复合Alpha因子评估

复合Alpha因子同样须经 IC/ICIR/分层回测评估，且标准更高：

| 指标 | 复合Alpha阈值 | 单因子阈值 |
|------|-------------|-----------|
| ICIR | > 1.5 | > 0.5 |
| 多空年化 | > 15% | > 5% |
| 多空夏普 | > 2.0 | > 1.0 |
| 最大回撤 | < 10% | < 20% |

---

## 八、因子统计指标存储

### 8.1 统计指标表设计

因子统计指标按月度滚动计算并持久化，用于因子筛选和融合权重更新。

| 字段 | 类型 | 说明 |
|------|------|------|
| factor_id | string | 因子标识 |
| calc_date | date | 计算日期 |
| window | int | 滚动窗口(交易日) |
| ic_mean | float | IC均值 |
| ic_std | float | IC标准差 |
| icir | float | ICIR = ic_mean / ic_std |
| ic_win_rate | float | IC胜率 |
| turnover | float | 因子换手率 |
| decay_half_life | float | IC衰减半衰期 |
| long_short_annual_ret | float | 多空年化收益 |
| long_short_sharpe | float | 多空夏普比率 |
| coverage | float | 因子覆盖度 |
| factor_grade | string | 因子等级(A/B/C/D) |

### 8.2 IC计算规范

```
IC_t = SpearmanRankCorr(factor_value_t, return_{t+1})
IC序列 = {IC_1, IC_2, ..., IC_T}
IC_mean = mean(IC序列)
IC_std  = std(IC序列)
ICIR    = IC_mean / IC_std
IC胜率  = count(IC > 0) / T
```

- 使用 **Spearman秩相关**（非Pearson），对极值和分布形态更鲁棒
- 收益期为 **下一交易日收益**，可扩展至 h=1,5,10,20 日
- 滚动窗口默认 **252个交易日**（约1年）
- 行业中性化后的因子值计算IC

### 8.3 分层回测规范

```
1. 每个截面日，按因子值将股票分为5组（Q1最小 ~ Q5最大）
2. 计算各组等权组合的日收益
3. 多空收益 = Q5收益 - Q1收益（方向为DESC时）
4. 统计多空组合的年化收益、夏普、最大回撤
5. 检验Q1~Q5收益是否单调
```

---

## 九、因子总览

### 9.1 截面因子统计

| 大类 | 子类 | 因子数 | 说明 |
|------|------|--------|------|
| A. 风险因子 | A1 规模 | 2 | Size + 非线性规模 |
| | A2 Beta | 2 | Beta + 下行Beta |
| | A3 波动率 | 8 | 历史波动/残差波动/ATR/布林 |
| | A4 流动性 | 10 | 换手率/Amihud/量比/Barra流动性 |
| B. 基本面因子 | B1 价值 | 11 | PE/PB/PS/EP/BP/CFP/DV |
| | B2 盈利 | 8 | ROE/ROA/ROIC/毛利率/净利率/EPS |
| | B3 成长 | 12 | 同比/环比增长 |
| | B4 质量 | 8 | 现金流/周转率/费用率 |
| | B5 杠杆 | 7 | 资产负债率/流动比率/MLEV |
| C. 技术因子 | C1 动量/反转 | 9 | 动量/反转/Barra动量 |
| | C2 趋势 | 10 | MACD/ADX/BOLL/SAR |
| | C3 超买超卖 | 9 | RSI/KDJ/BIAS/CCI/WR |
| | C4 均线 | 8 | MA/EMA |
| D. 量价因子 | D1 Alpha101 | 6 | WQ代表子集 |
| | D2 Alpha158 | 10 | Qlib代表子集 |
| | D3 资金流 | 6 | 主力/大单净流入 |
| | D4 交互 | 6 | 因子交叉项 |
| E. 缠论连续值 | — | 12 | 笔/中枢/背驰连续值指标 |
| F. K线聚合 | — | 6 | 形态频次/影线/实体比 |
| G. 复合Alpha | — | 6 | 等权/IC/ICIR/ML/集成 |
| **合计** | | **138** | |

### 9.2 非截面信号统计

| 信号类别 | 信号数 | 说明 |
|----------|--------|------|
| 缠论离散信号 | 9 | 分型/买卖点/共振/区间套/趋势方向/中枢位置 |
| K线形态信号 | 21 | 吞没/十字星/锤头线等 |
| **合计** | **30** | 由信号引擎管理 |

---

## 十、与 v3.4 的关键变更

| # | 变更 | 原因 |
|---|------|------|
| 1 | 新增风险/Alpha因子分离 | Barra/Axioma 均区分，风险因子用于风控，Alpha因子用于预测 |
| 2 | 新增因子评估体系（IC/ICIR/分层回测） | 业界标准，因子入库的必要门槛 |
| 3 | 新增复合Alpha因子层 | 多因子融合是机构Alpha的核心来源 |
| 4 | 新增Beta/非线性规模/残差波动率/盈利收益率等因子 | 对齐Barra CNE6风险模型 |
| 5 | 缠论离散信号移出因子库 | 离散信号无截面可比性，归信号层 |
| 6 | K线形态离散信号移出因子库 | 同上，聚合统计保留为因子 |
| 7 | 分类从19个平级改为5大类+子类 | 对齐业界因子分类层次 |
| 8 | 新增因子预处理流水线（去极值/中性化/标准化） | 行业中性化是截面因子处理的必要步骤 |
| 9 | 新增因子统计指标存储设计 | 支持IC/ICIR滚动计算和因子等级评定 |
| 10 | 新增因子等级制度（A/B/C/D） | 因子质量分级管理，淘汰无效因子 |

---

## 附录 A：factor_id 命名规范

| 前缀 | 含义 | 示例 |
|------|------|------|
| cs_ | 截面直取/变换 | cs_pct_chg, cs_turnover |
| z_ | 截面 Z-score | z_turnover, z_main_net_pct |
| ma_ / ema_ | 均线 | ma_5, ema_12 |
| bias_ | 乖离率 | bias_6, bias_12 |
| chan_ | 缠论 | chan_bi_slope, chan_zs_range |
| alpha_ | Alpha101 | alpha_1, alpha_101 |
| cdl_ | K线形态聚合 | cdl_bull_freq_20, cdl_net_score_20 |
| rev_ / mom_ | 反转/动量 | rev_5d, mom_20d |
| hist_vol_ | 历史波动率 | hist_vol_20 |
| alpha_ | 复合Alpha | alpha_ic, alpha_ensemble |

**规则**：小写字母+数字+下划线；全局唯一；注册前系统校验。

---

## 附录 B：因子与信号的数据模型差异

| 维度 | 因子 (Factor) | 信号 (Signal) |
|------|--------------|---------------|
| 存储表 | sdc_factor_value | sdc_signal_value |
| 值类型 | float (连续实数) | int/enum (离散值) |
| 截面可比 | 是 | 否 |
| 评估方式 | IC/ICIR/分层回测 | 胜率/盈亏比/信号回测 |
| 融合方式 | 加权/ML合成 | 逻辑组合/规则叠加 |
| 更新频率 | 日频 | 实时/日频 |
| 生命周期 | 持续存在 | 事件驱动，瞬时或持续N日 |

---

## 附录 C：行业中性化方法

### 方法一：行业均值减去法

```
f_neutral = f_raw - f_industry_mean
```

简单直观，适用于行业间因子分布差异不大的场景。

### 方法二：行业回归法

```
f_raw = Σ(β_i × I_i) + ε
f_neutral = ε  (残差即行业中性化因子)
```

I_i 为行业虚拟变量，ε 为回归残差。更精确，推荐使用。

### 方法三：Barra 正交化

```
f_neutral = f_raw - Σ(w_risk × f_risk)
```

对风险因子做正交化，消除风险暴露。用于构造纯Alpha因子。

---

*本文档定义因子库顶层架构。因子注册表字段、计算实现、流水线设计见相关框架文档。*
