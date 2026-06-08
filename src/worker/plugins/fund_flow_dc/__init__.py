"""个股资金流向采集插件 — 基于 Pipeline 引擎的逐标并发采集（东方财富数据源）。"""

from worker.plugins.fund_flow_dc.task import FundFlowDcCollectTask  # noqa: F401
