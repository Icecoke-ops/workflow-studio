"""最小二乘拟合 y = coef * x + intercept。"""

from engine.api import Component
from linreg.model import LinearModel


class FitLinearRegression(Component):
    name = "FitLinearRegression"
    title = "拟合线性回归"
    desc = "对指定特征列和目标列做最小二乘拟合"

    @staticmethod
    def config_schema():
        return {
            "feature": {
                "type": "string",
                "title": "特征列",
                "desc": "用作自变量的列名",
                "default": "x",
                "required": True,
            },
            "target": {
                "type": "string",
                "title": "目标列",
                "desc": "要预测的目标列名",
                "default": "y",
                "required": True,
            },
            "fit_intercept": {
                "type": "boolean",
                "title": "拟合截距",
                "desc": "关闭后强制直线过原点（截距为 0）",
                "default": True,
            },
        }

    @staticmethod
    def input_schema():
        return {"data": {"types": ["std_1.0@table"], "required": True, "title": "训练数据"}}

    @staticmethod
    def output_schema():
        return {"model": {"type": "std_1.0@model", "title": "线性模型"}}

    def __init__(self, config):
        self.feature = config["feature"]
        self.target = config["target"]
        self.fit_intercept = config["fit_intercept"]

    def invoke(self, data):
        import numpy as np

        for column in (self.feature, self.target):
            if column not in data.columns:
                raise ValueError(f"列不存在：{column}（可用：{list(data.columns)}）")

        x = data[self.feature].to_numpy(dtype=float)
        y = data[self.target].to_numpy(dtype=float)
        if len(x) < 2:
            raise ValueError("样本数不足，至少需要 2 个点")

        if self.fit_intercept:
            design = np.column_stack([np.ones_like(x), x])
        else:
            design = x.reshape(-1, 1)

        solution, *_ = np.linalg.lstsq(design, y, rcond=None)
        if self.fit_intercept:
            intercept, coef = solution[0], solution[1]
        else:
            intercept, coef = 0.0, solution[0]

        return {
            "model": LinearModel(coef, intercept, self.feature, self.target, len(x))
        }
