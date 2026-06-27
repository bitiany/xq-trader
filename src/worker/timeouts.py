"""Worker 任务超时配置（秒）。

因子计算/评估/合成等重任务默认 24h；Redis visibility_timeout 须大于最长 time_limit。
"""

# 重计算任务（因子计算、评估、合成、日频采集等）
LONG_TASK_TIMEOUT = 86400  # 24h

# Redis broker 消息可见性（须 > LONG_TASK_TIMEOUT，避免任务未完成被重新投递）
BROKER_VISIBILITY_TIMEOUT = LONG_TASK_TIMEOUT + 3600  # 25h
