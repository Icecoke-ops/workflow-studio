"""通用预测：任何符合 std_1.0@model 契约的模型都能接。

通用预测组件：core.PredictModel —— 模型是通用的，预测也是。
"""

from engine.api import Component


class PredictModel(Component):
    name = "PredictModel"
    title = "通用预测"
    desc = "用模型算出每行的预测值并新增一列"

    @staticmethod
    def config_schema():
        return {
            "output_column": {
                "type": "string",
                "title": "预测列名",
                "desc": "生成的预测值写进这一列，不能与已有列重名",
                "default": "y_pred",
            }
        }

    @staticmethod
    def input_schema():
        return {
            "model": {"types": ["std_1.0@model"], "required": True, "title": "模型"},
            "data": {"types": ["std_1.0@table"], "required": True, "title": "数据表"},
        }

    @staticmethod
    def output_schema():
        return {"predictions": {"type": "std_1.0@table", "title": "带预测值的表"}}

    def __init__(self, config):
        self.output_column = config["output_column"]

    def invoke(self, model, data):
        if self.output_column in data.columns:
            raise ValueError(f"列已存在：{self.output_column}")
        result = data.copy()
        result[self.output_column] = model.predict(result)
        return {"predictions": result}
