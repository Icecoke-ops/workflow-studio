"""linreg 插件声明。

现在只有「训练」是线性回归特有的；预测交给了 core 的通用 PredictModel 组件，
任何继承 PredictorModel 的模型都能被它吃掉。
"""

from linreg.impl.evaluate import Evaluate
from linreg.impl.fit import FitLinearRegression
from linreg.impl.make_data import MakeLinearData

PLUGIN_NAME = "linreg"
PLUGIN_VERSION = "0.1"
PLUGIN_TITLE = "线性回归"
COMPONENTS = [MakeLinearData, FitLinearRegression, Evaluate]
