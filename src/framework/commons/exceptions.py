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
