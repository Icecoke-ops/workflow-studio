"""fileio 插件声明：CSV / JSON / Excel 的读写。"""

from fileio.impl.io import LoadCSV, LoadExcel, LoadJSON, SaveCSV, SaveExcel

PLUGIN_NAME = "fileio"
PLUGIN_VERSION = "1.0"
PLUGIN_TITLE = "数据读写"
COMPONENTS = [
    LoadCSV,
    LoadJSON,
    LoadExcel,
    SaveCSV,
    SaveExcel,
]
