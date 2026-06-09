"""个股资金流向采集插件 — 基于 Pipeline 引擎的逐标并发采集（Tushare 原生数据源）。"""

from worker.plugins.fund_flow_dc.task import FundFlowCollectTask  # noqa: F401
