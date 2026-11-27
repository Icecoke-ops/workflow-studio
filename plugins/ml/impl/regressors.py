"""5 个回归模型组件：一个模型一个组件，不做「下拉选模型」。"""

from engine.api import Component
from ml.impl.model import SklearnModel, to_matrix


def model_schema(extra):
    schema = {
        "feature": {
            "type": "array",
            "title": "特征列",
            "desc": "参与训练的数值列名数组，例如 [\"x1\", \"x2\"]",
            "required": True,
            "min": 1,
        },
        "target": {
            "type": "string",
            "title": "目标列",
            "desc": "要预测的数值列名",
            "required": True,
        },
    }
    schema.update(extra)
    return schema


class _Regressor(Component):
    sklearn_module = ""
    sklearn_name = ""
    param_names = ()

    @staticmethod
    def input_schema():
        return {
            "data": {"types": ["std_1.0@table"], "required": True, "title": "训练数据"}
        }

    @staticmethod
    def output_schema():
        return {"model": {"type": "std_1.0@model", "title": "模型"}}

    def __init__(self, config):
        self.feature = list(config["feature"])
        self.target = config["target"]
        self.estimator = _make_estimator(
            self.sklearn_module,
            self.sklearn_name,
            {
                name: config[name]
                for name in self.param_names
                if config.get(name) is not None
            },
        )

    def invoke(self, data):
        matrix = to_matrix(data, self.feature, "特征")
        target = to_matrix(data, [self.target], "目标")[:, 0]
        try:
            self.estimator.fit(matrix, target)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{self.sklearn_name} 训练失败（特征 {self.feature}，目标 {self.target}）：{exc}"
            ) from exc
        return {"model": SklearnModel(self.estimator, self.feature, self.target)}


def _make_estimator(module, name, kwargs):
    import importlib

    estimator_cls = getattr(importlib.import_module(f"sklearn.{module}"), name)
    return estimator_cls(**kwargs)


class LinearRegression(_Regressor):
    name = "LinearRegression"
    title = "线性回归"
    desc = "拟合线性关系并输出回归模型"
    sklearn_module = "linear_model"
    sklearn_name = "LinearRegression"
    param_names = ("fit_intercept",)

    @staticmethod
    def config_schema():
        return model_schema(
            {
                "fit_intercept": {
                    "type": "boolean",
                    "title": "拟合截距",
                    "desc": "取消则强制直线过原点",
                    "default": True,
                }
            }
        )


class Ridge(_Regressor):
    name = "Ridge"
    title = "岭回归"
    desc = "拟合线性关系并抑制过拟合，输出回归模型"
    sklearn_module = "linear_model"
    sklearn_name = "Ridge"
    param_names = ("alpha", "fit_intercept")

    @staticmethod
    def config_schema():
        return model_schema(
            {
                "alpha": {
                    "type": "number",
                    "title": "正则强度",
                    "desc": "越大正则越强；0 等价于普通最小二乘",
                    "default": 1.0,
                    "min": 0,
                    "step": 0.1,
                },
                "fit_intercept": {
                    "type": "boolean",
                    "title": "拟合截距",
                    "desc": "取消则不拟合截距",
                    "default": True,
                },
            }
        )


class Lasso(_Regressor):
    name = "Lasso"
    title = "Lasso 回归"
    desc = "拟合线性关系并淘汰不重要的特征，输出回归模型"
    sklearn_module = "linear_model"
    sklearn_name = "Lasso"
    param_names = ("alpha", "max_iter")

    @staticmethod
    def config_schema():
        return model_schema(
            {
                "alpha": {
                    "type": "number",
                    "title": "正则强度",
                    "desc": "越大被压成 0 的系数越多",
                    "default": 1.0,
                    "min": 0,
                    "step": 0.1,
                },
                "max_iter": {
                    "type": "integer",
                    "title": "最大迭代次数",
                    "desc": "坐标下降的迭代上限",
                    "default": 1000,
                    "min": 1,
                },
            }
        )


class RandomForestRegressor(_Regressor):
    name = "RandomForestRegressor"
    title = "随机森林回归"
    desc = "拟合复杂的非线性关系，输出回归模型"
    sklearn_module = "ensemble"
    sklearn_name = "RandomForestRegressor"
    param_names = ("n_estimators", "max_depth", "random_state")

    @staticmethod
    def config_schema():
        return model_schema(
            {
                "n_estimators": {
                    "type": "integer",
                    "title": "树的数量",
                    "desc": "越多越稳、也越慢",
                    "default": 100,
                    "min": 1,
                },
                "max_depth": {
                    "type": "integer",
                    "title": "最大深度",
                    "desc": "留空表示不限制",
                    "min": 1,
                },
                "random_state": {
                    "type": "integer",
                    "title": "随机种子",
                    "desc": "固定后每次训练结果一致",
                },
            }
        )


class GradientBoostingRegressor(_Regressor):
    name = "GradientBoostingRegressor"
    title = "梯度提升回归"
    desc = "逐棵拟合残差，输出能抓住复杂非线性关系的回归模型"
    sklearn_module = "ensemble"
    sklearn_name = "GradientBoostingRegressor"
    param_names = ("n_estimators", "learning_rate", "max_depth")

    @staticmethod
    def config_schema():
        return model_schema(
            {
                "n_estimators": {
                    "type": "integer",
                    "title": "树的数量",
                    "desc": "提升轮数，越多越慢",
                    "default": 100,
                    "min": 1,
                },
                "learning_rate": {
                    "type": "number",
                    "title": "学习率",
                    "desc": "每棵树贡献的缩放，越小需要越多轮",
                    "default": 0.1,
                    "min": 0,
                    "step": 0.01,
                },
                "max_depth": {
                    "type": "integer",
                    "title": "最大深度",
                    "desc": "单棵树深度上限",
                    "default": 3,
                    "min": 1,
                },
            }
        )
