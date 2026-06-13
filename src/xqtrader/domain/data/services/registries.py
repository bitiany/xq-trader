"""数据类型与数据表显示名称注册表 — 策略模式，避免 if/elif 分支。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataTypeEntry:
    """数据类型显示名称条目。"""

    display_name: str
    display_name_en: str


@dataclass(frozen=True)
class TableEntry:
    """数据表标签条目。"""

    label: str
    label_en: str


class DataTypeRegistry:
    """数据类型显示名称注册表 — data_type → 显示名称映射。"""

    _entries: dict[str, DataTypeEntry] = {}

    @classmethod
    def register(cls, data_type: str, display_name: str, display_name_en: str) -> None:
        cls._entries[data_type] = DataTypeEntry(
            display_name=display_name,
            display_name_en=display_name_en,
        )

    @classmethod
    def get(cls, data_type: str) -> DataTypeEntry:
        return cls._entries.get(
            data_type,
            DataTypeEntry(display_name=data_type, display_name_en=data_type),
        )

    @classmethod
    def all_names(cls) -> set[str]:
        return set(cls._entries.keys())


class TableRegistry:
    """数据表标签注册表 — table_name → 显示标签映射。"""

    _entries: dict[str, TableEntry] = {}

    @classmethod
    def register(cls, table_name: str, label: str, label_en: str) -> None:
        cls._entries[table_name] = TableEntry(label=label, label_en=label_en)

    @classmethod
    def get(cls, table_name: str) -> TableEntry:
        return cls._entries.get(
            table_name,
            TableEntry(label=table_name, label_en=table_name),
        )


# ── 注册已知数据类型 ──
DataTypeRegistry.register("daily_kline", "A股日线行情", "Daily Kline")
DataTypeRegistry.register("daily_indicator", "每日指标", "Daily Indicator")
DataTypeRegistry.register("sw_daily", "申万行业日线", "SW Industry Daily")
DataTypeRegistry.register("index_daily", "指数日线", "Index Daily")
DataTypeRegistry.register("fund_flow", "个股资金流向", "Fund Flow")
DataTypeRegistry.register("factor_compute", "因子计算", "Factor Compute")
DataTypeRegistry.register("balance_sheet", "资产负债表", "Balance Sheet")
DataTypeRegistry.register("income_statement", "利润表", "Income Statement")
DataTypeRegistry.register("cash_flow", "现金流量表", "Cash Flow Statement")
DataTypeRegistry.register("financial_indicator", "财务指标", "Financial Indicator")

# ── 注册已知数据表 ──
TableRegistry.register("t_collect_watermark", "采集水位", "Collection Watermark")
TableRegistry.register("t_trade_calendar", "交易日历", "Trade Calendar")
TableRegistry.register("t_daily_kline", "日线行情", "Daily Kline")
TableRegistry.register("t_daily_indicator", "每日指标", "Daily Indicator")
TableRegistry.register("t_sw_daily", "申万行业日线", "SW Industry Daily")
TableRegistry.register("t_index_daily", "指数日线", "Index Daily")
TableRegistry.register("t_fund_flow", "资金流向", "Fund Flow")
TableRegistry.register("t_factor_value", "因子值", "Factor Value")
TableRegistry.register("t_factor_pool", "因子池", "Factor Pool")
TableRegistry.register("t_factor_registry", "因子注册表", "Factor Registry")
TableRegistry.register("t_factor_stats", "因子统计", "Factor Stats")
TableRegistry.register("sch_task_def", "任务定义", "Task Definition")
TableRegistry.register("sch_task_exec", "任务执行记录", "Task Execution")
TableRegistry.register("sch_pipeline_def", "编排定义", "Pipeline Definition")
TableRegistry.register("t_security", "证券信息", "Security Info")
TableRegistry.register("t_task_schedule_history", "调度历史", "Schedule History")
TableRegistry.register("sdc_candlestick_daily", "日线K线(SDC)", "Daily Kline (SDC)")
TableRegistry.register("sdc_daily_indicator", "每日指标(SDC)", "Daily Indicator (SDC)")
TableRegistry.register("sdc_factor_value", "因子值(SDC)", "Factor Value (SDC)")
TableRegistry.register("sdc_factor_stats", "因子统计(SDC)", "Factor Stats (SDC)")
TableRegistry.register("sdc_index_daily", "指数日线(SDC)", "Index Daily (SDC)")
TableRegistry.register("sdc_balance_sheet", "资产负债表(SDC)", "Balance Sheet (SDC)")
TableRegistry.register("sdc_income_statement", "利润表(SDC)", "Income Statement (SDC)")
TableRegistry.register("sdc_cash_flow", "现金流量表(SDC)", "Cash Flow (SDC)")
TableRegistry.register("sdc_financial_indicator", "财务指标(SDC)", "Financial Indicator (SDC)")
TableRegistry.register("sdc_sample_pool", "样本池(SDC)", "Sample Pool (SDC)")
TableRegistry.register("sdc_alpha_signal", "Alpha信号(SDC)", "Alpha Signal (SDC)")
TableRegistry.register("sdc_plugin_registry", "插件注册表(SDC)", "Plugin Registry (SDC)")
TableRegistry.register("sdc_ml_model", "ML模型(SDC)", "ML Model (SDC)")
TableRegistry.register("fac_signal_value", "信号值", "Signal Value")
