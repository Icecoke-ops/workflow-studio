"""引擎内置的标准类型（相当于 java.util）与它们绑定的抽象基类。

标准类型**不依赖任何插件**，永远可用。插件可以定义自己的类型给别家引用，
但只有引擎能定义「被继承的契约」——否则每个插件都自称标准，生态就散了。

类型标识：``std_1.0@table``、``std_1.0@model`` ……
"""

from .api import PredictorModel

PLUGIN_NAME = "std"
PLUGIN_VERSION = "1.0"
PLUGIN_TITLE = "标准类型"

TYPES = {
    "table": "表格数据（pandas.DataFrame）",
    "number": "数值（int 或 float）",
    "string": "字符串",
    "boolean": "布尔值",
    "model": "预测模型，载体必须继承 PredictorModel 并实现 predict(frame)",
}

# 类型 -> 必须继承的抽象基类。只有引擎能声明，插件不行。
MODELS = {
    "model": PredictorModel,
}


def type_id(short):
    return f"{PLUGIN_NAME}_{PLUGIN_VERSION}@{short}"
