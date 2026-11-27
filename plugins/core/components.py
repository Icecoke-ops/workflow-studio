"""core 插件声明：只做模型应用，表格操作见 table 插件。"""

from core.impl.predict_model import PredictModel

PLUGIN_NAME = "core"
PLUGIN_VERSION = "1.0"
PLUGIN_TITLE = "模型应用"
COMPONENTS = [PredictModel]
