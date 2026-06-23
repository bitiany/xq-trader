"""交易域枚举定义 — 所有枚举集中管理，模型字段使用 String 存储。"""


# ──────────────── 账户 & 实例 ────────────────

class AccountType:
    """交易账户类型"""
    LIVE = "live"
    PAPER = "paper"


class BrokerType:
    """券商适配类型"""
    QMT = "qmt"
    SIMULATED = "simulated"
    BACKTEST = "backtest"


class RunMode:
    """策略实例运行模式"""
    LIVE_MANUAL = "live_manual"
    LIVE_AUTO = "live_auto"
    PAPER = "paper"
    BACKTEST = "backtest"


class InstanceStatus:
    """策略实例状态"""
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class PaperSessionStatus:
    """模拟盘会话状态"""
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


# ──────────────── 信号 & 方向 ────────────────

class Direction:
    """交易方向"""
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class PreOrderSide:
    """预订单操作方向"""
    OPEN = "open"
    ADD = "add"
    REDUCE = "reduce"
    CLOSE = "close"


class OrderSide:
    """订单买卖方向"""
    BUY = "buy"
    SELL = "sell"


class OrderType:
    """订单类型"""
    LIMIT = "limit"
    MARKET = "market"


# ──────────────── 审批 & 状态 ────────────────

class ApprovalStatus:
    """审批状态"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PreOrderStatus:
    """预订单状态机"""
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUBMITTED = "submitted"


class OrderStatus:
    """订单状态机（OMS）"""
    CREATED = "created"
    RISK_CHECKED = "risk_checked"
    SUBMITTED = "submitted"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderEventType:
    """订单事件类型"""
    CREATED = "created"
    RISK_CHECKED = "risk_checked"
    SUBMITTED = "submitted"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


# ──────────────── 风控 ────────────────

class RiskCategory:
    """风控规则类别"""
    POSITION = "position"
    CAPITAL = "capital"
    TIMING = "timing"
    CIRCUIT_BREAKER = "circuit_breaker"


class RiskLevel:
    """风控级别"""
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"
    FATAL = "fatal"


class RiskEventType:
    """风控事件类型"""
    BLOCKED = "blocked"
    WARNING = "warning"
    CIRCUIT_BREAKER = "circuit_breaker"
    KILL_SWITCH = "kill_switch"


class RiskScope:
    """风控规则作用域"""
    GLOBAL = "global"
    ACCOUNT = "account"
    INSTANCE = "instance"


# ──────────────── 规则引擎 ────────────────

class RuleCategory:
    """规则类别 — 标识规则适用场景"""
    SELECTION = "selection"  # 仅截面选股
    TIMING = "timing"        # 仅时序回测
    BOTH = "both"            # 截面/时序均可


class RuleType:
    """规则类型"""
    EXPRESSION = "expression"
    PLUGIN = "plugin"


class RuleStatus:
    """规则状态"""
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class RuleDirection:
    """规则方向语义 — 按业务场景定义

    - 截面选股: BULLISH / BEARISH / NEUTRAL (分析当前处于多空中哪种状态)
    - 时序回测: BUY / SELL / NEUTRAL (产生交易动作)
    """
    # 截面选股方向
    BULLISH = "bullish"
    BEARISH = "bearish"
    # 时序回测方向
    BUY = "buy"
    SELL = "sell"
    # 共用
    NEUTRAL = "neutral"


# ──────────────── 策略引擎 ────────────────

class StrategyStatus:
    """策略定义状态"""
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class CombinationMethod:
    """规则组合 / 信号融合方式"""
    AND = "and"
    OR = "or"
    WEIGHTED_SCORE = "weighted_score"
    WEIGHTED_VOTE = "weighted_vote"
    IC_WEIGHTED = "ic_weighted"


class StrategyType:
    """策略类型 — 决定策略适用场景

    - SELECTION: 截面选股策略 (产出候选标的池，方向 bullish/bearish)
    - TIMING: 时序回测策略 (对给定标的逐 bar 产生 buy/sell 信号)
    """
    SELECTION = "selection"
    TIMING = "timing"


class BacktestRunStatus:
    """回测运行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
