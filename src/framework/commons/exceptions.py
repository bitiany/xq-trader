"""业务异常定义。"""


class BusinessException(Exception):  # noqa: N818
    """可预期的业务异常，由中间件/异常处理器统一转换为 API 响应。"""

    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)


class UnauthorizedException(BusinessException):
    def __init__(self, message: str = "未授权访问"):
        super().__init__(message=message, code=401)


class NotFoundException(BusinessException):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message=message, code=404)


class ConflictException(BusinessException):
    def __init__(self, message: str = "数据冲突"):
        super().__init__(message=message, code=409)


# ==================== Broker 异常层级 ====================

class BrokerError(BusinessException):
    """Broker 基础异常。"""


class BrokerConnectionError(BrokerError):
    """Broker 连接异常。"""

    def __init__(self, message: str = "Broker 连接未建立"):
        super().__init__(message=message, code=503)


class BrokerConfigError(BrokerError):
    """Broker 配置异常。"""

    def __init__(self, message: str = "Broker 配置缺失"):
        super().__init__(message=message, code=500)


class DataCollectionError(BusinessException):
    """数据采集异常。"""

    def __init__(self, message: str = "数据采集失败"):
        super().__init__(message=message, code=500)


# ==================== Worker/Scheduler 异常层级 ====================

class WorkerError(Exception):
    """Worker 基础异常。"""


class WorkerNotInitializedError(WorkerError):
    """Worker 组件未初始化。"""


class TaskNotFoundError(WorkerError):
    """任务未找到。"""


class InvalidWorkflowError(WorkerError):
    """无效的工作流定义。"""


class OrchestrationNotFoundError(WorkerError):
    """编排记录未找到。"""


class RecoveryFailedError(WorkerError):
    """编排恢复失败。"""


class SchedulerNotInitializedError(WorkerError):
    """调度器未初始化。"""


class InvalidCronExpressionError(WorkerError):
    """无效的 cron 表达式。"""


class InvalidCycleWindowError(WorkerError):
    """无效的周期窗口。"""


class CyclicDependencyError(WorkerError):
    """检测到循环依赖。"""


class UnknownDependencyError(WorkerError):
    """未知的依赖任务。"""


class PipelineNotFoundError(WorkerError):
    """编排未找到或无步骤。"""


# ==================== 工作流异常层级 ====================

class WorkflowError(Exception):
    """工作流基础异常。"""


class WorkflowConfigError(WorkflowError):
    """工作流配置错误（JSON 解析失败、必需字段缺失等）。"""


class WorkflowNodeError(WorkflowError):
    """节点执行错误。"""

    def __init__(self, node_id: str, node_type: str, message: str):
        self.node_id = node_id
        self.node_type = node_type
        super().__init__(f"Node [{node_id}] ({node_type}): {message}")


class WorkflowConditionError(WorkflowError):
    """条件分支未匹配错误。"""

    def __init__(self, node_id: str, cases: list[str]):
        self.node_id = node_id
        self.cases = cases
        super().__init__(
            f"SwitchNode [{node_id}] no branch matched, cases: {cases}"
        )


class WorkflowResumeError(WorkflowError):
    """工作流恢复错误（resume_value 格式不正确等）。"""


class WorkflowToolLoadError(WorkflowError):
    """工具类加载失败。"""
