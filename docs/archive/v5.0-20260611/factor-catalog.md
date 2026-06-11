# xqtrader 因子库架构设计

> **版本**: v5.0 | **更新**: 2026-06-11
> **定位**: 因子库顶层架构与分类体系，指导因子注册、评估与融合
> **对齐**: Barra CNE6 / Qlib Alpha158 / 华泰金工

---

## 一、设计原则

### 1.1 核心原则

| 原则 | 说明 |
|------|------|
| 截面优先 | 因子库以截面因子为核心，支持横截面排序与比较 |
| 变化优先 | 因子应反映**信息变化**而非信息状态；原始价格/成交量无截面可比性，取比率/偏离度/变化率 |
| 风险/Alpha分离 | 风险因子解释方差，Alpha因子预测收益，两者分层管理 |
| 评估驱动 | 因子入库须经 IC/ICIR/换手率等统计检验，不合格因子降级或淘汰 |
| 信号独立 | 非截面形态信号不纳入因子库，由信号/策略层独立管理 |

### 1.2 变化优先原则详解

**核心论点**：能预测收益的是信息的变化，而非信息本身。

| 因子层次 | 含义 | 截面可比 | 预测力 | 示例 |
|----------|------|---------|--------|------|
| 原始值 | 信息状态 | 通常否 | 弱 | MA(20)=15.3, MACD_DIF=0.5 |
| 比率/偏离度 | 标准化状态 | 是 | 中 | MA(20)/close-1=-0.03, RSI=65 |
| 一阶导数(Δ) | 信息变化 | 是 | **强** | Δ(MA偏离度), Δ(RSI), Δ(HIST/close) |
| 二阶导数(Δ²) | 变化的变化 | 是 | 过拟合风险 | 极少使用 |

**业界实践**：
- **Qlib Alpha158**：所有价格因子除以 close 归一化，成交量取 Log
- **华泰金工**：技术因子统一取变化率/偏离度，不做原始值直接使用
- **Barra CNE6**：动量取收益变化率，波动率取收益率标准差（非价格标准差）

**构造规则**：

```
原始指标 → 标准化为截面可比形式 → 取一阶导数 → 最终因子

  MA(20) → MA(20)/close - 1 (偏离度) → Δ(偏离度) (偏离度加速回归)
  HIST   → HIST/close (标准化加速度) → Δ(HIST/close) (加速度变化)
  RSI    → RSI (本身0-100可比) → Δ(RSI) (超买超卖加速)
```

### 1.3 因子体系全景

```
┌─────────────────────────────────────────────────────────────┐
│                    因子体系 (Factor Universe)                │
├──────────────────────┬──────────────────────────────────────┤
│   截面因子           │   非截面信号                          │
│   (Cross-Sectional)  │   (Non-Cross-Sectional)              │
│                      │                                      │
│  ┌────────────────┐  │  ┌────────────────────────────────┐  │
│  │ A.风险因子      │  │  │ 缠论信号 (chan_signal)         │  │
│  │  规模/Beta      │  │  │  一买/三买/一卖/三卖           │  │
│  │  波动率/流动性  │  │  │  多级别共振/区间套             │  │
│  ├────────────────┤  │  ├────────────────────────────────┤  │
│  │ B.基本面因子    │  │  │ K线形态信号 (candlestick)      │  │
│  │  价值/盈利      │  │  │  吞没/十字星/锤头线等          │  │
│  │  成长/质量/杠杆 │  │  └────────────────────────────────┘  │
│  ├────────────────┤  │                                      │
│  │ C.技术因子      │  │  → 由信号引擎管理，不入因子库      │
│  │  动量/趋势      │  │  → 输出可量化连续值时可升级为因子    │
│  │  超买超卖/均线  │  │                                      │
│  ├────────────────┤  │                                      │
│  │ D.量价因子      │  │                                      │
│  │  Alpha101/158   │  │                                      │
│  │  资金流/交互    │  │                                      │
│  ├────────────────┤  │                                      │
│  │ E.另类因子      │  │                                      │
│  │  缠论连续值     │  │                                      │
│  │  K线聚合        │  │                                      │
│  ├────────────────┤  │                                      │
│  │ F.复合Alpha     │  │                                      │
│  │  多因子融合     │  │                                      │
│  └────────────────┘  │                                      │
└──────────────────────┴──────────────────────────────────────┘
```

---

## 二、截面因子分类体系

### 2.1 大类划分

参照 Barra CNE6 + Qlib Alpha158 + 华泰金工，截面因子分为 **六大类**：

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
│   └── C4 均线偏离 (Moving Average Deviation)
│
├── D. 量价因子 (Price-Volume Factors)   — 高阶量价关系，Alpha来源
│   ├── D1 Alpha101 (WorldQuant)
│   ├── D2 Alpha158 (Qlib)
│   ├── D3 资金流 (Money Flow)
│   └── D4 交互因子 (Interaction)
│
├── E. 另类因子 (Alternative Factors)    — 缠论/K线聚合
│   ├── E1 缠论连续值
│   └── E2 K线形态聚合
│
└── F. 复合Alpha因子 (Composite Alpha)   — 多因子融合产出
    ├── F1 等权复合
    ├── F2 IC加权复合
    ├── F3 ICIR加权复合
    └── F4 ML融合复合
```

---

### 2.2 A. 风险因子（Risk Factors）

风险因子解释收益方差，是组合风险控制的基石。参照 Barra CNE6，风险因子不做Alpha预测，但必须纳入风险模型。

#### A1 规模因子 (Size)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| cs_log_mv | 对数总市值 | DESC | log(1+total_mv) | Barra Size，对数消除右偏 |
| nl_size | 非线性规模 | ASC | (标准化log_mv)³ 对 Size 正交化取残差 | Barra Non-linear Size，捕捉规模非线性效应 |

#### A2 Beta因子 (Beta)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| beta_250 | 250日Beta | DESC | Cov(ret, mkt_ret)/Var(mkt_ret)，半衰期63日 | Barra Beta，系统性风险暴露 |
| beta_down | 下行Beta | ASC | 负收益日 Cov(ret, mkt_ret)/Var(mkt_ret) | 不对称风险度量，下跌时更敏感 |

#### A3 波动率因子 (Volatility)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| hist_vol_20 | 20日历史波动率 | ASC | STD(20,daily_ret)*sqrt(252) | 短期波动 |
| hist_vol_60 | 60日历史波动率 | ASC | STD(60,daily_ret)*sqrt(252) | 中期波动 |
| downside_vol | 下行波动率 | ASC | STD(负收益日)*sqrt(252) | 不对称波动 |
| dastd | 日收益加权标准差 | ASC | EW_STD(252,daily_ret)，半衰期42日 | Barra DASTD |
| cmra | 累计收益范围 | ASC | log(1+max_cum)-log(1+min_cum)，12月 | Barra CMRA |
| atr_ratio | ATR/价格 | ASC | ATR(14)/close | 标准化波动，截面可比 |
| atr_ratio_delta | ATR/价格变化 | ASC | Δ(ATR(14)/close) | 波动率加速，预测力更强 |
| boll_width | 布林带宽度 | DESC | (upper-lower)/middle | 波动率代理 |

> Barra 波动率因子 = Residual Volatility，由 DASTD + CMRA + hist_vol 正交化后合成。需对 Beta 正交化以减少共线性。

#### A4 流动性因子 (Liquidity)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| cs_turnover | 换手率 | DESC | turnover_rate | 日换手 |
| turnover_f | 流通换手率 | DESC | turnover_rate_f | 流通股换手 |
| z_turnover | 换手率Z-score | DESC | 截面Z-score标准化换手率 | 标准化换手 |
| amihud | Amihud非流动性 | ASC | abs(ret)/amount | 价格冲击 |
| cs_log_amount | 对数成交额 | DESC | log(1+amount) | 成交规模 |
| cs_volume_ratio | 量比 | DESC | volume/Mean(volume,5) | 量能异动 |
| stom | 月换手率 | DESC | log(Σ(21日,V_t/S_t)) | Barra STOM |
| stoq | 季换手率 | DESC | log(mean(3月,exp(STOM))) | Barra STOQ |
| adv_20 | 20日均量偏离 | DESC | MA(volume,20)/volume | 均量偏离度 |
| vol_osc | 量振荡 | DESC | MA(V,5)/MA(V,20) | 量能趋势 |

> Barra 流动性因子由 STOM + STOQ + STOA 等权合成。需对 Size 正交化。

---

### 2.3 B. 基本面因子（Fundamental Factors）

基本面因子是 Alpha 的核心来源，**必须做行业+市值中性化**处理。

> 基本面因子数据来源：`sdc_daily_indicator`（估值指标）、`sdc_fina_indicator`（财务指标）。
> 通过 CrossSectionReader 在评估/合成时按需加载，PIT 前向填充，不在因子计算任务中处理。

#### B1 价值因子 (Value)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| ep_ttm | 盈利收益率TTM | DESC | 1/PE_TTM | Barra Earnings Yield 核心项 |
| bp | 账面市值比 | DESC | 1/PB | Barra Book-to-Price |
| sp_ttm | 销售收益率TTM | DESC | 1/PS_TTM | 销售估值 |
| cfp | 现金收益率 | DESC | 经营现金流/总市值 | Barra Cash Earnings Yield |
| dv_ttm | 股息率TTM | DESC | daily_indicator.dv_ttm | 分红收益TTM |
| pe_ttm | 市盈率TTM | ASC | 总市值/净利润TTM | 高PE=高估值 |
| pb | 市净率 | ASC | daily_indicator.pb | 高PB=高估值 |
| ps_ttm | 市销率TTM | ASC | daily_indicator.ps_ttm | 高PS=高估值 |

> Barra 价值因子 = BP；盈利收益率因子 = EP + CFP 等权合成。PE/PB/PS 为 ASC 方向（高值=高估值），EP/BP/SP/CFP 为 DESC 方向（高值=低估值=买入机会）。

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
| gp_to_assets | 资产毛利率 | DESC | 毛利润/总资产 | Barra GP_TTM，比毛利率更截面可比 |

#### B3 成长因子 (Growth)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| q_or_yoy | 营收同比增长率 | DESC | fina_indicator.q_or_yoy | 营收增长 |
| q_netprofit_yoy | 净利润同比增长率 | DESC | fina_indicator.q_netprofit_yoy | 利润增长 |
| q_dtprofit_yoy | 扣非净利润同比增长率 | DESC | fina_indicator.q_dtprofit_yoy | 核心利润增长 |
| q_op_yoy | 营业利润同比增长率 | DESC | fina_indicator.q_op_yoy | 经营增长 |
| q_ocf_yoy | 经营现金流同比增长率 | DESC | fina_indicator.q_ocf_yoy | 现金流增长 |
| q_roe_yoy | ROE同比增长率 | DESC | fina_indicator.q_roe_yoy | 效率提升 |
| q_netprofitgrow_qoq | 净利润环比增长率 | DESC | fina_indicator.q_netprofitgrow_qoq | 短期加速 |
| q_orgrow_qoq | 营收环比增长率 | DESC | fina_indicator.q_orgrow_qoq | 短期加速 |
| q_opgrow_qoq | 营业利润环比增长率 | DESC | fina_indicator.q_opgrow_qoq | 短期加速 |
| q_roegrow_qoq | ROE环比增长率 | DESC | fina_indicator.q_roegrow_qoq | 效率加速 |

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
| accra | 应计利润/总资产 | ASC | (净利润-经营现金流)/总资产 | Barra ABS，盈利操纵代理 |

#### B5 杠杆因子 (Leverage)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| debt_to_assets | 资产负债率 | ASC | fina_indicator.debt_to_assets | Barra DTOA |
| current_ratio | 流动比率 | DESC | fina_indicator.current_ratio | 短期偿债 |
| eqt_to_talcapital | 归母权益/全部投入资本 | DESC | fina_indicator.eqt_to_talcapital | Barra FMLEV |
| ebit_to_interest | 利息保障倍数 | DESC | fina_indicator.ebit_to_interest | 偿债安全 |
| ocf_to_debt | 经营现金流/负债合计 | DESC | fina_indicator.ocf_to_debt | 现金偿债 |
| mlev | 市场杠杆 | ASC | (总市值+优先股+长期债务)/总市值 | Barra MLEV |

> Barra 杠杆因子 = MLEV + FMLEV + DTOA 等权合成。

---

### 2.4 C. 技术因子（Technical Factors）

> **关键原则**：技术因子取变化率/偏离度，而非原始值。原始价格/均线/指标值无截面可比性。

#### C1 动量/反转因子 (Momentum/Reversal)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| cs_pct_chg | 当日涨跌幅 | DESC | pct_chg 截面 | 日度动量 |
| mom_5d | 5日动量 | DESC | close/close[-5]-1 | 短期动量 |
| mom_20d | 20日动量 | DESC | close/close[-20]-1 | 中期动量 |
| mom_60d | 60日动量 | DESC | close/close[-60]-1 | 长期动量 |
| roc_10 | 10日变化率 | DESC | talib.ROC(10) | 变化率 |
| barra_momentum | Barra动量 | DESC | 12月收益剔除近1月，半衰期126日 | Barra标准动量 |
| barra_strev | Barra短期反转 | ASC | 近1月收益×(-1) | Barra标准反转，与动量不同现象 |

> **注意**：barra_momentum 和 barra_strev 是不同现象——动量是中长期趋势延续，短期反转是1月均值回归。两者可同时为正。不保留简单的 rev_5d/rev_20d（与 mom_5d/mom_20d 完全共线）。

#### C2 趋势因子 (Trend)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| macd_hist_ratio | MACD柱/价格 | DESC | HIST/close | 标准化动量加速度 |
| macd_hist_delta | MACD柱变化率 | DESC | Δ(HIST/close) | 动量加速度变化——"红柱缩短"信号，核心MACD因子 |
| adx_14 | ADX趋势强度 | DESC | talib.ADX(14) | 0-100范围，截面可比 |
| adx_delta | ADX变化 | DESC | Δ(ADX(14)) | 趋势强度加速 |
| adx_plus_di | +DI上升方向 | DESC | talib.PLUS_DI(14) | 0-100范围，上升力度 |
| adx_minus_di | -DI下降方向 | ASC | talib.MINUS_DI(14) | 0-100范围，下降力度 |
| boll_position | 布林带位置 | DESC | (close-lower)/(upper-lower) | 0-1标准化位置，截面可比 |
| boll_position_delta | 布林带位置变化 | DESC | Δ(boll_position) | 位置加速变化——从下轨回归信号 |
| boll_width | 布林带宽度 | DESC | (upper-lower)/middle | 波动率代理 |
| sar_deviation | SAR偏离度 | DESC | Δ(SAR/close) | 趋势跟踪偏离变化 |

> **删除的因子及原因**：
> - `macd_dif`, `macd_dea`：原始值无截面可比性，信息已包含在 macd_hist_ratio 中
> - `macd_hist`：未标准化，改为 macd_hist_ratio（除以close）
> - `boll_upper/middle/lower`：原始价格值无截面可比性，改为 boll_position（0-1标准化）
> - `sar`：原始值无截面可比性，改为 sar_deviation（偏离度变化率）

#### C3 超买超卖因子 (Oscillator)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| rsi_14 | RSI(14) | DESC | talib.RSI(14) | 0-100范围，截面可比 |
| rsi_delta_14 | RSI(14)变化 | DESC | Δ(RSI(14)) | 超买超卖加速——RSI从60→70比RSI=70更有信息量 |
| kdj_k | KDJ-K值 | DESC | talib.STOCH(K=9,slowK=3) | 0-100范围，短线方向 |
| kdj_d | KDJ-D值 | DESC | K的3日平滑 | 0-100范围，中线方向 |
| kdj_j | KDJ-J值 | DESC | 3K-2D | 超买超卖极端 |
| bias_6 | BIAS(6)乖离率 | DESC | (C-MA6)/MA6 | 短期偏离，已是比率形式 |
| bias_12 | BIAS(12)乖离率 | DESC | (C-MA12)/MA12 | 中期偏离 |
| bias_24 | BIAS(24)乖离率 | DESC | (C-MA24)/MA24 | 长期偏离 |
| cci_14 | CCI(14) | DESC | talib.CCI(14) | 顺势指标 |
| wr_14 | WR(14)威廉指标 | ASC | talib.WILLR(14) | 0-100范围，超买超卖 |

#### C4 均线偏离因子 (Moving Average Deviation)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| ma_bias_5 | MA5偏离度 | DESC | MA(5)/close - 1 | 短期偏离 |
| ma_bias_10 | MA10偏离度 | DESC | MA(10)/close - 1 | 短期偏离 |
| ma_bias_20 | MA20偏离度 | DESC | MA(20)/close - 1 | 中期偏离 |
| ma_bias_60 | MA60偏离度 | DESC | MA(60)/close - 1 | 长期偏离 |
| ma_bias_delta_20 | MA20偏离度变化 | DESC | Δ(MA(20)/close - 1) | 偏离度加速回归——核心均线因子 |

> **删除的因子及原因**：
> - `ma_5` ~ `ma_250`：原始均线值无截面可比性（MA=15.3 vs MA=150.2 不可比），改为 MA/close - 1 偏离度
> - `ma_30`, `ma_120`, `ma_250`：与 ma_bias_20/60 高度共线，减少冗余
> - `ema_12`, `ema_26`：MACD 内部组件，信息已包含在 macd_hist_ratio 中

---

### 2.5 D. 量价因子（Price-Volume Factors）

#### D1 Alpha101 因子 (WorldQuant)

> 从 101 个因子中选取被业界广泛验证的 6 个代表性因子。

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| alpha_1 | 量价偏离极值日 | DESC | rank(ts_argmax((vwap-0.5*open)^2,5)) | WQ#1，下跌时波动放大 |
| alpha_12 | 量增价跌反转 | DESC | sign(Δvolume)×(-Δ(close-open)) | WQ#12，量价背离 |
| alpha_33 | 收开盘比衰减 | DESC | -rank(decay_linear(close/open,5)) | WQ#33，均值回归 |
| alpha_41 | 几何均价VWAP偏离 | DESC | sqrt(high×low)-vwap | WQ#41，定价偏差 |
| alpha_55 | 日内涨跌量相关 | DESC | -corr(rank(close-open),rank(volume),5) | WQ#55，量价负相关 |
| alpha_101 | 日内K线形态 | DESC | (close-open)/(high-low+0.001) | WQ#101，日内方向强度 |

#### D2 Alpha158 因子 (Qlib)

> 选取 Alpha158 中最具代表性的 10 个因子。所有价格因子均除以 close 归一化。

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| kmid_5 | 5日K线实体均值 | DESC | MA(5,(C-O)/O) | 实体比例 |
| klen_5 | 5日K线振幅均值 | DESC | MA(5,(H-L)/O) | 振幅 |
| kup2_5 | 5日上影线占比均值 | ASC | MA(5,(H-max(O,C))/(H-L)) | 上影线=压力 |
| klow2_5 | 5日下影线占比均值 | DESC | MA(5,(min(O,C)-L)/(H-L)) | 下影线=支撑 |
| rsv_9 | 9日随机值 | DESC | (C-L9)/(H9-L9) | KDJ基础 |
| cntp_20 | 20日上涨天数占比 | DESC | count(C>C1,20)/20 | 涨跌比 |
| imax_20 | 20日最高价位置 | ASC | argmax(C,20)/20 | 高点位置 |
| roc5_close | 5日收盘变化率 | DESC | C/C[-5]-1 | 变化率 |
| std20_close | 20日收盘波动率 | ASC | STD(20,C)/C | 波动率代理 |
| corr_pv_10 | 10日价量相关 | ASC | corr(close,Log(volume+1),10) | 价量关系 |

#### D3 资金流因子 (Money Flow)

> **核心原则**：资金流因子必须使用**占比/比率**形式，绝对金额无截面可比性（大盘股天然流入大）。
> 参照华泰金工研究：资金流因子需剥离反转因素（MOD修正），单数维度优于金额维度，时段分化（尾盘信号更强）。

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| cs_main_net_pct | 主力净流入占比 | DESC | main_net_pct | 主力动向，已是比率 |
| cs_net_mf_pct | 全部净流入占比 | DESC | net_mf_amt/amount | 全市场资金净方向 |
| huge_net_pct | 超大单净流入占比 | DESC | huge_net_amt/amount | 大资金动向 |
| big_net_pct | 大单净流入占比 | DESC | big_net_amt/amount | 中大资金动向 |
| z_main_net_pct | 主力净流入Z-score | DESC | 截面Z-score标准化 main_net_pct | 标准化主力 |
| main_net_pct_close | 尾盘主力净流入占比 | DESC | 尾盘主力净流入/尾盘成交额 | 尾盘资金意图，信号更强 |
| main_net_pct_open | 开盘主力净流入占比 | DESC | 开盘主力净流入/开盘成交额 | 开盘资金意图 |

> **删除的因子及原因**：
> - `cs_net_mf_amt`, `huge_net_amt`, `big_net_amt`, `main_net_amt`：绝对金额无截面可比性，改为占比形式
> - `main_net_amt_ma_5/10/20`：绝对金额MA同样无截面意义，且与原始值高度共线
>
> **新增因子说明**：
> - `cs_net_mf_pct`：替代 cs_net_mf_amt，改为净流入/成交额
> - `huge_net_pct`, `big_net_pct`：替代绝对金额，改为净流入/成交额
> - `main_net_pct_open/close`：华泰研究发现尾盘资金流信号更强（IR=0.78），开盘次之

#### D4 交互因子 (Interaction)

| factor_id | 展示名 | 方向 | 计算逻辑 | 说明 |
|-----------|--------|------|----------|------|
| mom_vol_cross | 动量×波动 | DESC | momentum × atr_ratio | 非线性交互 |
| adx_rsi_cross | ADX×RSI偏离 | DESC | ADX × (RSI-50)/50 | 趋势+超买 |
| vol_ratio_mom_cross | 量比×动量 | DESC | cs_volume_ratio × momentum | 量价配合 |
| rsi_bbands_cross | RSI×布林位置 | DESC | RSI × boll_position | 超买+通道 |
| macd_adx_cross | MACD×ADX | DESC | macd_hist_ratio × ADX | 趋势确认 |
| vol_mom_accel_cross | 波动×动量加速度 | DESC | atr_ratio × macd_hist_delta | 波动加速 |

---

### 2.6 E. 另类因子（Alternative Factors）

#### E1 缠论连续值因子

> 仅保留缠论输出中具有截面可比性的连续值指标。离散信号归入信号层。

| factor_id | 展示名 | group_id | 方向 | 计算逻辑 | 说明 |
|-----------|--------|----------|------|----------|------|
| chan_fractal_strength | 分型强度 | chan_fractal | DESC | 极值与两侧差之和 | 分型显著度 |
| chan_bi_length | 笔长度 | chan_bi | DESC | abs(顶H-底L)/close | 标准化趋势幅度 |
| chan_bi_kcount | 笔内K线数 | chan_bi | DESC | 一笔内K线数 | 趋势持续 |
| chan_bi_slope | 笔斜率 | chan_bi | DESC | (终点价-起点价)/K线数/close | 标准化趋势强度 |
| chan_bi_amplitude | 笔振幅 | chan_bi | ASC | 笔内最大回撤/笔长度 | 趋势质量 |
| chan_bi_strength | 笔强度 | chan_bi | DESC | 笔长度/笔内K线数 | 趋势效率 |
| chan_zs_height_ratio | 中枢高度比 | chan_zs | DESC | (ZG-ZD)/price | 标准化中枢 |
| chan_zs_range | 中枢区间 | chan_zs | DESC | (ZG-ZD)/price | 标准化震荡幅度 |
| chan_divergence_ratio | 背驰强度 | chan_div | DESC | A_curr/A_prev面积比 | 背驰程度 |
| chan_macd_area | MACD面积 | chan_div | DESC | 笔内MACD柱状图绝对值之和/close | 标准化动能衰减 |

> 缠论因子中的价格相关值（笔长度、笔斜率、中枢区间、MACD面积）均除以 close 标准化，确保截面可比。删除 chan_zs_zg/zd（原始价格值无截面可比性）。

#### E2 K线形态聚合因子

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

### 2.7 F. 复合Alpha因子（Composite Alpha）

> 由多因子融合产出，需经评估后才能入库。

| factor_id | 展示名 | 融合方法 | 输入因子 | 说明 |
|-----------|--------|---------|---------|------|
| alpha_eq | 等权Alpha | 等权 | B类+C类+D类全部A级因子 | 基线Alpha |
| alpha_ic | IC加权Alpha | IC加权 | B类+C类+D类全部A级因子 | 自适应Alpha |
| alpha_icir | ICIR加权Alpha | ICIR加权 | B类+C类+D类全部A级因子 | 稳健Alpha |
| alpha_xgb | XGBoost Alpha | ML | 全部A级+B级因子 | 非线性Alpha |
| alpha_lgb | LightGBM Alpha | ML | 全部A级+B级因子 | 非线性Alpha |
| alpha_ensemble | 集成Alpha | Stacking | alpha_ic + alpha_icir + alpha_xgb + alpha_lgb | 最终Alpha |

---

## 三、非截面信号层

### 3.1 信号层定位

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

### 3.2 信号与因子的关系

- 信号可**聚合**为因子（频次、比率、强度评分）
- 因子**不可**还原为信号（聚合不可逆）
- 信号可直接驱动交易策略，不必须经过因子层

---

## 四、因子评估体系

### 4.1 评估指标

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

### 4.2 评估流程

```
因子候选
  │
  ▼
① 预处理
  缺失值填充(行业均值) → 去极值(MAD, n=5) → 行业+市值中性化 → Z-score标准化
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

### 4.3 因子等级

| 等级 | 标准 | 用途 |
|------|------|------|
| **A级** | ICIR > 1.0, 多空年化 > 10%, 换手率 < 50% | 核心Alpha因子，可独立使用 |
| **B级** | ICIR > 0.5, 多空年化 > 5%, 换手率 < 70% | 辅助Alpha因子，需组合使用 |
| **C级** | ICIR > 0.3, 多空年化 > 3% | 弱Alpha因子，仅作ML特征 |
| **D级** | ICIR < 0.3 或 多空年化 < 3% | 无效因子，淘汰或降级为信号 |

---

## 五、因子预处理流水线

### 5.1 标准流程（华泰/Barra 共识）

```
原始因子值
  │
  ▼
① 缺失值处理
  行业均值填充 或 丢弃
  │
  ▼
② 去极值 (Winsorize)
  MAD法: |x - median| > 5×MAD → clip
  （MAD法比3σ法更稳健，不受极端值影响）
  │
  ▼
③ 行业+市值中性化
  因子值对行业哑变量 + log(市值) 回归取残差
  （基本面因子必做，技术因子建议做，资金流因子必做）
  │
  ▼
④ 标准化 (Z-score)
  (x - μ) / σ，截面标准化
  │
  ▼
⑤ 正交化 (可选，Barra规范)
  对风险因子回归取残差，消除风险暴露
  正交化顺序：Size → Beta → Momentum → Volatility → ...
  │
  ▼
加工因子值 → 用于融合
```

> **顺序不可调换**：先标准化再去极值会扭曲均值方差；先中性化再处理异常值会影响回归系数。

### 5.2 融合方法

| 方法 | 公式 | 优点 | 缺点 | 适用场景 |
|------|------|------|------|---------|
| **等权** | α = (1/N) Σ f_i | 简单稳健 | 忽略因子质量差异 | 因子数量少、质量相近 |
| **IC加权** | α = Σ(IC_i × f_i) / Σ\|IC_i\| | 赋权与预测力成正比 | IC不稳定时权重波动 | 因子IC稳定 |
| **ICIR加权** | α = Σ(ICIR_i × f_i) / Σ\|ICIR_i\| | 兼顾预测力与稳定性 | 需较长IC历史 | 因子ICIR分化明显 |
| **ML融合** | XGBoost/LightGBM/NN | 捕捉非线性 | 过拟合风险 | 因子数量多、交互复杂 |

### 5.3 复合Alpha因子评估

复合Alpha因子同样须经 IC/ICIR/分层回测评估，且标准更高：

| 指标 | 复合Alpha阈值 | 单因子阈值 |
|------|-------------|-----------|
| ICIR | > 1.5 | > 0.5 |
| 多空年化 | > 15% | > 5% |
| 多空夏普 | > 2.0 | > 1.0 |
| 最大回撤 | < 10% | < 20% |

---

## 六、因子统计指标存储

### 6.1 统计指标表设计

| 字段 | 类型 | 说明 |
|------|------|------|
| factor_id | string | 因子标识 |
| pool_id | string | 样本池标识 |
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

### 6.2 IC计算规范

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

### 6.3 分层回测规范

```
1. 每个截面日，按因子值将股票分为5组（Q1最小 ~ Q5最大）
2. 计算各组等权组合的日收益
3. 多空收益 = Q5收益 - Q1收益（方向为DESC时）
4. 统计多空组合的年化收益、夏普、最大回撤
5. 检验Q1~Q5收益是否单调（Spearman > 0.8）
```

---

## 七、因子总览

### 7.1 截面因子统计

| 大类 | 子类 | 因子数 | 说明 |
|------|------|--------|------|
| A. 风险因子 | A1 规模 | 2 | Size + 非线性规模 |
| | A2 Beta | 2 | Beta + 下行Beta |
| | A3 波动率 | 8 | 历史波动/Barra波动/ATR比率/布林 |
| | A4 流动性 | 10 | 换手率/Amihud/量比/Barra流动性 |
| B. 基本面因子 | B1 价值 | 8 | EP/BP/SP/CFP/DV + PE/PB/PS |
| | B2 盈利 | 8 | ROE/ROA/ROIC/毛利率/净利率/GP |
| | B3 成长 | 10 | 同比/环比增长 |
| | B4 质量 | 8 | 现金流/周转率/应计利润 |
| | B5 杠杆 | 6 | 资产负债率/流动比率/MLEV/FMLEV |
| C. 技术因子 | C1 动量/反转 | 7 | 动量/Barra动量/反转 |
| | C2 趋势 | 10 | MACD标准化/ADX/BOLL位置/SAR偏离 |
| | C3 超买超卖 | 10 | RSI+变化/KDJ/BIAS/CCI/WR |
| | C4 均线偏离 | 5 | MA偏离度+偏离度变化 |
| D. 量价因子 | D1 Alpha101 | 6 | WQ代表子集 |
| | D2 Alpha158 | 10 | Qlib代表子集 |
| | D3 资金流 | 7 | 占比形式+时段分化 |
| | D4 交互 | 6 | 因子交叉项 |
| E. 另类因子 | E1 缠论连续值 | 10 | 笔/中枢/背驰标准化指标 |
| | E2 K线聚合 | 6 | 形态频次/影线/实体比 |
| F. 复合Alpha | — | 6 | 等权/IC/ICIR/ML/集成 |
| **合计** | | **131** | |

### 7.2 非截面信号统计

| 信号类别 | 信号数 | 说明 |
|----------|--------|------|
| 缠论离散信号 | 9 | 分型/买卖点/共振/区间套/趋势方向/中枢位置 |
| K线形态信号 | 21 | 吞没/十字星/锤头线等 |
| **合计** | **30** | 由信号引擎管理 |

---

## 附录 A：factor_id 命名规范

| 前缀 | 含义 | 示例 |
|------|------|------|
| cs_ | 截面直取/变换 | cs_pct_chg, cs_turnover, cs_log_mv |
| z_ | 截面 Z-score | z_turnover, z_main_net_pct |
| ma_bias_ | 均线偏离度 | ma_bias_5, ma_bias_20 |
| bias_ | 乖离率 | bias_6, bias_12 |
| hist_vol_ | 历史波动率 | hist_vol_20 |
| macd_ | MACD相关 | macd_hist_ratio, macd_hist_delta |
| boll_ | 布林带相关 | boll_position, boll_width |
| atr_ | ATR相关 | atr_ratio, atr_ratio_delta |
| rsi_ | RSI相关 | rsi_14, rsi_delta_14 |
| adx_ | ADX相关 | adx_14, adx_delta |
| chan_ | 缠论 | chan_bi_slope, chan_zs_height_ratio |
| alpha_ | Alpha101/复合Alpha | alpha_1, alpha_ic |
| cdl_ | K线形态聚合 | cdl_bull_freq_20, cdl_net_score_20 |
| mom_ | 动量 | mom_5d, mom_20d |
| barra_ | Barra标准因子 | barra_momentum, barra_strev |

**规则**：小写字母+数字+下划线；全局唯一；注册前系统校验。

---

## 附录 B：因子与信号的数据模型差异

| 维度 | 因子 (Factor) | 信号 (Signal) |
|------|--------------|---------------|
| 存储表 | fac_factor_value | fac_signal_value |
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

### 方法二：行业+市值回归法（推荐）

```
f_raw = β₁×industry_dummies + β₂×log(market_cap) + α + ε
f_neutral = ε  (残差即中性化因子)
```

华泰/Barra 标准做法，同时消除行业和规模效应。

### 方法三：Barra 正交化

```
f_neutral = f_raw - Σ(w_risk × f_risk)
```

对风险因子做正交化，消除风险暴露。用于构造纯Alpha因子。正交化顺序：Size → Beta → Momentum → Volatility → 其余。

---

*本文档定义因子库顶层架构。因子注册表字段、计算实现、流水线设计见 factor-architecture.md。*
