"""生成一条带噪声的直线数据。"""

from engine.api import Component


class MakeLinearData(Component):
    name = "MakeLinearData"
    title = "生成线性数据"
    desc = "y = slope * x + intercept + noise * N(0, 1)，固定 seed 可复现"

    @staticmethod
    def config_schema():
        return {
            "n_samples": {
                "type": "integer",
                "title": "样本数",
                "desc": "生成多少个样本点，越多拟合越稳但越慢",
                "default": 200,
                "min": 20,
                "max": 100000,
            },
            "slope": {
                "type": "number",
                "title": "真实斜率",
                "desc": "数据的真实斜率，用来对照拟合结果",
                "default": 2.0,
                "step": 0.1,
            },
            "intercept": {
                "type": "number",
                "title": "真实截距",
                "desc": "数据的真实截距",
                "default": 1.0,
                "step": 0.1,
            },
            "noise": {
                "type": "number",
                "title": "噪声强度",
                "desc": "高斯噪声标准差，0 表示点完全落在直线上",
                "default": 0.5,
                "min": 0,
                "max": 50,
                "step": 0.1,
            },
            "x_max": {
                "type": "number",
                "title": "x 上限",
                "desc": "x 在 0 ~ 此值之间均匀取值",
                "default": 10.0,
                "min": 0.1,
            },
            "seed": {
                "type": "integer",
                "title": "随机种子",
                "desc": "固定后每次生成的数据完全一致",
                "default": 42,
            },
        }

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"data": {"type": "std_1.0@table", "title": "数据表（x, y）"}}

    def __init__(self, config):
        self.n_samples = config["n_samples"]
        self.slope = config["slope"]
        self.intercept = config["intercept"]
        self.noise = config["noise"]
        self.x_max = config["x_max"]
        self.seed = config["seed"]

    def invoke(self):
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(self.seed)
        x = rng.uniform(0.0, self.x_max, self.n_samples)
        if self.noise > 0:
            perturbation = rng.normal(0.0, 1.0, self.n_samples) * self.noise
        else:
            perturbation = np.zeros(self.n_samples)
        y = self.slope * x + self.intercept + perturbation
        return {"data": pd.DataFrame({"x": x, "y": y})}
