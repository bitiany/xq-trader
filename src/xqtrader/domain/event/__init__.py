"""舆情事件驱动子模块 — 事件检测、宏观恐慌指数、论点卡触发。

架构文档 §11 业务场景三：舆情事件驱动。

三层能力：
  1. EventDetector — 两层检测（关键词快速 + LLM 精细识别）
  2. MarketFearIndexService — VIX/OVX/GVZ/US10Y 采集 + Fear&Greed 评分
  3. EventThesisService — 事件→论点卡触发（mark_thesis_stale / 更新 catalysts）
"""
