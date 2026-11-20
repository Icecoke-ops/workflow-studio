"""split 插件声明：训练/测试切分与 X / Y 拆分。"""

from split.impl.split import SplitTable, SplitXY

PLUGIN_NAME = "split"
PLUGIN_VERSION = "1.0"
PLUGIN_TITLE = "数据划分"
COMPONENTS = [SplitTable, SplitXY]
