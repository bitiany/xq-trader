"""管道引擎异常定义。"""


class PipelineError(Exception):
    """管道引擎基础异常。"""


class PipelineStageError(PipelineError):
    """Stage 执行异常。"""

    def __init__(self, stage_name: str, item: object, message: str):
        self.stage_name = stage_name
        self.item = item
        super().__init__(f"Stage [{stage_name}] failed for item {item!r}: {message}")


class PipelineAspectError(PipelineError):
    """Aspect 执行异常。"""

    def __init__(self, aspect_name: str, hook: str, item: object, message: str):
        self.aspect_name = aspect_name
        self.hook = hook
        self.item = item
        super().__init__(f"Aspect [{aspect_name}].{hook} failed for item {item!r}: {message}")
