"""插件与引擎之间的接口约定。

每个组件类必须：

* 继承 :class:`Component`
* 提供 ``name`` / ``title`` / ``desc``
* 实现三个静态方法：``config_schema()`` / ``input_schema()`` / ``output_schema()``
* 实现 ``__init__(self, config)`` 与 ``invoke(self, **inputs)``
* 可选实现 ``close()``
"""

from abc import ABC, abstractmethod


class Component(ABC):
    """所有插件组件必须实现的接口。"""

    name: str = ""
    title: str = ""
    desc: str = ""

    @staticmethod
    @abstractmethod
    def config_schema() -> dict:
        """返回初始化参数 schema。"""

    @staticmethod
    @abstractmethod
    def input_schema() -> dict:
        """返回输入端口 schema。"""

    @staticmethod
    @abstractmethod
    def output_schema() -> dict:
        """返回输出端口 schema。"""

    @abstractmethod
    def __init__(self, config: dict) -> None:
        """节点初始化。config 已按 schema 校验并补齐默认值。"""

    @abstractmethod
    def invoke(self, **inputs):
        """执行节点，返回 {输出端口名: 值}。"""

    def close(self) -> None:
        """可选：释放资源，引擎在流程结束后调用。"""


class PredictorModel(ABC):
    """标准模型契约：``std_1.0@model`` 的载体必须继承它。

    两道强制：

    * 继承但没实现 ``predict`` → 构造模型时就抛 ``TypeError``（产出方节点里）
    * 没继承 → 引擎的输出类型校验拦住，报在产出方节点和端口上
    """

    @abstractmethod
    def predict(self, frame):
        """输入 pandas.DataFrame，返回与行数等长的预测值。"""
