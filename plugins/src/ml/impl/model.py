"""插件内的 sklearn 模型对象，作为 ``std_1.0@model`` 的载体。

``core.PredictModel`` 会把整张表传进来，所以 ``predict`` 必须按
``feature_columns`` 自己选列，否则 id 列、目标列都会进模型。
"""

from engine.api import PredictorModel


def to_matrix(frame, columns, role):
    """取出若干列并按数值矩阵返回；缺列、非数值都给出中文错误。"""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{role}列不存在：{missing}（可用：{list(frame.columns)}）")
    try:
        return frame[columns].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{role}列必须是数值：{columns}（{exc}）") from exc


class SklearnModel(PredictorModel):
    def __init__(self, estimator, feature_columns, target):
        self.estimator = estimator
        self.feature_columns = list(feature_columns)
        self.target = target

    def predict(self, frame):
        matrix = to_matrix(frame, self.feature_columns, "特征")
        try:
            return self.estimator.predict(matrix)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"预测失败（特征列 {self.feature_columns}）：{exc}"
            ) from exc

    def __repr__(self):
        estimator_name = type(self.estimator).__name__
        return f"SklearnModel({estimator_name}: {self.target} ~ {' + '.join(self.feature_columns)})"
