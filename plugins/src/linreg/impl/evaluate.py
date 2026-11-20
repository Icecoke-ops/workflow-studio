"""回归指标：mse / rmse / mae / r2。"""

from engine.api import Component


class Evaluate(Component):
    name = "Evaluate"
    title = "评估回归"
    desc = "对比真实值与预测值，输出 mse / rmse / mae / r2"

    @staticmethod
    def config_schema():
        return {
            "target": {
                "type": "string",
                "title": "真实值列",
                "desc": "真实值所在列，要与训练时保持一致",
                "default": "y",
                "required": True,
            },
            "pred_column": {
                "type": "string",
                "title": "预测值列",
                "desc": "预测值列名，通常由通用预测组件生成的 y_pred",
                "default": "y_pred",
                "required": True,
            },
        }

    @staticmethod
    def input_schema():
        return {
            "true_data": {"types": ["std_1.0@table"], "required": True, "title": "真实数据"},
            "predictions": {"types": ["std_1.0@table"], "required": True, "title": "预测结果"},
        }

    @staticmethod
    def output_schema():
        return {"metrics": {"type": "std_1.0@table", "title": "指标表"}}

    def __init__(self, config):
        self.target = config["target"]
        self.pred_column = config["pred_column"]

    def invoke(self, true_data, predictions):
        import numpy as np
        import pandas as pd

        if self.target not in true_data.columns:
            raise ValueError(f"列不存在：{self.target}（可用：{list(true_data.columns)}）")
        if self.pred_column not in predictions.columns:
            raise ValueError(
                f"列不存在：{self.pred_column}（可用：{list(predictions.columns)}）"
            )

        truth = true_data[self.target].to_numpy(dtype=float)
        predicted = predictions[self.pred_column].to_numpy(dtype=float)
        if len(truth) != len(predicted):
            raise ValueError(
                f"行数不一致：真实数据 {len(truth)} 行，预测结果 {len(predicted)} 行"
            )

        residual = truth - predicted
        mse = float(np.mean(residual**2))
        rmse = float(np.sqrt(mse))
        mae = float(np.mean(np.abs(residual)))
        total = float(np.sum((truth - truth.mean()) ** 2))
        r2 = 1.0 - float(np.sum(residual**2)) / total if total > 0 else float("nan")

        return {
            "metrics": pd.DataFrame(
                {"metric": ["mse", "rmse", "mae", "r2"], "value": [mse, rmse, mae, r2]}
            )
        }
