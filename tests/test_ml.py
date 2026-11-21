"""ml 插件组件行为测试：5 个回归模型、EvaluateRegression 与模型持久化。

直接运行：python tests/test_ml.py
"""

import io
import json
import os
import pickle
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import __version__ as ENGINE_VERSION
from engine.api import PredictorModel
from engine.registry import Registry

from _harness import (
    check,
    env_guard,
    expect_raises,
    get_registry,
    invoke,
    run_cases,
)


def training_frame():
    rng = np.random.default_rng(7)
    x1 = rng.uniform(0.0, 10.0, 80)
    x2 = rng.uniform(0.0, 5.0, 80)
    y = 2.0 * x1 - 3.0 * x2 + 1.0 + rng.normal(0.0, 0.1, 80)
    return pd.DataFrame({"x1": x1, "x2": x2, "y": y})


def train(component, config=None, registry=None):
    full = {"feature": ["x1", "x2"], "target": "y"}
    full.update(config or {})
    return invoke(
        registry or get_registry(), "ml", component, full, data=training_frame()
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


# --------------------------------------------------------------------------
# SaveModel / LoadModel
# --------------------------------------------------------------------------

_PERSIST_REGISTRY = None


def persistence_registry():
    """持久化用例必须用「当前 sys.modules 里的组件类」，不能用 _harness 的缓存。

    test_runner 里会重新 load 一次真实插件（purge + 重新 import），那之后缓存
    registry 里的模型类已经和 sys.modules 里的对不上，pickle 按名字反查类时会炸
    （Can't pickle ...: it's not the same object as ...）。这里重新 load 一次，
    让类对象和模块对象重新对齐。
    """
    global _PERSIST_REGISTRY
    if _PERSIST_REGISTRY is None:
        _PERSIST_REGISTRY = Registry().load(ROOT / "plugins")
    return _PERSIST_REGISTRY


def _predictions(model, frame=None):
    data = training_frame() if frame is None else frame
    return invoke(
        persistence_registry(), "core", "PredictModel", {}, model=model, data=data
    )["predictions"]


def _save_model(model, path):
    return invoke(
        persistence_registry(), "ml", "SaveModel", {"path": path}, model=model
    )["model"]


def _load_model(path):
    return invoke(persistence_registry(), "ml", "LoadModel", {"path": path})["model"]


def case_save_load_roundtrip():
    """训练 → 存盘 → 同进程读回：预测值必须与内存模型逐位一致。"""
    model = train("LinearRegression", registry=persistence_registry())
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_") as tmp:
        path = Path(tmp) / "model.pkl"
        _save_model(model, str(path))
        check(path.is_file(), f"SaveModel 应写出文件：{path}")
        loaded = _load_model(str(path))
        memory_pred = _predictions(model)["y_pred"].to_numpy()
        file_pred = _predictions(loaded)["y_pred"].to_numpy()
    check(isinstance(loaded, PredictorModel), "读回的模型应仍是 PredictorModel")
    check(
        np.array_equal(memory_pred, file_pred),
        "读回的模型预测值与内存模型不一致",
    )


def case_save_load_cross_process():
    """新起一个 engine run 进程加载同一模型文件，预测结果仍逐位一致。"""
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_process_") as tmp:
        root = Path(tmp)
        model = train("LinearRegression", registry=persistence_registry())
        model_path = root / "model.pkl"
        _save_model(model, str(model_path))

        features_path = root / "features.csv"
        training_frame()[["x1", "x2"]].head(20).to_csv(features_path, index=False)
        # 父进程也用 LoadCSV 读同一份特征：pandas 的 CSV 解析有 1 ulp 误差，
        # 直接拿内存里的原始浮点比会误判，必须让两边喂给模型的是同一批 double。
        loaded_features = invoke(
            get_registry(), "fileio", "LoadCSV", {"path": str(features_path)}
        )["table"]
        parent_csv = root / "parent.csv"
        invoke(
            get_registry(),
            "fileio",
            "SaveCSV",
            {"path": str(parent_csv)},
            data=_predictions(model, loaded_features),
        )

        workflow = {
            "name": "persist-cross-process",
            "nodes": [
                {
                    "id": "n1",
                    "plugin": "fileio",
                    "component": "LoadCSV",
                    "config": {"path": str(root / "features.csv")},
                    "inputs": {},
                },
                {
                    "id": "n2",
                    "plugin": "ml",
                    "component": "LoadModel",
                    "config": {"path": str(model_path)},
                    "inputs": {},
                },
                {
                    "id": "n3",
                    "plugin": "core",
                    "component": "PredictModel",
                    "config": {},
                    "inputs": {
                        "model": {"from": "n2", "port": "model"},
                        "data": {"from": "n1", "port": "table"},
                    },
                },
                {
                    "id": "n4",
                    "plugin": "fileio",
                    "component": "SaveCSV",
                    "config": {"path": str(root / "child.csv")},
                    "inputs": {"data": {"from": "n3", "port": "predictions"}},
                },
            ],
        }
        workflow_path = root / "run.json"
        workflow_path.write_text(
            json.dumps(workflow, ensure_ascii=False), encoding="utf-8"
        )

        log_path = root / "child.log"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        env["PYTHONIOENCODING"] = "utf-8"
        with open(log_path, "wb") as handle:
            completed = subprocess.run(
                [sys.executable, "-m", "engine", "run", str(workflow_path)],
                cwd=tmp,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        check(
            completed.returncode == 0,
            f"新进程执行失败：{log_path.read_text(encoding='utf-8', errors='replace')}",
        )

        child_csv = root / "child.csv"
        check(child_csv.is_file(), "子进程应写出预测 CSV")
        check(
            child_csv.read_bytes() == parent_csv.read_bytes(),
            "跨进程加载模型后的预测与父进程不一致",
        )


def case_save_load_workspace_expansion():
    with env_guard(), tempfile.TemporaryDirectory(prefix="engine_ml_model_env_") as tmp:
        os.environ["workspace"] = tmp
        model = train("LinearRegression", registry=persistence_registry())
        _save_model(model, "${workspace}/model.pkl")
        target = Path(tmp) / "model.pkl"
        check(target.is_file(), f"${{workspace}} 应展开到临时目录：{target}")
        loaded = _load_model("${workspace}/model.pkl")
        check(
            np.array_equal(
                _predictions(model)["y_pred"].to_numpy(),
                _predictions(loaded)["y_pred"].to_numpy(),
            ),
            "经 ${workspace} 读回的模型预测不一致",
        )


def case_load_model_not_model_file():
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_bad_") as tmp:
        path = Path(tmp) / "note.json"
        path.write_text('{"hello": 1}', encoding="utf-8")
        expect_raises(ValueError, lambda: _load_model(str(path)), "不是模型文件")


def case_load_model_wrong_magic():
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_magic_") as tmp:
        path = Path(tmp) / "bad.pkl"
        with open(path, "wb") as handle:
            pickle.dump({"magic": "not-a-model", "model": None}, handle)
        expect_raises(ValueError, lambda: _load_model(str(path)), "不是模型文件")


def case_load_model_missing_file():
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_missing_") as tmp:
        path = Path(tmp) / "nope.pkl"
        expect_raises(
            ValueError, lambda: _load_model(str(path)), "模型文件不存在", str(path)
        )


def case_save_model_missing_parent_dir():
    """与 SaveCSV 一致：父目录不存在就报错，不偷偷建目录。"""
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_dir_") as tmp:
        model = train("LinearRegression", registry=persistence_registry())
        target = Path(tmp) / "no_such_dir" / "model.pkl"
        expect_raises(
            ValueError, lambda: _save_model(model, str(target)), "写入模型失败", str(target)
        )
        check(
            not target.parent.exists(),
            f"SaveModel 不应自动创建父目录：{target.parent}",
        )


def case_save_model_passthrough():
    """输出必须与输入是同一个模型对象，训练 → 保存 → 评估才能串起来。"""
    model = train("LinearRegression", registry=persistence_registry())
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_pass_") as tmp:
        returned = _save_model(model, str(Path(tmp) / "model.pkl"))
    check(returned is model, "SaveModel 应原样透传模型对象，而不是拷贝")


def _mutated_model_file(tmp, mutate):
    """用 SaveModel 正常存一份，再把存档读出来改字段写回，不碰产品代码。"""
    model = train("LinearRegression", registry=persistence_registry())
    path = Path(tmp) / "model.pkl"
    _save_model(model, str(path))
    payload = joblib.load(path)
    mutate(payload)
    joblib.dump(payload, path)
    return model, path


def case_load_model_engine_version_mismatch_warns():
    """引擎版本只警告：加载成功、stderr 有 [警告]，预测值逐位一致。"""
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_engine_") as tmp:
        model, path = _mutated_model_file(
            tmp, lambda payload: payload.update({"engine": "0.0.9"})
        )
        err = io.StringIO()
        with redirect_stderr(err):
            loaded = _load_model(str(path))
        text = err.getvalue()
        memory_pred = _predictions(model)["y_pred"].to_numpy()
        file_pred = _predictions(loaded)["y_pred"].to_numpy()
    check("[警告]" in text, f"引擎版本不符应有 [警告]：{text!r}")
    check("0.0.9" in text, f"警告应带存档里的引擎版本：{text!r}")
    check(ENGINE_VERSION in text, f"警告应带当前引擎版本：{text!r}")
    check(
        np.array_equal(memory_pred, file_pred),
        "引擎版本不符只是警告，预测结果必须与原始模型逐位一致",
    )


def case_load_model_plugin_version_mismatch():
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_pver_") as tmp:
        _, path = _mutated_model_file(
            tmp, lambda payload: payload.update({"plugin_version": "9.9"})
        )
        exc = expect_raises(
            ValueError, lambda: _load_model(str(path)), "ml v9.9", "ml v1.0"
        )
    check("插件版本" in str(exc), f"错误信息应说明插件版本不匹配：{exc}")


def case_load_model_class_mismatch():
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_cls_") as tmp:
        _, path = _mutated_model_file(
            tmp, lambda payload: payload.update({"class": "fake.module.FakeModel"})
        )
        exc = expect_raises(
            ValueError,
            lambda: _load_model(str(path)),
            "fake.module.FakeModel",
            "ml.impl.model.SklearnModel",
        )
    check("模型类不匹配" in str(exc), f"错误信息应说明类不匹配：{exc}")


def case_load_model_same_version_silent():
    """同版本加载不能顺带打警告：只有引擎版本不同才警告。"""
    with tempfile.TemporaryDirectory(prefix="engine_ml_model_quiet_") as tmp:
        model = train("LinearRegression", registry=persistence_registry())
        path = Path(tmp) / "model.pkl"
        _save_model(model, str(path))
        err = io.StringIO()
        with redirect_stderr(err):
            _load_model(str(path))
        text = err.getvalue()
    check(text == "", f"同版本加载不应有 stderr 输出：{text!r}")


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
    ("SaveModel/LoadModel 同进程往返预测逐位一致", case_save_load_roundtrip),
    ("新进程加载保存的模型并复现预测", case_save_load_cross_process),
    ("SaveModel/LoadModel 支持 ${workspace} 展开", case_save_load_workspace_expansion),
    ("LoadModel 读非模型文件报「不是模型文件」", case_load_model_not_model_file),
    ("LoadModel magic 不符报「不是模型文件」", case_load_model_wrong_magic),
    ("LoadModel 文件不存在报路径", case_load_model_missing_file),
    ("SaveModel 父目录不存在报错且不建目录", case_save_model_missing_parent_dir),
    ("SaveModel 原样透传模型对象", case_save_model_passthrough),
    ("引擎版本不符只警告且预测逐位一致", case_load_model_engine_version_mismatch_warns),
    ("插件版本不符硬错并给两个版本号", case_load_model_plugin_version_mismatch),
    ("模型类路径不符硬错并给两个类名", case_load_model_class_mismatch),
    ("同版本加载 stderr 为空", case_load_model_same_version_silent),
]


def main():
    return run_cases("ml", CASES)


if __name__ == "__main__":
    sys.exit(main())
