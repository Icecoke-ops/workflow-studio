"""引擎统一异常。"""


class WorkflowError(Exception):
    """所有引擎异常的基类。"""


class PluginLoadError(WorkflowError):
    """插件 zip 加载失败。"""


class SchemaError(WorkflowError):
    """插件声明的 schema 本身不合法。"""


class TypeIdError(WorkflowError):
    """类型标识格式不合法。"""


class ExecutionError(WorkflowError):
    """节点执行失败。"""

    def __init__(self, message, node_id=None):
        super().__init__(message)
        self.node_id = node_id
