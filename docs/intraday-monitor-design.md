# 盘内行情监控系统设计

> 版本：v1.0  日期：2026-07-09
> 状态：设计中，待评审
> 关联文档：[trading-system-design.md](trading-system-design.md) §9、[trading-improvement-plan.md](trading-improvement-plan.md) Phase 1、[websocket.md](websocket.md)、[rule-strategy-design.md](rule-strategy-design.md)

## 一、背景与定位

### 1.1 当前缺口

xqtrader 当前交易闭环为「**日频决策 + 事件驱动执行 + 紧急 Kill Switch**」三段式：

- 决策流 `watchlist_after_close_decision_flow`：T 日盘后 1 次，生成 `td_pre_order`（status=pending_approval）
- 执行流 `pre_order_execution_flow`：人工审批通过后逐单触发，提交至 QMT/SimulatedMatching
- Kill Switch：驾驶舱按钮 / 风控 fatal，绕过 Workflow 紧急全平

**结构性缺口**（[trading-improvement-plan.md](trading-improvement-plan.md) §一）：
1. 下单后无实时成交回报、持仓不自动同步 → 实盘半闭环
2. 无日内风控熔断 → 跳空、急跌无法应对
3. 无分钟级行情采集与存储 → 无法做盘中信号、无法事后归因
4. WebSocket 高频 Topic（positions/orders/risk）无生产者

### 1.2 设计目标

构建「**分钟级事件驱动 + TimescaleDB 落库 + asyncio 专用 worker + Celery 盘后**」混合架构，补齐盘内监控半环，使交易系统从「半闭环」走向「全闭环」。

### 1.3 设计原则

1. **决策与监控分离**：因子/Alpha 信号 T 日盘后批量算（[trading-product-design.md](trading-product-design.md) §1.2），**不在盘内重算**；盘内只做执行层监控（成交确认、持仓同步、风控熔断、量价异动告警）
2. **独立轻量后台任务**：盘内监控**非 Workflow 节点**，仅交易时段运行，以已审批 `td_pre_order` 目标权重为只读剧本（[trading-system-design.md](trading-system-design.md) §9 L368）
3. **复用现有扩展点**：RulePlugin + OnDemandComputeRegistry + WS SPI + KillSwitchService 单例 + QmtDataCollector
4. **不引入重型组件**：不引入 Kafka/Flink，用 Redis Pub/Sub 解耦事件
5. **无 Level-2 权限适配**：基于 QMT Level-1 快照 + Tushare 日级资金流替代 Level-2 方案

## 二、业界主流做法（参考）

### 2.1 频率与落库

| 维度 | 业界主流 | 本项目采纳 |
|---|---|---|
| 监控频率 | 分钟级为事实标准（聚宽/米筐/Alpaca/Backtrader），Tick 级仅高频做市 | 分钟级为主，Tick 级仅重点标的 |
| 落库策略 | 分钟线落库 TimescaleDB，Tick 落库仅机构 | 1m OHLCV 落库，Tick 不落库 |
| 生命周期 | Continuous Aggregate 预聚合 + retention/compression 自动管理 | 同上 |

### 2.2 架构模式

- **事件驱动为主**：WebSocket 推送 → asyncio 事件循环 → 分钟线合成完毕事件 → 触发策略回调（聚宽/米筐/QMT/Alpaca/Backtrader 均如此）
- **定时调度为辅**：Celery Beat 负责盘前初始化、盘后对账、定时数据同步
- **机构级高吞吐**：Kafka + Flink CEP（本项目不采用，过重）
- **个人级简化**：Redis Pub/Sub 解耦 + asyncio 专用 worker

### 2.3 信号策略（无 Level-2 适配）

| 策略 | 业界做法 | 本项目（无 Level-2） |
|---|---|---|
| VWAP/TWAP | 执行基准 + 支撑阻力 + 方向信号 | ✅ 基于 1m OHLCV 累积 |
| 分钟动量/突破 | 突破均线 + 阶段新高 + 量放大 | ✅ 基于 1m + 5m Continuous Agg |
| 量价异动 | Tick 级大单/急涨急跌 | ✅ Level-1 快照（5 档盘口 + 1 笔成交）做分钟级异动 |
| 资金流分级 | Level-2 逐笔拆超大/大/中/小单 | ❌ 改用 Tushare moneyflow_dc 日级（已有，盘后算） |
| 集合竞价信号 | 9:20–9:25 真实资金态度 | ✅ 基于 QMT 快照 |
| 涨跌停/停牌监控 | A 股特有，影响下单可行性 | ✅ 基于 1m 快照 |

## 三、总体架构

### 3.1 组件视图

```
┌─────────────────────────────────────────────────────────────────────┐
│  FastAPI 进程（lifespan 内常驻 asyncio 后台任务 IntradayMonitorTask） │
│                                                                     │
│  数据接入层（监听 Redis intraday.control 信号启停）                  │
│  - xtquant subscribe_quote(period='1m')  -> 分钟线合成器              │
│  - xtquant subscribe_whole_quote         -> 全推快照（异动扫描，不落库）│
│  - get_full_tick                          -> 重点标的 Tick（不落库）   │
│  └────────────┬──────────────────────────┬─────────────────────────┘  │
│               │                          │                            │
│      ┌────────▼─────────┐      ┌─────────▼──────────┐                 │
│      │ 落库 TimescaleDB │      │ Redis Pub/Sub 发布 │                 │
│      │ sdc_candlestick_1m│     │ "minute_bar.ready" │                 │
│      │ + Continuous Agg  │      │ "tick_anomaly"     │                 │
│      │   5m/15m/30m/1h  │      └─────────┬──────────┘                 │
│      └────────┬──────────┘                │                          │
│               │                          │                          │
│      ┌────────▼──────────┐     ┌──────────▼──────────────┐          │
│      │ OrderConfirmService│    │ 信号计算层（asyncio）     │          │
│      │ (事件+30s轮询兜底) │    │ - VWAP/TWAP              │          │
│      │ -> td_order/td_trade│   │ - 5m MACD/布林/双均线/动量 │          │
│      └────────┬──────────┘    │ - 15m 唐奇安/ATR         │          │
│               │               │ - 1m 集合竞价/涨跌停监控  │          │
│      ┌────────▼──────────┐    │ - 量价异动告警            │          │
│      │ PositionSyncService│   └────────┬─────────────────┘          │
│      │ (1m 轮询 QMT)     │             │                            │
│      │ -> td_position 快照│      ┌────▼─────────────────────┐       │
│      └────────┬──────────┘     │ IntradayRiskMonitor       │       │
│               │                │ (1m 轮询 + 事件触发)       │       │
│               │                │ - 日内亏损熔断             │       │
│               │                │ - 权重偏离告警             │       │
│               │                │ - 超阈值->KillSwitch       │       │
│               │                └────────┬──────────────────┘       │
│               └─────────────────────────┬┘                         │
│                                         │                          │
│      ┌──────────────────────────────────▼──────────────────────┐   │
│      │ WS 推送层（复用现有 SPI 框架，同进程直通）              │   │
│      │ - ws.trading.signals (信号事件)                        │   │
│      │ - ws.trading.orders / trades (成交回报)                │   │
│      │ - ws.trading.positions (持仓偏离告警)                  │   │
│      │ - ws.trading.risk (风控/熔断事件)                        │   │
│      └────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

Celery Beat（独立进程，仅定时控制信号）：
- 09:15 publish intraday.start -> 唤醒 FastAPI 内监控任务
- 15:30 publish intraday.stop  -> 优雅停止
- 盘后全量补全 + 对账 + 因子重算（手动触发）
- 龙虎榜/北向资金定时抓取
```

### 3.2 进程边界

| 进程 | 职责 | 启停 |
|---|---|---|
| **FastAPI** | API 编排、监控查询、手动干预、**盘中监控 asyncio 任务** | 长驻 |
| Celery Beat | 定时调度（09:15/15:30 发控制信号） | 长驻 |
| Celery Worker | 盘后批处理、数据补全、因子重算 | 长驻 |
| Redis | Pub/Sub 事件解耦 + 控制信号 + 缓存 | 长驻 |

> **启动策略**：监控控制信号（09:15/15:30）由 Celery Beat 自动触发；盘后回补（`intraday_reconcile`）属采集任务，遵循手动启动约束（`enabled: false`），需用户手动触发。

**关键约束**：FastAPI 不在请求线程内做长耗时计算（监控任务在独立 asyncio task）；监控任务不嵌套 `asyncio.run()`（[开发测试规范.md](.trae/rules/开发测试规范.md)）；Celery 不跑毫秒级实时（Beat tick 轮询 + broker 投递开销不适合）。

## 四、关键设计决策

### 4.1 落库范围

**决策**：落库仅「动态股票池」，行情订阅可全市场。

| 维度 | 范围 | 频率 | 落库 |
|---|---|---|---|
| 动态股票池 | **全部账户去重自选池** + 持仓 + 已审批 pre_order（约 50-300 只） | 1m bar 事件 | ✅ `sdc_candlestick_1m` |
| 全市场快照 | 全 A 股 | 3s 全推 | ❌ 内存扫描异动，命中后入股票池 |
| 重点标的 Tick | 持仓 + 已审批 pre_order | 事件回调 | ❌ 仅内存检测异动 |

**动态股票池来源**（[watchlist.py](../src/xqtrader/domain/trading/models/watchlist.py) L13 `account_id unique=True`，模拟盘与实盘账户自选池独立存储）：

```python
# 1. 获取全部账户去重自选池（含模拟盘 account_type=paper 与实盘 account_type=live）
watchlists = await Watchlist.filter(limit=None)
watchlist_ids = [w.id for w in watchlists]
items = await WatchlistItem.filter(watchlist_id__in=watchlist_ids, is_enabled=1, limit=None)
watchlist_symbols = list({item.symbol for item in items})  # 去重

# 2. 叠加持仓 + 已审批 pre_order
position_symbols = [...]   # 从 td_position 查
pre_order_symbols = [...]   # 从 td_pre_order where status in (pending_approval, approved) 查
dynamic_pool = list(set(watchlist_symbols + position_symbols + pre_order_symbols))
```

**理由**：
- 全市场落库成本过高（5000 只 × 240 根/日 = 120 万根/日，3 月热数据 ≈ 7000 万行，写入与存储压力大）
- 动态股票池已覆盖所有交易决策场景
- 全推快照在内存中扫描异动，命中后再加入股票池落库，平衡覆盖度与成本

### 4.2 存储设计

**决策**：单 hypertable + compression policy + retention policy + Continuous Aggregate，**不应用层分表**。

当前 dal-orm 的 [timescale.py](../src/framework/dal/timescale.py) 基于 TimescaleDB 单 hypertable 模型，[partition.py](../src/framework/dal/partition.py) 已标注 `[DEPRECATED]`。TimescaleDB 的设计哲学是「单表 + chunk 自动分区 + compression policy」，原生支持冷热数据管理，无需应用层分表。

**生命周期分层**：

```
1m 原始表 (sdc_candlestick_1m)
├─ 0-3 月：热数据（不压缩，支持回测复现、事中归因）
├─ 3 月-2 年：温数据（compress_after='3 months'，压缩 90%+，compress_segmentby='symbol'）
└─ >2 年：自动 drop（add_retention_policy INTERVAL '2 years'）

Continuous Aggregate（永久保留，替代降采样）
├─ 5m   (sdc_candlestick_5m_cagg)   - 用于盘中 MACD/布林/双均线/动量信号
├─ 15m  (sdc_candlestick_15m_cagg)  - 用于唐奇安/ATR 止损
├─ 30m  (sdc_candlestick_30m_cagg)  - 用于缠论笔识别（Phase 2，需改造 chanpy 支持 K_30M）
└─ 1h   (sdc_candlestick_1h_cagg)   - 用于缠论段识别
```

**Continuous Aggregate 刷新策略**（针对本地硬件 9950X + 48G 优化）：
- `schedule_interval => INTERVAL '5 minutes'`（非 1 分钟，降低 job 调度开销，5 分钟延迟可接受）
- `start_offset => INTERVAL '3 days'`，`end_offset => INTERVAL '5 minutes'`
- 增量刷新只处理新增 chunk（约 50-300 根/分钟），CPU 开销 <1ms，内存接近 0
- 使用 `materialized_only=false` 实时聚合，最新 chunk 查询时实时合并

**硬件说明**：5060Ti 显卡对本场景无用（TimescaleDB 不支持 GPU 加速）；9950X 16 核 + 48G 内存绰绰有余。

**chunk_interval**：`1 day`（1m 数据每日约 240 × 股票数行，1 day chunk 便于按日查询与清理）

### 4.3 盘中信号策略（多周期组合）

**决策**：不止 VWAP，采用「多周期组合」策略，覆盖 1m / 5m / 15m / 30m / 1h。

| 周期 | 策略 | 数据源 | Phase | 实现要点 |
|---|---|---|---|---|
| 1m | VWAP 监控（执行基准 + 支撑阻力 + 方向信号） | sdc_candlestick_1m | 2.0 | 累积 amount/volume，上穿/下穿信号 |
| 1m | 集合竞价信号（9:20-9:25 真实资金态度） | QMT 快照 | 2.0 | 仅集合竞价段订阅 |
| 1m | 涨跌停/停牌监控 | sdc_candlestick_1m | 2.0 | pct_chg 触及 ±10%/±20%/±30% 告警 |
| 5m | MACD 金叉死叉 | Continuous Aggregate 5m | 2.1 | 复用 `_compute_macd`，talib 不校验频率 |
| 5m | 布林带突破 | Continuous Aggregate 5m | 2.1 | 复用 `_compute_bollinger` |
| 5m | 双均线交叉（SMA5/SMA20） | Continuous Aggregate 5m | 2.1 | 复用 `_compute_ma` |
| 5m | 动量突破（close.shift(10)） | Continuous Aggregate 5m | 2.1 | 复用 `_compute_mom_10d`，参数改 10 根 5m K 线 |
| 15m | 唐奇安通道突破 | Continuous Aggregate 15m | 2.1 | 复用 `_compute_donchian` |
| 15m | ATR 止损 | Continuous Aggregate 15m | 2.1 | 复用 `_compute_atr_14` |
| 30m/1h | 缠论笔/段识别 | Continuous Aggregate 30m/1h | 3.0 | **需改造** [chanlun_signal.py](../src/xqtrader/domain/trading/backtest/plugins/chanlun_signal.py) L106 `KL_TYPE.K_DAY` -> 支持 `K_30M`/`K_1H` |
| - | 量价异动（急涨急跌 + 量脉冲） | 1m + Level-1 快照 | 2.1 | 无 Level-2，用 5 档盘口 + 1 笔成交估算 |

**OnDemand 因子分钟级适配性**（调研结论）：

| 因子 | 能否接受分钟级 | 说明 |
|---|---|---|
| MACD / 布林 / 双均线 / 动量 / ATR / 唐奇安 | ✅ | 纯 talib/pandas，不校验频率，传 close/high/low 序列即可 |
| 神奇九转 | ⚠️ | 技术上可运行，但语义"连续9个交易日"会变"连续9根K线"，需重新定义语义 |
| 缠论 | ❌（当前） | [chanlun_signal.py](../src/xqtrader/domain/trading/backtest/plugins/chanlun_signal.py) L106 硬编码 `KL_TYPE.K_DAY`，Phase 3 改造 |

**关键原则**：盘中信号策略复用现有 `OnDemandComputeRegistry` 注册表与 `RulePlugin` ABC，**不新建并行体系**。仅缠论需新增分钟级版本 `compute_chanlun_signals_min(df, kl_type)`，与日级版本并存。

### 4.4 无 Level-2 权限适配

| 策略 | 原 Level-2 方案 | 替代方案 |
|---|---|---|
| 量价异动 | Tick 逐笔大单检测 | QMT `get_full_tick` Level-1 快照（5 档盘口 + 1 笔成交），分钟级急涨急跌 + 量脉冲 |
| 资金流分级 | Level-2 逐笔拆超大/大/中/小单 | Tushare `moneyflow_dc` 日级（已有，盘后算），不做盘中实时资金流 |
| 大单监测 | Level-2 十档盘口 | 仅对重点标的做快照级大单估算（成交额/均量比） |

**结论**：无 Level-2 不影响 Phase 1.0-1.1（成交确认 + 持仓同步）与 Phase 2（VWAP/动量/异动/集合竞价/MACD/布林/双均线/唐奇安/ATR）。仅 Phase 3 的「资金流分级共振」需 Level-2，本期不实施。

### 4.5 进程管理方案

**决策**：采用「FastAPI lifespan 内常驻 asyncio 后台任务」，**不使用独立 asyncio worker 进程**。

**调研结论**：
- 当前架构无 supervisor/systemd，无 `subprocess.Popen` 先例
- [framework/ws/redis_listener.py](../src/framework/ws/redis_listener.py) 已有「后台线程 + asyncio 桥接」模式
- [ws/spi/](../src/xqtrader/ws/spi/) 的 `WsTopicScheduler` 已用 APScheduler 按 Topic 订阅状态动态启停 Job
- `AsyncTaskRunner` 已解决 asyncio 桥接问题
- Windows 下 subprocess.Popen 崩溃恢复弱，supervisor 支持差

**方案设计**：
1. 在 FastAPI lifespan 启动时注册 `IntradayMonitorTask`（asyncio 后台任务，daemon=True）
2. 任务默认休眠，监听 Redis Pub/Sub 频道 `intraday.control`
3. Celery Beat 在 09:15 `publish intraday.start`（含动态股票池快照），任务被唤醒启动订阅
4. 15:30 `publish intraday.stop`，任务优雅停止订阅
5. 非交易时段任务休眠，不消耗 CPU

**架构优势**：
- 复用现有 FastAPI 进程，避免引入进程管理复杂度
- 同进程内 asyncio 任务直通，无 Redis 跨进程通信延迟
- 与现有 `BrokerStatusSpi`/`PnlSpi`/`StockQuoteSpi` 等 WS SPI 架构一致
- 监控任务设计为**幂等可重入**，FastAPI 重启后自动从 DB 加载最新状态恢复

**容错机制**：
- Redis 缓存「最后处理的分钟时间戳」，断点续传
- 30s 缺口检测：发现分钟线缺失时主动调 `fetch_kline_minute` 补单
- 盘后 15:30 全量补全（[QmtDataCollector.fetch_kline_minute](../src/xqtrader/broker/services/qmt_data_collector.py)）

**未来扩展**：若监控任务负载过重（CPU 占用 >30%），可拆分为独立进程，但当前动态股票池规模（50-300 只）下同进程足够。

## 五、数据模型

### 5.1 新增表：`sdc_candlestick_1m`

复用 [market/models/candlestick.py](../src/xqtrader/domain/market/models/candlestick.py) 的 `CandlestickDaily` 模式，新增 `CandlestickMinute`：

```python
@timescale(
    time_column="trade_time",
    chunk_interval="1 day",
    compress_after="3 months",
    compress_segmentby="symbol"
)
class CandlestickMinute(Base):
    __bind_key__ = "stock"
    __tablename__ = "sdc_candlestick_1m"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True, comment="证券代码")
    trade_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, comment="分钟时间戳")
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False, comment="成交量(手)")
    amount: Mapped[float] = mapped_column(Float, nullable=False, comment="成交额(元)")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="所属交易日，便于按日查询")
    data_source: Mapped[str] = mapped_column(String(20), nullable=False, default="qmt")
```

**字段设计要点**：
- `trade_time` 用 `DateTime(timezone=True)` 而非 `Date`，支持分钟精度
- 主键 `(symbol, trade_time)` 包含时间列，符合 TimescaleDB hypertable 要求（[timescale.py](../src/framework/dal/timescale.py) L137-187 删除不兼容唯一索引逻辑）
- `trade_date` 冗余字段 + 索引，便于按日聚合查询（避免 `date_trunc` 函数索引）
- `volume` 单位「手」，`amount` 单位「元」（与 QMT xtdata 返回一致）

### 5.2 Continuous Aggregate（数据库层定义）

在初始化脚本中执行（dal-orm 不直接管理 CAGG，由 SQL 脚本维护）：

```sql
-- 5m 聚合
CREATE MATERIALIZED VIEW sdc_candlestick_5m_cagg
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('5 minutes', trade_time) AS trade_time,
    first(open, trade_time) AS open,
    max(high) AS high,
    max(low) AS low,
    last(close, trade_time) AS close,
    sum(volume) AS volume,
    sum(amount) AS amount,
    trade_date
FROM sdc_candlestick_1m
GROUP BY symbol, time_bucket('5 minutes', trade_time), trade_date;

SELECT add_continuous_aggregate_policy('sdc_candlestick_5m_cagg',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes');

-- 15m / 1h 类似，省略
```

### 5.3 Retention Policy

```sql
SELECT add_retention_policy('stock.sdc_candlestick_1m', INTERVAL '2 years');
```

### 5.4 不新增的表（保持精简）

- **不建** `sdc_tick_data`（Tick 不落库）
- **不建** `sdc_candlestick_5m` / `sdc_candlestick_15m` / `sdc_candlestick_1h` 物理表（用 Continuous Aggregate 视图替代）
- **不建** `sdc_intraday_signal`（盘中信号写现有 `td_trading_signal` 表，加 `signal_source='intraday'` 区分）

## 六、模块设计

### 6.1 数据接入层

新增 `src/xqtrader/domain/market/intraday/` 目录：

```
intraday/
├── __init__.py
├── minute_bar_collector.py     # 分钟线合成器（tick/快照 -> 1m OHLCV）
├── tick_anomaly_scanner.py     # 全推快照异动扫描（内存，不落库）
├── intraday_monitor_task.py    # asyncio 后台任务主循环（FastAPI lifespan 注册）
└── publishers.py               # Redis Pub/Sub 事件发布
```

**QmtDataCollector 扩展**（[qmt_data_collector.py](../src/xqtrader/broker/services/qmt_data_collector.py)）：

```python
def fetch_kline_minute(self, symbols: list[str], period: str = "1m",
                       start_dt: str, end_dt: str) -> pd.DataFrame:
    """历史分钟线补全（盘后用）"""
    # 复用 _download_and_get_kline，period 传 "1m"/"5m"

def subscribe_minute_bar(self, symbols: list[str], callback: Callable) -> None:
    """实时分钟线订阅（盘中用）"""
    # xtdata.subscribe_quote(symbols, period='1m', count=1)
```

### 6.2 信号计算层

新增 `src/xqtrader/domain/trading/backtest/plugins/intraday/` 目录，复用 [RulePlugin](../src/xqtrader/domain/trading/backtest/core.py) ABC：

```
plugins/intraday/
├── __init__.py
├── vwap.py                     # VWAP 计算（执行基准 + 支撑阻力 + 方向信号）
├── minute_momentum.py          # 分钟动量/突破
├── anomaly_detect.py           # 量价异动（急涨急跌 + 量脉冲）
├── auction_signal.py           # 集合竞价信号（9:20-9:25）
└── limit_monitor.py            # 涨跌停/停牌监控
```

**接入方式**：复用 `td_rule_registry` 表注册，`rule_type='plugin'`，`spi_class` 字段存插件类路径，`signal_source='intraday'` 区分日级/盘中。

### 6.3 监控服务层

新增 `src/xqtrader/domain/trading/monitor/` 目录（文档 [trading-system-design.md](trading-system-design.md) §9 已标注 ⏳）：

```
monitor/
├── __init__.py
├── order_confirm_service.py   # OrderConfirmService（P1，本期实施）
├── position_sync_service.py  # PositionSyncService（P1，本期实施）
├── risk_monitor.py            # IntradayRiskMonitor（P2，下期）
└── reconciliation_service.py  # ReconciliationService（P3，下期）
```

**OrderConfirmService**（本期）：
- 事件驱动：QMT 订单/成交回报回调 → 推进 `td_order.status` → 写 `td_trade` → 发布 `ws.trading.orders`/`ws.trading.trades`
- 30s 轮询兜底：调 `trader.query_stock_order`/`query_stock_trade` 补漏
- 复用 [execution_tools.py](../src/xqtrader/domain/trading/workflow/tools/execution_tools.py) 模块级共享 `QmtTrader` 实例

**PositionSyncService**（本期）：
- 1m 轮询：调 `trader.query_stock_position`/`query_stock_asset` → 写 `td_position` 快照 → 发布 `ws.trading.positions`
- 偏离检测：对比 `td_pre_order.target_weight`，超阈值（±20%）发 `ws.trading.risk` warning

### 6.4 WS 推送层

复用 [ws/spi/](../src/xqtrader/ws/spi/) SPI 框架，新增 SPI 实现：

```
ws/spi/impl/
├── order_confirm_spi.py        # 订单/成交回报推送
├── position_sync_spi.py        # 持仓/资金同步推送
├── intraday_signal_spi.py      # 盘中信号事件推送
└── risk_event_spi.py           # 风控/熔断事件推送
```

在 [ws/constants.py](../src/xqtrader/ws/constants.py) 新增 Topic 常量（文档 [trading-system-design.md](trading-system-design.md) §10 已规划）：
- `ws.trading.signals`
- `ws.trading.orders` / `ws.trading.trades`
- `ws.trading.positions`
- `ws.trading.workflow`
- `ws.trading.risk`

### 6.5 Celery 调度

> **框架约束**：当前 scheduler 框架（[celery_app.py](../src/worker/celery_app.py) `_load_beat_schedule()`）仅支持 yml 顶层 `cron` 字段，不支持 canvas 模式下的 step 级 `schedule`。因此拆分为 3 个独立 yml 文件，每个文件一个 cron。

新增 3 个调度文件（仅定时控制信号，不拉起独立进程）：

**`schedules/intraday_monitor_start.yml`**（09:15 自动启动监控）：

```yaml
name: intraday_monitor_start
mode: canvas
queue: market
enabled: true
cron: "15 9 * * 1-5"
steps:
  - name: publish_start_signal
    task: market.intraday_control
    args:
      action: start
```

**`schedules/intraday_monitor_stop.yml`**（15:30 自动停止监控）：

```yaml
name: intraday_monitor_stop
mode: canvas
queue: market
enabled: true
cron: "30 15 * * 1-5"
steps:
  - name: publish_stop_signal
    task: market.intraday_control
    args:
      action: stop
```

**`schedules/intraday_reconcile.yml`**（盘后回补，**手动触发**）：

```yaml
name: intraday_reconcile
mode: canvas
queue: market
enabled: false   # 采集任务仅允许手动启动，禁止自动调度
steps:
  - name: intraday_reconcile
    task: market.intraday_reconcile
    args: {}
```

**控制流程**：Celery Beat 在 09:15 / 15:30 发 Redis `publish intraday.control` 消息 -> FastAPI 内的 `IntradayMonitorTask` 监听该频道被唤醒/休眠。**Celery 不拉起独立进程，不跑实时行情**。

**启动策略**：监控控制信号（start/stop）由 Celery Beat 自动触发；盘后回补（`intraday_reconcile`）属采集任务，遵循手动启动约束，`enabled: false`，需用户通过 API 或管理界面手动触发。

## 七、实施计划（Phase 1.0-1.1）

### 7.1 范围

| Phase | 范围 | 验收 |
|---|---|---|
| 1.0 基础设施 | 分钟线落库 + FastAPI lifespan 后台任务 + QMT 扩展 | 动态股票池 1m OHLCV 入库，可按日/分钟查询 |
| 1.1 成交确认 + 持仓同步 | OrderConfirmService + PositionSyncService + WS 推送 | 下单后成交回报实时可见，持仓 1m 自动刷新 |

### 7.2 任务分解

#### Phase 1.0：基础设施

| ID | 任务 | 涉及文件 | 依赖 |
|---|---|---|---|
| 1.0.1 | 新增 `CandlestickMinute` ORM 模型 | `src/xqtrader/domain/market/models/candlestick.py` | 无 |
| 1.0.2 | 新增 Continuous Aggregate + retention policy SQL 脚本 | `src/xqtrader/domain/market/sql/` | 1.0.1 |
| 1.0.3 | `QmtDataCollector` 新增 `fetch_kline_minute` + `subscribe_minute_bar` | `src/xqtrader/broker/services/qmt_data_collector.py` | 无 |
| 1.0.4 | 实现 `MinuteBarCollector` 分钟线合成器 | `src/xqtrader/domain/market/intraday/minute_bar_collector.py` | 1.0.3 |
| 1.0.5 | 实现 `TickAnomalyScanner` 全推快照异动扫描（内存，不落库） | `src/xqtrader/domain/market/intraday/tick_anomaly_scanner.py` | 1.0.3 |
| 1.0.6 | 实现 `IntradayMonitorTask` asyncio 后台任务（FastAPI lifespan 注册，订阅+合成+落库+发布事件，监听 Redis intraday.control 启停） | `src/xqtrader/domain/market/intraday/intraday_monitor_task.py` | 1.0.4, 1.0.5 |
| 1.0.7 | 实现 `Publishers` Redis Pub/Sub 事件发布 | `src/xqtrader/domain/market/intraday/publishers.py` | 无 |
| 1.0.8 | 新增 Celery Beat schedule：09:15/15:30 发控制信号（自动）+ 盘后回补（手动） | `schedules/intraday_monitor_start.yml` + `schedules/intraday_monitor_stop.yml` + `schedules/intraday_reconcile.yml` + `src/worker/` | 1.0.6 |
| 1.0.9 | 黑盒测试：动态股票池 1m OHLCV 入库 + Continuous Aggregate 自动刷新 + 按日/分钟查询 | `tests/market/test_intraday_monitor.py` | 全部 |

#### Phase 1.1：成交确认 + 持仓同步

| ID | 任务 | 涉及文件 | 依赖 |
|---|---|---|---|
| 1.1.1 | 新增 `OrderConfirmService`（事件 + 30s 轮询兜底） | `src/xqtrader/domain/trading/monitor/order_confirm_service.py` | Phase 1.0 |
| 1.1.2 | 新增 `PositionSyncService`（1m 轮询 + 偏离检测） | `src/xqtrader/domain/trading/monitor/position_sync_service.py` | Phase 1.0 |
| 1.1.3 | 新增 WS SPI：`OrderConfirmSpi` + `PositionSyncSpi` | `src/xqtrader/ws/spi/impl/` | 1.1.1, 1.1.2 |
| 1.1.4 | 在 [ws/constants.py](../src/xqtrader/ws/constants.py) 新增 Topic 常量 | `src/xqtrader/ws/constants.py` | 1.1.3 |
| 1.1.5 | `IntradayMonitorTask` 接入 OrderConfirm + PositionSync（订阅 Redis 事件） | `src/xqtrader/domain/market/intraday/intraday_monitor_task.py` | 1.1.1, 1.1.2 |
| 1.1.6 | 黑盒测试：下单 → 成交回报 → 持仓同步 → WS 推送全链路 | `tests/trading/test_intraday_monitor.py` | 全部 |

### 7.3 验收口径

**Phase 1.0 验收**：
1. 09:15 Celery Beat 发 `intraday.start` 控制信号，FastAPI 内 `IntradayMonitorTask` 被唤醒启动订阅；15:30 发 `intraday.stop` 优雅停止
2. 动态股票池（**全部账户去重自选池** + 持仓 + 已审批 pre_order）1m OHLCV 实时落库 `sdc_candlestick_1m`
3. 5m/15m/30m/1h Continuous Aggregate 自动增量刷新（`schedule_interval => INTERVAL '5 minutes'`）
4. `add_retention_policy` 2 年自动 drop 生效（可模拟旧数据验证）
5. `add_compression_policy` 3 月压缩生效（可模拟旧数据验证）
6. db-tools 可按日/分钟查询验证数据完整性
7. 盘后手动触发 `fetch_kline_minute` 全量补全当日数据，缺口已补齐

**Phase 1.1 验收**：
1. 模拟账户下单后，30s 内 `td_order.status` 推进、`td_trade` 写入
2. QMT 账户下单后，30s 内成交回报写入（事件驱动优先，轮询兜底）
3. 持仓 1m 自动刷新，`td_position` 快照写入
4. 持仓偏离 `td_pre_order.target_weight` 超 ±20% 时，`ws.trading.risk` 推送 warning
5. WS 客户端订阅 `ws.trading.orders`/`ws.trading.trades`/`ws.trading.positions` 可实时收到推送
6. Kill Switch 触发时，绕过 Workflow 紧急全平仍正常（回归测试）
7. FastAPI 重启后 `IntradayMonitorTask` 幂等恢复（从 Redis 缓存读最后时间戳断点续传）

### 7.4 后续阶段（本期不实施，仅规划）

| Phase | 范围 | 优先级 |
|---|---|---|
| 1.2 | IntradayRiskMonitor 日内亏损熔断 + 权重偏离告警 -> KillSwitch | 中 |
| 2.0 | VWAP / 集合竞价信号 / 涨跌停监控（1m 周期 P1 三件套） | 中 |
| 2.1 | 5m MACD/布林/双均线/动量 + 15m 唐奇安/ATR + 量价异动 | 中 |
| 3.0 | 缠论分钟级（需改造 chanpy 支持 K_30M/K_1H） | 低 |
| 3.1 | 资金流分级共振（需 Level-2）/ 北向资金实时 / 龙虎榜预期 | 低 |

## 八、风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| QMT `subscribe_quote` 回调延迟或丢包 | 分钟线缺失 | 30s 缺口检测 + 盘后手动触发 `fetch_kline_minute` 全量补全 |
| FastAPI 重启导致监控中断 | 监控中断 | 任务幂等可重入，重启后从 Redis 缓存读最后时间戳恢复 |
| TimescaleDB 写入压力（动态股票池扩大） | 落库延迟 | 批量写入（每 5s 聚合一批）+ `compress_segmentby='symbol'` 优化 |
| QMT 连接断开 | 无法获取行情 | 复用 `BrokerStatusSpi` 监控连接状态，断开时告警并暂停落库 |
| Redis Pub/Sub 消息丢失 | 信号事件丢失 | 关键事件（成交/持仓）双重保障：事件 + 30s/1m 轮询兜底 |
| 分钟线时间戳时区问题 | 数据错位 | 统一 `DateTime(timezone=True)`，QMT 返回已为本地时间需明确转换 |
| 监控任务占用 FastAPI 事件循环 | API 响应变慢 | 监控任务用 `asyncio.create_task` 独立调度，DB 写入用 `asyncio.to_thread`，不阻塞主循环 |

## 九、与现有代码的边界

### 9.1 不修改的模块

- [workflow/service.py](../src/xqtrader/domain/trading/workflow/service.py) `WatchlistDecisionWorkflowService`：决策流不变（日频盘后）
- [workflow/execution_service.py](../src/xqtrader/domain/trading/workflow/execution_service.py) `PreOrderExecutionWorkflowService`：执行流不变（事件驱动逐单）
- [workflow/kill_switch_service.py](../src/xqtrader/domain/trading/workflow/kill_switch_service.py) `KillSwitchService`：紧急全平不变（Phase 1.2 风控熔断会调用它）
- [backtest/](../src/xqtrader/domain/trading/backtest/) 全部：回测引擎不变

### 9.2 扩展的模块

- [market/models/candlestick.py](../src/xqtrader/domain/market/models/candlestick.py)：新增 `CandlestickMinute` 类
- [broker/services/qmt_data_collector.py](../src/xqtrader/broker/services/qmt_data_collector.py)：新增 `fetch_kline_minute` + `subscribe_minute_bar`
- [ws/constants.py](../src/xqtrader/ws/constants.py)：新增 Topic 常量
- [ws/spi/impl/](../src/xqtrader/ws/spi/impl/)：新增 SPI 实现
- [app.py 或 main.py lifespan]：注册 `IntradayMonitorTask` 后台任务

### 9.3 新增的模块

- `src/xqtrader/domain/market/intraday/`：数据接入层（`MinuteBarCollector`/`TickAnomalyScanner`/`IntradayMonitorTask`/`Publishers`）
- `src/xqtrader/domain/trading/monitor/`：监控服务层
- `src/xqtrader/domain/trading/backtest/plugins/intraday/`：盘中信号策略（Phase 2）
- `schedules/intraday_monitor_start.yml` / `intraday_monitor_stop.yml`：Celery Beat 调度（09:15/15:30 自动控制信号）
- `schedules/intraday_reconcile.yml`：盘后回补调度（`enabled: false`，手动触发）

## 十、决策确认与实施

经评审，以下决策已确认：

| 决策项 | 最终方案 |
|---|---|
| 数据源 | QMT xtquant 全推（subscribe_quote period='1m' + subscribe_whole_quote 全推快照） |
| 存储粒度 | 1m OHLCV，热3月/温2年（压缩）/2年后自动drop，5m/15m/30m/1h 用 Continuous Aggregate 永久保留 |
| Continuous Aggregate 刷新 | `schedule_interval => INTERVAL '5 minutes'`，`materialized_only=false` 实时聚合 |
| 进程模式 | **FastAPI lifespan 内常驻 asyncio 后台任务**（不使用独立进程） |
| 控制信号 | Celery Beat 09:15/15:30 发 Redis `intraday.control` 消息唤醒/休眠任务 |
| 落库范围 | **全部账户去重自选池** + 持仓 + 已审批 pre_order（约 50-300 只） |
| 分表方案 | 不分表，单 hypertable + compression/retention policy + Continuous Aggregate |
| 盘中信号策略 | 多周期组合：1m VWAP/集合竞价/涨跌停 + 5m MACD/布林/双均线/动量 + 15m 唐奇安/ATR + 30m/1h 缠论（Phase 3 改造） |
| Level-2 替代 | 量价异动用 Level-1 快照，资金流用 Tushare moneyflow_dc 日级 |
| 分钟线补全 | 盘后手动触发 `fetch_kline_minute` 全量拉取补全 |
| 实施范围 | Phase 1.0 基础设施 + Phase 1.1 成交确认与持仓同步 |

### 10.1 实施前需进一步确认

1. **WS 推送频率**：`ws.trading.positions` 设计为 1m 推送。是否需要加变更检测（仅持仓/资金变化时推送）以降低推送频率？建议：默认变更检测，可配置强制 1m 推送
2. **IntradayMonitorTask 注册位置**：建议在 FastAPI lifespan（`src/xqtrader/app.py` 或 `main.py`）的 `startup` 事件注册，`shutdown` 事件优雅停止。需确认现有 lifespan 结构
3. **监控任务异常处理**：任务内异常不应影响 FastAPI 主进程，需用 `try/except` 包裹 + `logger.error(exc_info=True)` + 自动重启机制（如 `asyncio.create_task` 失败后 5s 重试）

---

## 附录 A：业界参考

- 聚宽 JoinQuant：分钟级 `handle_data` 回调，云端托管，K 线已前复权
- 米筐 RiceQuant：Level-1 实时快照（3-5s 延迟）-> 实时合成分钟线 -> `handle_bar` 回调
- QMT/迅投：全推 Tick 本地落地 + `subscribe_quote` 精准盯防 + `get_full_tick` 主动快照
- Alpaca：WebSocket 推送分钟 bar，回测/实盘同一接口
- Backtrader live：IBStore + IBData + resampling/replaying，事件驱动 `next()`
- TimescaleDB：`create_hypertable` + `add_continuous_aggregate_policy` + `add_retention_policy` + `add_compression_policy`

## 附录 B：硬件配置说明

- CPU：AMD Ryzen 9 9950X（16 核 32 线程）- 充足
- 内存：48GB - 充足（TimescaleDB 缓存 + Continuous Aggregate 物化视图占用极小）
- 显卡：RTX 5060Ti - **本场景无用**（TimescaleDB 不支持 GPU 加速）
- 存储：建议 SSD，分钟线写入频繁，HDD 会成为瓶颈

---

## 十一、行情监控大屏驾驶舱

> 版本：v1.0  日期：2026-07-10
> 状态：设计中，待评审

### 11.1 背景与定位

#### 11.1.1 现状缺口

| 维度 | 现状 | 缺口 |
|------|------|------|
| 交易视角 | [LiveCockpitPage](../web/src/pages/trading/LiveCockpitPage.tsx) `/trading` — 账户资产/信号审批/持仓/订单流/Kill Switch | 已有，聚焦"执行" |
| 行情视角 | `/monitor` 路由是 `RoutePlaceholder` 占位 | **空白，未实现** |
| 单标的 K 线 | [StockKlineChart.tsx](../web/src/components/stock/StockKlineChart.tsx) 840 行，支持 MA/布林/TD9/缠论 + MACD/KDJ/RSI 副图 | 单标的详情视角，不支持多标的同屏 |
| 盘内数据 | 本文档 §一至 §十已设计分钟线采集/落库/信号计算 | 数据层+计算层已设计，**缺可视化层** |
| WS 推送 | [constants.py](../src/xqtrader/ws/constants.py) 已定义 `ws.intraday.minute_bar` / `ws.intraday.tick_anomaly` / `ws.intraday.status` 三个 topic | 前端无消费方 |
| 信号查询 | `td_trading_signal` 表存在，但**无独立 API**（仅通过 pre_order 的 signal_detail 间接暴露） | 缺 `GET /intraday/signals` 端点 |

#### 11.1.2 设计目标

构建「**行情监控大屏驾驶舱**」——类似视频监控的多标的同屏行情观察面板，作为盘内监控可视化层的最终消费方，补齐盘内闭环最后一环。

与现有 `/trading` 交易驾驶舱互补并列：
- `/trading`：交易视角（管执行：审批/持仓/订单流/Kill Switch）
- `/monitor/screen`：行情视角（看市场：多标的监控/信号流/快速下单）

#### 11.1.3 设计原则

1. **独立大屏**：可脱离框架布局（TopBar/SideNav/StatusBar）独立全屏打开，适合投屏/副屏场景
2. **深色主题统一**：复用 [themes.css](../web/src/styles/themes.css) 全局 CSS 变量，不引入新色板
3. **视频监控式交互**：标的可拖拽、排序、缩放、放大全屏，类似监控墙
4. **高复用低新增**：ECharts/WS 框架/intraday API/自选池 API 均已有，大屏是"组装"非"从零搭建"；唯一新增前端依赖 `react-grid-layout`
5. **信号可快速下单**：保留审计与风控前提下，支持从信号一键下单

### 11.2 独立窗口支持

#### 11.2.1 路由设计

当前路由全部嵌套在 `AppLayout`（TopBar + SideNav + StatusBar）下（[router/index.tsx](../web/src/router/index.tsx)）。大屏需脱离框架布局独立全屏展示。

在 `createBrowserRouter` 顶层新增一条**平级路由**，不经过 `AppLayout`：

```typescript
// web/src/router/index.tsx
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AuthGuard><RouteErrorBoundary><AppLayout /></RouteErrorBoundary></AuthGuard>,
    errorElement: <ServerErrorPage />,
    children: [
      // ... 现有子路由 ...
      { path: 'monitor', element: <MonitorOverviewPage /> },  // 框架内概览页
    ],
  },
  // ↓ 新增：独立大屏路由，不套 AppLayout
  {
    path: '/monitor/screen',
    element: <AuthGuard><RouteErrorBoundary><MonitorDashboardPage /></RouteErrorBoundary></AuthGuard>,
    errorElement: <ServerErrorPage />,
  },
  { path: '/500', element: <ServerErrorPage /> },
  { path: '/404', element: <NotFoundPage /> },
  { path: '*', element: <NotFoundPage /> },
])
```

- **框架内入口**：`/monitor` 作为大屏概览页（含"打开大屏"按钮 + 布局预览）
- **独立窗口入口**：`/monitor/screen` 通过 `window.open` 在新浏览器窗口打开，无 TopBar/SideNav/StatusBar，全屏可用
- **鉴权**：`AuthGuard` 当前 `canActivate()` 恒返回 `true`（[auth.ts](../web/src/router/auth.ts) 预留），独立窗口同样经过 AuthGuard，无额外处理

#### 11.2.2 打开方式

在 `/monitor` 概览页放"打开大屏"按钮：

```typescript
window.open('/monitor/screen', '_blank', 'popup,width=1920,height=1080')
```

生产环境同域部署时直接可用；开发环境 Vite proxy 已转发 `/api` 和 `/ws`（[vite.config.ts](../web/vite.config.ts)）。

### 11.3 大屏 UI 布局

采用**三区布局**：顶部状态栏 + 左侧标的池 + 主监控网格 + 底部信号流。

```
┌──────────────────────────────────────────────────────────────────────┐
│  ScreenHeader (32px)                                                 │
│  ● 监控中 09:30-15:00 | 池: 38只 | 布局: 3×2 | 主题: 深色 | [全屏F11] │
├──────────┬───────────────────────────────────────────────────────────┤
│          │                                                           │
│ StockPool│              MonitorGrid                                  │
│ Sidebar  │   ┌────────────┐ ┌────────────┐ ┌────────────┐           │
│ (180px)  │   │ 000001.SZ  │ │ 600519.SH  │ │ 300750.SZ  │           │
│          │   │ 10.52 +1.2%│ │ 1689.0 -0.3│ │ 215.5 +2.1%│           │
│ [搜索框]  │   │ ┌────────┐ │ │ ┌────────┐ │ │ ┌────────┐ │           │
│          │   │ │1m+VWAP │ │ │ │1m+MACD │ │ │ │ 日K+布林│ │           │
│ 自选池    │   │ │ K线图  │ │ │ │ K线图  │ │ │ │ K线图  │ │           │
│ ┌──────┐ │   │ └────────┘ │ │ └────────┘ │ │ └────────┘ │           │
│ │000001│ │   │ ⤢放大 ✕移除│ │ ⤢放大 ✕移除│ │ ⤢放大 ✕移除│           │
│ │600519│ │   └────────────┘ └────────────┘ └────────────┘           │
│ │300750│ │   ┌────────────┐ ┌────────────┐ ┌────────────┐           │
│ │...   │ │   │ 002594.SZ  │ │  (空槽)    │ │  (空槽)    │           │
│ └──────┘ │   │ 1m+动量    │ │  拖入标的  │ │  拖入标的  │           │
│          │   └────────────┘ └────────────┘ └────────────┘           │
│ 持仓标的  │                                                           │
│ ┌──────┐ │                                                           │
│ │...   │ │                                                           │
│ └──────┘ │                                                           │
├──────────┴───────────────────────────────────────────────────────────┤
│  SignalStreamPanel (160px, 可折叠至 32px)                             │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ ⚡ 10:32:15  000001.SZ  VWAP上穿   ▲ long  0.72  [⚡快速下单]  │  │
│  │ ⚡ 10:31:48  600519.SH  量价异动   — —     0.85  [⚡快速下单]  │  │
│  │ ⚡ 10:30:00  300750.SZ  MACD金叉   ▲ long  0.65  [⚡快速下单]  │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

**各区域职责**：

| 区域 | 尺寸 | 职责 |
|------|------|------|
| ScreenHeader | 32px 固定高 | 监控状态/股票池统计/布局切换/全屏按钮 |
| StockPoolSidebar | 180px 固定宽，可折叠 | 拖拽源：自选池+持仓标的列表，支持搜索 |
| MonitorGrid | flex: 1 自适应 | 拖拽目标：react-grid-layout 网格，N×M 布局 |
| SignalStreamPanel | 160px，可折叠至 32px | 信号流：时间倒序，支持过滤/快速下单 |

### 11.4 配色方案（深色主题统一）

复用 [themes.css](../web/src/styles/themes.css) 全局 CSS 变量，不引入新色板：

| 区域 | CSS 变量 | 色值 | 用途 |
|------|----------|------|------|
| 大屏背景 | `--bg-root` | `#0a0c10` | 全屏底色 |
| 顶栏 | `--bg-statusbar` | `#080a0e` | ScreenHeader 背景 |
| 侧栏 | `--bg-sidenav` | `#0c0f14` | StockPool 背景 |
| 网格区 | `--bg-workspace` | `#0f1218` | MonitorGrid 背景 |
| 标的卡片 | `--bg-card` | `#131820` | MonitorCell 背景 |
| 卡片边框 | `--border-default` | `rgba(255,255,255,0.11)` | Cell 边框 |
| 悬浮高亮 | `--border-focus` | `rgba(22,119,255,0.55)` | 拖拽悬停/选中 |
| 主文字 | `--text-primary` | `#eef2f8` | 标的代码/价格 |
| 次文字 | `--text-secondary` | `#9aaabe` | 标签/时间 |
| 品牌色 | `--accent-primary` | `#1677ff` | 按钮/链接/选中态 |
| 涨色 | `--color-rise` | `#e03e3e` | A 股红涨 |
| 跌色 | `--color-fall` | `#2eaa67` | A 股绿跌 |
| 警告 | `--color-warning` | `#faad14` | 异动告警 |
| 卡片阴影 | `--shadow-card` | `0 1px 3px rgba(0,0,0,0.45)` | Cell 投影 |

**交互态增强**（新增少量局部样式）：
- 卡片选中态：`border-color: var(--accent-primary)` + `box-shadow: 0 0 0 1px var(--accent-primary)`
- 拖拽悬停态：空槽 `border: 1px dashed var(--accent-muted)` + `background: var(--accent-muted)`
- 信号行 hover：`background: var(--bg-hover)`

所有颜色通过 CSS 变量引用，切换 light 主题时自动适配（大屏默认深色）。

### 11.5 MonitorCell 组件设计（视频监控式交互）

#### 11.5.1 拖拽与排序

使用 `react-grid-layout`（React 生态标准网格拖拽库）：

| 能力 | 实现 |
|------|------|
| 拖拽排序 | `react-grid-layout` 的 `onDragStop` 重新排列 cells |
| 从侧栏拖入 | 侧栏标的为 HTML5 `draggable`，拖入网格区 `onDrop` 创建新 cell |
| 缩放尺寸 | 拖拽 cell 右下角 resize handle，支持 1×1 / 2×1 / 2×2 / 3×2 等尺寸 |
| 放大全屏 | cell 内 `⤢` 按钮 → layout 中该 cell 设为 `w=cols, h=maxRows`，其余隐藏 |
| 移除 | cell 内 `✕` 按钮 → 从 cells 列表删除 |
| 布局持久化 | layout 配置存 `localStorage`，key 为 `monitor:layout:{accountId}` |

#### 11.5.2 Cell 内部结构

```
MonitorCell
├── CellHeader (28px)
│   ├── 左：标的代码 + 名称 + 实时价格 + 涨跌幅(红/绿)
│   └── 右：周期切换(1m/日K) + 指标切换(▾) + 放大(⤢) + 关闭(✕)
├── ChartBody (flex: 1)
│   └── MiniKlineChart (ECharts)
│       ├── 主图：candlestick + 叠加指标
│       └── 副图：技术指标 (可选)
└── CellFooter (20px, 可选)
    └── 最新信号 badge (如 "⚡VWAP上穿 10:32")
```

#### 11.5.3 MiniKlineChart 设计

基于现有 [StockKlineChart.tsx](../web/src/components/stock/StockKlineChart.tsx) 的 ECharts 配置精简：

**分钟模式（默认）**：
- 数据：`GET /intraday/minute-bars?symbol={symbol}&trade_date={today}`
- 主图叠加指标（单选）：VWAP / MA5&MA20 / 布林带 / 唐奇安通道
- 副图指标（单选）：成交量 / MACD / RSI
- 实时更新：WS 订阅 `ws.intraday.minute_bar`，按 symbol 过滤，增量更新最后一根 K 线

**日 K 模式**：
- 数据：`GET /stocks/{symbol}/kline?limit=120`
- 主图叠加：MA / 布林 / TD9 / 缠论
- 副图：MACD / KDJ / RSI / 成交量
- 实时更新：WS 订阅 `ws.market.stock_quotes.{symbol}`，复用 [klineLive.ts](../web/src/utils/klineLive.ts) `mergeLiveQuoteIntoBars`

**精简策略**（与 StockKlineChart 的区别）：
- 无 dataZoom 滚动条（cell 空间小，固定显示最近 N 根）
- 无十字光标 tooltip（可选开启）
- 轴标签极简（仅显示首尾时间）
- 放大态时恢复完整交互（dataZoom + tooltip）

#### 11.5.4 指标切换 UI

CellHeader 右侧指标切换用 Ant Design `Dropdown`：

```
周期: [1m] [日K]     指标: [主图▾] [副图▾]    ⤢  ✕
                      ├─ VWAP         ├─ 成交量
                      ├─ MA5/MA20     ├─ MACD
                      ├─ 布林带       └─ RSI
                      └─ 唐奇安
```

### 11.6 SignalStreamPanel 信号区设计

#### 11.6.1 数据来源

| 来源 | 方式 | 说明 |
|------|------|------|
| 初始加载 | `GET /intraday/signals?trade_date={today}` | 需新增 API，查 `td_trading_signal` 当日记录 |
| 实时异动 | WS `ws.intraday.tick_anomaly` | 急涨急跌/量脉冲 |
| 实时策略信号 | WS `ws.trading.signals`（规划中） | VWAP突破/MACD金叉等 |

#### 11.6.2 信号行结构

```
┌──────────────────────────────────────────────────────────────────────┐
│ ⚡ 10:32:15 │ 000001.SZ 平安银行 │ VWAP上穿 │ ▲ long │ 0.72 │ [⚡下单] │
├──────────────────────────────────────────────────────────────────────┤
│ ⚡ 10:31:48 │ 600519.SH 贵州茅台 │ 量价异动 │  —    │ 0.85 │ [⚡下单] │
└──────────────────────────────────────────────────────────────────────┘
```

- 按时间倒序，最新在顶部，自动滚动
- 支持按标的/信号类型/方向过滤
- 点击信号行 → 高亮对应 MonitorCell（边框闪烁 2s）
- 信号方向颜色：long → `--color-rise`(红)，short → `--color-fall`(绿)，neutral → `--text-muted`

### 11.7 信号快速下单分析与设计

#### 11.7.1 现有下单链路

```
信号(TradingSignal)
  → PositionSizingResult(配仓)
  → PreOrder创建(status=pending_approval)
  → 人工审批(POST /trading/approval/{id})
  → submit(POST /trading/pre-orders/{id}/submit)
  → 执行流 → Order → QMT/模拟撮合
```

**关键约束**（[router.py](../src/xqtrader/api/v1/trading/router.py) L1313-1337, [schemas.py](../src/xqtrader/api/v1/trading/schemas.py) L119-156）：
1. PreOrder 必须经过 `approval_status: pending → approved` 才能 submit
2. `submit_pre_order` 要求 `approval_status == APPROVED`
3. 审批和下单是**两个独立 API 调用**，需人工确认
4. `operator` 字段必填，禁止 `system`（`validate_operator_not_system`）
5. PreOrder 需要 `instance_id`（策略实例），信号本身不直接产出 PreOrder

#### 11.7.2 快速下单可行性分析

| 场景 | 可行性 | 说明 |
|------|--------|------|
| 信号已有对应 PreOrder | ✅ 可行 | 信号已走完决策流产出 PreOrder，快速下单 = 审批 + submit 两步合并 |
| 信号无 PreOrder（纯盘中信号） | ⚠️ 需新建 | 盘中信号(VWAP/异动)目前不产出 PreOrder，需新增"从信号创建 PreOrder"的 API |
| 绕过审批直接下单 | ❌ 不建议 | 破坏现有审批风控体系，与 `live_manual` 模式冲突 |

#### 11.7.3 推荐方案：两步合一的"快速审批下单"

**不绕过审批**，而是将"审批 + 下单"合并为一次交互：

**场景 A：信号已有 PreOrder**

```
用户点击 [⚡下单]
  → 弹出 QuickOrderModal（预填信号信息）
  → 用户确认方向/数量/价格/操作人
  → 前端连续调用：
    1. POST /trading/approval/{pre_order_id}  (approved=true)
    2. POST /trading/pre-orders/{pre_order_id}/submit
  → 展示下单结果
```

**场景 B：盘中信号无 PreOrder**

后端新增 API：

```
POST /intraday/signals/{signal_id}/quick-order
Body: {
  account_id: int,
  side: "open" | "add" | "reduce" | "close",
  target_qty: int,
  order_type: "limit" | "market",
  limit_price: float | null,
  operator: str  (禁止 system)
}
→ 后端创建 PreOrder(approval_status=approved, status=approved)
→ 自动触发 submit
→ 返回 order 信息
```

该 API **内部完成"创建+审批+下单"三步**，但仍保留：
- `operator` 审计字段
- PreOrder 记录可追溯
- 风控预检（`risk_check_passed`）
- Kill Switch 仍可拦截

#### 11.7.4 QuickOrderModal 交互设计

```
┌─────────────────────────────────────────────┐
│  快速下单 — 000001.SZ 平安银行              │
├─────────────────────────────────────────────┤
│  信号: VWAP上穿  方向: ▲ long  强度: 0.72   │
│  现价: 10.52  涨幅: +1.2%                   │
│                                             │
│  账户:    [模拟盘 ▾]                        │
│  操作:    [开仓 ▾]  (open/add/reduce/close) │
│  数量:    [100    ] 股                      │
│  类型:    [限价 ▾]  (limit/market)          │
│  价格:    [10.52  ] 元  (market时禁用)      │
│  操作人:  [trader ]                         │
│                                             │
│  ⚠ 此操作将跳过人工审批直接提交订单         │
│                                             │
│              [取消]    [确认下单]           │
└─────────────────────────────────────────────┘
```

- Modal 打开时根据信号方向预填 side（long→open/buy，short→reduce/sell）
- 价格默认填现价（从 WS 实时行情获取）
- 操作人默认填 `DEFAULT_OPERATOR`（[trading/utils.ts](../web/src/pages/trading/utils/trading.ts) 已有此常量）
- 确认按钮需二次确认（Ant Design `Modal.confirm`）

#### 11.7.5 安全约束

| 约束 | 实现 |
|------|------|
| 仅模拟盘默认开启快速下单 | 实盘账户需在设置中显式开启"快速下单"开关 |
| Kill Switch 激活时禁用 | 前端检查 `riskEvents` 中是否有未解决的 `kill_switch` 事件 |
| 单笔金额上限 | 可配置（如模拟盘 50 万、实盘 10 万），超限需走正常审批 |
| 操作人审计 | `operator` 必填，写入 PreOrder.approved_by + Order 审计字段 |
| 风控预检不跳过 | 后端 `quick-order` API 仍执行 `risk_check_passed` 逻辑 |

### 11.8 前端文件结构

```
web/src/pages/monitor/
├── index.tsx                          # 路由导出
├── MonitorDashboardPage.tsx           # 大屏主页面（独立路由 /monitor/screen）
├── MonitorOverviewPage.tsx            # /monitor 概览页（框架内，含"打开大屏"按钮）
├── components/
│   ├── ScreenHeader.tsx               # 顶部状态栏
│   ├── StockPoolSidebar.tsx           # 左侧标的池（拖拽源）
│   ├── MonitorGrid.tsx                # 网格容器（react-grid-layout）
│   ├── MonitorCell.tsx                # 单个标的监控格子
│   ├── MiniKlineChart.tsx             # 迷你K线图
│   ├── SignalStreamPanel.tsx          # 底部信号流
│   └── QuickOrderModal.tsx            # 快速下单弹窗
├── stores/
│   └── monitorStore.ts                # Zustand：cells列表/布局配置/信号列表/选中态
├── hooks/
│   ├── useMonitorWebSocket.ts         # 盘内WS订阅封装
│   └── useMonitorLayout.ts            # 布局持久化(localStorage)
└── styles/
    └── monitor.css                    # 大屏局部样式（引用全局CSS变量）
```

### 11.9 后端配套改动

| 改动 | 说明 | 优先级 |
|------|------|--------|
| 新增 `GET /intraday/signals` | 查询当日盘中信号列表，支持 symbol/signal_type/direction 过滤 | P0 |
| `td_trading_signal` 新增 `signal_source` 字段 | `String(16)`，区分 `daily`/`intraday`（本文档 §5.4 已规划） | P0 |
| 新增 `POST /intraday/signals/{id}/quick-order` | 从盘中信号快速创建 PreOrder + 审批 + 下单（三步合一） | P1 |
| 新增 `ws.trading.signals` SPI | 盘中策略信号事件推送（本文档 §6.4 已规划） | P1 |
| 监控布局 API（可选） | `GET/POST /intraday/monitor-layout` 服务端持久化布局 | P2 |

#### 11.9.1 `GET /intraday/signals` API 设计

```
GET /api/v1/intraday/signals?trade_date={YYYY-MM-DD}&symbol={symbol}&signal_type={type}&direction={dir}&page=1&page_size=50

Response:
{
  "items": [
    {
      "id": 123,
      "instance_id": 1,
      "signal_date": "2026-07-10",
      "symbol": "000001.SZ",
      "direction": "long",
      "strength": 0.72,
      "signal_type": "vwap_breakout",
      "signal_source": "intraday",   // 新增字段
      "raw_values": { "vwap": 10.48, "close": 10.52, ... },
      "created_at": "2026-07-10T10:32:15+08:00"
    }
  ],
  "total": 38,
  "page": 1,
  "page_size": 50
}
```

#### 11.9.2 `POST /intraday/signals/{id}/quick-order` API 设计

```
POST /api/v1/intraday/signals/{signal_id}/quick-order
Body:
{
  "account_id": 1,
  "side": "open",
  "target_qty": 100,
  "order_type": "limit",
  "limit_price": 10.52,
  "operator": "trader"
}

Response:
{
  "pre_order": { ... },
  "order": { ... },
  "broker_order_id": "..."
}
```

后端流程：
1. 查 `TradingSignal` 获取 symbol/direction/instance_id
2. 创建 `PreOrder`（approval_status=approved, status=approved, operator 审计）
3. 执行风控预检（`risk_check_passed`）
4. 调用 `_run_pre_order_execution_workflow` 提交订单
5. 返回 pre_order + order 信息

### 11.10 技术选型

| 依赖 | 版本 | 用途 | 是否新增 |
|------|------|------|----------|
| `react-grid-layout` | ^2.x | 拖拽网格布局 | **是**（唯一新增前端依赖） |
| ECharts | 6.1.0 | K线图渲染 | 否（已有） |
| Zustand | 5.x | 状态管理 | 否（已有） |
| Ant Design | 6.x | Modal/Dropdown/Segmented | 否（已有） |
| dayjs | 1.11.x | 时间格式化 | 否（已有） |

### 11.11 数据流全景

```
                    ┌─────────────────────────────────────┐
                    │           后端数据层                 │
                    │  sdc_candlestick_1m (分钟K线)        │
                    │  sdc_candlestick_5m_cagg (5m聚合)     │
                    │  sdc_candlestick_daily (日K线)       │
                    │  td_trading_signal (信号)            │
                    └──────────┬──────────┬─────────────────┘
                               │          │
                    ┌──────────▼──┐  ┌────▼──────────────┐
                    │  REST API   │  │  WebSocket 推送    │
                    │  /intraday/ │  │  ws.intraday.*     │
                    │  /stocks/   │  │  ws.market.stock_* │
                    │  /trading/  │  │  ws.trading.signals│
                    └──────┬──────┘  └────┬──────────────┘
                           │              │
            ┌──────────────▼──────────────▼──────────────┐
            │          MonitorDashboardPage              │
            │  ┌─────────┐  ┌──────────────────────────┐ │
            │  │Sidebar  │  │  MonitorGrid             │ │
            │  │(拖拽源) │  │  Cell1  Cell2  Cell3     │ │
            │  │         │  │  Cell4  Cell5(放大全屏)  │ │
            │  └─────────┘  └──────────────────────────┘ │
            │  ┌──────────────────────────────────────┐  │
            │  │  SignalStreamPanel（WS信号流）        │  │
            │  │  → [⚡快速下单] → QuickOrderModal     │  │
            │  └──────────────────────────────────────┘  │
            └────────────────────────────────────────────┘
```

### 11.12 实施计划

| 期次 | 范围 | 前端 | 后端 |
|------|------|------|------|
| **P0 基础大屏** | 独立窗口 + 拖拽网格 + 迷你K线(分钟/日切换) + 布局持久化 + 信号区(REST) | 全部前端文件骨架 | `GET /intraday/signals` + `signal_source` 字段 |
| **P1 实时+快速下单** | WS 实时分钟线更新 + WS 异动信号流 + 指标叠加 + QuickOrderModal | WS hook + 指标 + Modal | `POST /intraday/signals/{id}/quick-order` + `ws.trading.signals` SPI |
| **P2 增强** | 服务端布局同步 + 信号过滤 + 信号回放 | 布局 API | `GET/POST /intraday/monitor-layout` |

#### P0 验收口径

1. `/monitor` 概览页可点击"打开大屏"按钮，在新窗口打开 `/monitor/screen`
2. 大屏页面无 TopBar/SideNav/StatusBar，全屏可用，深色主题
3. 左侧标的池从自选池 API 加载，可拖拽到网格区创建 MonitorCell
4. 每个 Cell 支持周期切换（1m/日K）、指标切换、放大全屏、移除
5. 布局配置存 localStorage，刷新后恢复
6. 底部信号区从 `GET /intraday/signals` 加载当日信号，按时间倒序展示
7. 点击信号行可高亮对应 MonitorCell

#### P1 验收口径

1. WS 订阅 `ws.intraday.minute_bar`，分钟K线实时更新最后一根
2. WS 订阅 `ws.intraday.tick_anomaly`，异动信号实时推入信号区
3. 指标叠加（VWAP/MACD/布林/唐奇安）正确渲染
4. 信号行 [⚡下单] 按钮可弹出 QuickOrderModal
5. QuickOrderModal 提交后，PreOrder 创建 + 审批 + 下单三步合一，订单可见
6. Kill Switch 激活时，快速下单按钮禁用
