"""回归指标评估：真实值与预测值按行序一一对应。"""

from engine.api import Component
from ml.impl.model import to_matrix

_ALLOWED = ("mse", "rmse", "mae", "r2", "mape")


class EvaluateRegression(Component):
    name = "EvaluateRegression"
    title = "回归评估"
    desc = "计算 mse / rmse / mae / r2 / mape；真实值与预测值按行序一一对应"

    @staticmethod
    def config_schema():
        return {
            "target": {
                "type": "string",
                "title": "真实列",
                "desc": "真实数据里的目标列名",
                "required": True,
            },
            "pred_column": {
                "type": "string",
                "title": "预测列",
                "desc": "预测数据里的预测值列名",
                "default": "y_pred",
            },
            "metrics": {
                "type": "array",
                "title": "指标",
                "desc": "要计算的指标名数组，默认全部；mape 为比例（0.1 表示 10%）",
                "default": list(_ALLOWED),
                "min": 1,
            },
        }

    @staticmethod
    def input_schema():
        return {
            "true_data": {
                "types": ["std_1.0@table"],
                "required": True,
                "title": "真实数据",
            },
            "predictions": {
                "types": ["std_1.0@table"],
                "required": True,
                "title": "预测数据",
            },
        }

    @staticmethod
    def output_schema():
        return {
            "metrics": {"type": "std_1.0@table", "title": "指标表（metric / value）"}
        }

    def __init__(self, config):
        self.target = config["target"]
        self.pred_column = config["pred_column"]
        self.metrics = list(config["metrics"])
        unknown = [metric for metric in self.metrics if metric not in _ALLOWED]
        if unknown:
            raise ValueError(f"未知指标 {unknown}（可选：{list(_ALLOWED)}）")

    def invoke(self, true_data, predictions):
        if len(true_data) != len(predictions):
            raise ValueError(
                f"行数不一致：真实数据 {len(true_data)} 行，预测数据 {len(predictions)} 行；"
                "预测必须来自同一批行"
            )
        y_true = to_matrix(true_data, [self.target], "真实")[:, 0]
        y_pred = to_matrix(predictions, [self.pred_column], "预测")[:, 0]

        values = {metric: self._compute(metric, y_true, y_pred) for metric in self.metrics}

        import pandas as pd

        table = pd.DataFrame(
            {"metric": self.metrics, "value": [values[m] for m in self.metrics]}
        )
        return {"metrics": table}

    def _compute(self, metric, y_true, y_pred):
        from sklearn import metrics

        if metric == "mse":
            return float(metrics.mean_squared_error(y_true, y_pred))
        if metric == "rmse":
            return float(metrics.mean_squared_error(y_true, y_pred)) ** 0.5
        if metric == "mae":
            return float(metrics.mean_absolute_error(y_true, y_pred))
        if metric == "r2":
            return float(metrics.r2_score(y_true, y_pred))
        zeros = int((y_true == 0).sum())
        if zeros:
            # mape 的分母是真实值，含 0 时结果无意义；宁可报错也不悄悄换分母。
            raise ValueError(
                f"mape 无法计算：真实列 {self.target} 有 {zeros} 个 0；"
                "请改用 mae / rmse，或从 metrics 里去掉 mape"
            )
        return float(metrics.mean_absolute_percentage_error(y_true, y_pred))
