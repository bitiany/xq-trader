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
