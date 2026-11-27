"""引擎统一异常。"""


class WorkflowError(Exception):
    """所有引擎异常的基类。"""


class PluginLoadError(WorkflowError):
    """插件目录加载失败。"""


class PluginNameConflict(PluginLoadError):
    """插件名重复（全局与项目之间、或同批目录之间）。宽容模式也必须抛出。"""


class SchemaError(WorkflowError):
    """插件声明的 schema 本身不合法。"""


class TypeIdError(WorkflowError):
    """类型标识格式不合法。"""


class HookError(WorkflowError):
    """钩子加载、安装或注册失败。"""


class ValidationFailed(WorkflowError):
    """工作流校验未通过；report 带着全部错误与警告。"""

    def __init__(self, report):
        super().__init__(f"工作流校验未通过，共 {len(report.errors)} 条错误")
        self.report = report


class RunAborted(WorkflowError):
    """钩子回调抛异常，整轮运行中止；原异常挂在 __cause__。"""


class ExecutionError(WorkflowError):
    """节点执行失败。"""

    def __init__(self, message, node_id=None):
        super().__init__(message)
        self.node_id = node_id


class MissingInput(ExecutionError):
    """节点缺少上游输入，无法执行。"""
