"""ml 插件组件行为测试：5 个回归模型与 EvaluateRegression。

直接运行：python tests/test_ml.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.api import PredictorModel

from _harness import check, expect_raises, get_registry, invoke, run_cases


def training_frame():
    rng = np.random.default_rng(7)
    x1 = rng.uniform(0.0, 10.0, 80)
    x2 = rng.uniform(0.0, 5.0, 80)
    y = 2.0 * x1 - 3.0 * x2 + 1.0 + rng.normal(0.0, 0.1, 80)
    return pd.DataFrame({"x1": x1, "x2": x2, "y": y})


def train(component, config=None):
    full = {"feature": ["x1", "x2"], "target": "y"}
    full.update(config or {})
    return invoke(
        get_registry(), "ml", component, full, data=training_frame()
    )["model"]


def assert_predicts(component, config=None):
    model = train(component, config)
    check(
        isinstance(model, PredictorModel),
        f"{component} 的输出必须继承 PredictorModel，实际 {type(model).__name__}",
    )
    predictions = model.predict(training_frame()[["x1", "x2"]])
    check(len(predictions) == len(training_frame()), f"{component} 预测行数不对")
    return model


def case_linear_regression():
    assert_predicts("LinearRegression")


def case_ridge():
    assert_predicts("Ridge")


def case_lasso():
    assert_predicts("Lasso")


def case_random_forest():
    assert_predicts("RandomForestRegressor", {"n_estimators": 20, "random_state": 0})


def case_gradient_boosting():
    assert_predicts(
        "GradientBoostingRegressor", {"n_estimators": 20, "max_depth": 2}
    )


def case_extra_columns_ignored():
    """训练表里的 id / cat 不能进模型：预测时它们换成完全不同的值，结果也不能变。"""
    data = training_frame()
    data["id"] = np.arange(len(data)) + 1000
    data["cat"] = ["a", "b"] * (len(data) // 2)

    model = invoke(
        get_registry(),
        "ml",
        "LinearRegression",
        {"feature": ["x1", "x2"], "target": "y"},
        data=data,
    )["model"]

    frame = training_frame()
    frame["id"] = -1
    frame["cat"] = "zzz"
    with_extras = model.predict(frame)
    features_only = model.predict(frame[["x1", "x2"]])
    check(
        np.allclose(with_extras, features_only),
        "预测结果被额外列影响了：模型没有按 feature_columns 选列",
    )


def _evaluate_frame():
    return pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0, 5.0]})


def _prediction_frame():
    return pd.DataFrame({"y_pred": [1.1, 1.9, 3.2, 3.8, 5.0]})


def case_evaluate_metrics_match_hand_calc():
    result = invoke(
        get_registry(),
        "ml",
        "EvaluateRegression",
        {"target": "y", "pred_column": "y_pred"},
        true_data=_evaluate_frame(),
        predictions=_prediction_frame(),
    )["metrics"]
    values = result.set_index("metric")["value"]

    y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y_pred = np.array([1.1, 1.9, 3.2, 3.8, 5.0])
    residual = y_true - y_pred
    expected = {
        "mse": float(np.mean(residual**2)),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "mae": float(np.mean(np.abs(residual))),
        "r2": float(1.0 - np.sum(residual**2) / np.sum((y_true - y_true.mean()) ** 2)),
        "mape": float(np.mean(np.abs(residual / y_true))),
    }
    for metric, wanted in expected.items():
        check(metric in values.index, f"指标表缺少 {metric}：{list(values.index)}")
        actual = float(values[metric])
        check(
            abs(actual - wanted) <= 1e-9,
            f"{metric} 与手算不一致：{actual!r} vs {wanted!r}",
        )


def case_evaluate_row_count_mismatch():
    predictions = _prediction_frame().iloc[:3]
    expect_raises(
        ValueError,
        lambda: invoke(
            get_registry(),
            "ml",
            "EvaluateRegression",
            {"target": "y", "pred_column": "y_pred"},
            true_data=_evaluate_frame(),
            predictions=predictions,
        ),
        "行数不一致",
    )


def case_evaluate_mape_zero_target():
    true_data = pd.DataFrame({"y": [0.0, 1.0, 2.0]})
    predictions = pd.DataFrame({"y_pred": [0.1, 1.1, 2.1]})
    expect_raises(
        ValueError,
        lambda: invoke(
            get_registry(),
            "ml",
            "EvaluateRegression",
            {"target": "y", "pred_column": "y_pred"},
            true_data=true_data,
            predictions=predictions,
        ),
        "mape",
        "真实列 y",
    )


CASES = [
    ("LinearRegression 训练并输出 PredictorModel", case_linear_regression),
    ("Ridge 训练并输出 PredictorModel", case_ridge),
    ("Lasso 训练并输出 PredictorModel", case_lasso),
    ("RandomForestRegressor 训练并输出 PredictorModel", case_random_forest),
    ("GradientBoostingRegressor 训练并输出 PredictorModel", case_gradient_boosting),
    ("额外列（id/cat）不参与预测", case_extra_columns_ignored),
    ("EvaluateRegression 五项指标与手算一致", case_evaluate_metrics_match_hand_calc),
    ("EvaluateRegression 行数不一致报错", case_evaluate_row_count_mismatch),
    ("EvaluateRegression mape 遇真实值 0 报错指列名", case_evaluate_mape_zero_target),
]


def main():
    return run_cases("ml", CASES)


if __name__ == "__main__":
    sys.exit(main())
