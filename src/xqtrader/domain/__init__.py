"""领域模块 — 启动时确保所有模型被 import，以便 DatasourceManager 自动发现并建表。"""

# 新因子系统模型（fac_ 前缀新表）
import xqtrader.domain.factor.models  # noqa: F401
