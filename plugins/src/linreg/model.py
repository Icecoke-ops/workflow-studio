"""插件内的模型对象，作为 ``std_1.0@model`` 的载体。

必须继承 ``engine.api.PredictorModel``：
少实现 ``predict`` 会在构造时就抛 TypeError，没继承会被引擎的输出校验拦住。
"""

from engine.api import PredictorModel


class LinearModel(PredictorModel):
    def __init__(self, coef, intercept, feature, target, n_samples):
        self.coef = float(coef)
        self.intercept = float(intercept)
        self.feature = feature
        self.target = target
        self.n_samples = int(n_samples)

    def predict(self, frame):
        x = frame[self.feature].to_numpy(dtype=float)
        return self.coef * x + self.intercept

    def __repr__(self):
        return (
            f"LinearModel({self.target} = {self.coef:.4f} * {self.feature} "
            f"+ {self.intercept:.4f}, 样本 {self.n_samples})"
        )
