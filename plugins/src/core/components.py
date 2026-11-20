"""core 插件声明：只做注册，实现放在 impl/ 下。

类型都不用自己定义 —— 表格、数值这些是引擎内置的 std_1.0@*。
"""

from core.impl.load_csv import LoadCSV
from core.impl.predict_model import PredictModel
from core.impl.select_columns import SelectColumns

PLUGIN_NAME = "core"
PLUGIN_VERSION = "1.0"
PLUGIN_TITLE = "基础组件"
COMPONENTS = [LoadCSV, SelectColumns, PredictModel]
