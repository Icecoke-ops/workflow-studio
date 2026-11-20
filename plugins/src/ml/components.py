"""ml 插件声明：sklearn 回归模型与评估。"""

from ml.impl.evaluate import EvaluateRegression
from ml.impl.regressors import (
    GradientBoostingRegressor,
    Lasso,
    LinearRegression,
    RandomForestRegressor,
    Ridge,
)

PLUGIN_NAME = "ml"
PLUGIN_VERSION = "1.0"
PLUGIN_TITLE = "机器学习回归"
COMPONENTS = [
    LinearRegression,
    Ridge,
    Lasso,
    RandomForestRegressor,
    GradientBoostingRegressor,
    EvaluateRegression,
]
