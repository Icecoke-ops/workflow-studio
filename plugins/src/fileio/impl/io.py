"""表格读写：CSV / JSON / Excel。"""

from engine.api import Component, expand_env
from fileio.impl.base import TableIn


def _path(desc):
    return {"type": "string", "title": "文件路径", "desc": desc, "required": True}


def _fail_write(path, exc):
    raise ValueError(f"写入失败：{path}：{exc}") from exc


class LoadCSV(Component):
    name = "LoadCSV"
    title = "读取 CSV"
    desc = "读取 CSV 文件并转成表格，可切换编码"

    @staticmethod
    def config_schema():
        return {
            "path": _path("绝对路径优先；也可写相对路径，按进程工作目录解析，支持 ${变量}"),
            "encoding": {
                "type": "enum",
                "title": "编码",
                "desc": "Windows 上中文 CSV 常是 GBK，读出来乱码就换这个",
                "default": "utf-8",
                "choices": [
                    {"value": "utf-8", "label": "UTF-8"},
                    {"value": "gbk", "label": "GBK"},
                ],
            },
            "sep": {
                "type": "string",
                "title": "分隔符",
                "desc": "默认逗号",
                "default": ",",
            },
            "header": {
                "type": "boolean",
                "title": "首行为表头",
                "desc": "关闭时列名是 0、1、2…",
                "default": True,
            },
        }

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "数据表"}}

    def __init__(self, config):
        self.path = expand_env(config["path"])
        self.encoding = config["encoding"]
        self.sep = config["sep"]
        self.header = config["header"]

    def invoke(self):
        import pandas as pd

        return {
            "table": pd.read_csv(
                self.path,
                encoding=self.encoding,
                sep=self.sep,
                header=0 if self.header else None,
            )
        }


class LoadJSON(Component):
    name = "LoadJSON"
    title = "读取 JSON"
    desc = "读取 JSON 文件并把每条记录转成表格行"

    @staticmethod
    def config_schema():
        return {
            "path": _path("绝对路径优先；也可写相对路径，支持 ${变量}"),
        }

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "数据表"}}

    def __init__(self, config):
        self.path = expand_env(config["path"])

    def invoke(self):
        import pandas as pd

        return {"table": pd.read_json(self.path, orient="records")}


class LoadExcel(Component):
    name = "LoadExcel"
    title = "读取 Excel"
    desc = "读取 Excel 工作簿里的一张工作表并转成表格"

    @staticmethod
    def config_schema():
        return {
            "path": _path("绝对路径优先；也可写相对路径，支持 ${变量}"),
            "sheet": {
                "type": "string",
                "title": "工作表",
                "desc": "留空读第一个工作表",
                "default": "",
            },
            "header": {
                "type": "boolean",
                "title": "首行为表头",
                "desc": "关闭时列名是 0、1、2…",
                "default": True,
            },
        }

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "数据表"}}

    def __init__(self, config):
        self.path = expand_env(config["path"])
        self.sheet = config["sheet"]
        self.header = config["header"]

    def invoke(self):
        import pandas as pd

        return {
            "table": pd.read_excel(
                self.path,
                sheet_name=self.sheet or 0,
                header=0 if self.header else None,
            )
        }


class SaveCSV(TableIn):
    name = "SaveCSV"
    title = "保存 CSV"
    desc = "把表格写成 CSV 文件，可切换编码"

    @staticmethod
    def config_schema():
        return {
            "path": _path("绝对路径优先；也可写相对路径，支持 ${变量}"),
            "encoding": {
                "type": "enum",
                "title": "编码",
                "desc": "Excel 打开中文不乱码通常选 GBK",
                "default": "utf-8",
                "choices": [
                    {"value": "utf-8", "label": "UTF-8"},
                    {"value": "gbk", "label": "GBK"},
                ],
            },
            "index": {
                "type": "boolean",
                "title": "写入行号",
                "desc": "是否把行索引也写成一列",
                "default": False,
            },
        }

    @staticmethod
    def output_schema():
        return {}

    def __init__(self, config):
        self.path = expand_env(config["path"])
        self.encoding = config["encoding"]
        self.index = config["index"]

    def invoke(self, data):
        try:
            data.to_csv(self.path, encoding=self.encoding, index=self.index)
        except (OSError, UnicodeError) as exc:
            _fail_write(self.path, exc)
        return {}


class SaveExcel(TableIn):
    name = "SaveExcel"
    title = "保存 Excel"
    desc = "把表格写成 Excel 工作表，可指定表名"

    @staticmethod
    def config_schema():
        return {
            "path": _path("绝对路径优先；也可写相对路径，支持 ${变量}；需 .xlsx 后缀"),
            "sheet": {
                "type": "string",
                "title": "工作表名",
                "desc": "写入的工作表名称",
                "default": "Sheet1",
            },
            "index": {
                "type": "boolean",
                "title": "写入行号",
                "desc": "是否把行索引也写成一列",
                "default": False,
            },
        }

    @staticmethod
    def output_schema():
        return {}

    def __init__(self, config):
        self.path = expand_env(config["path"])
        self.sheet = config["sheet"]
        self.index = config["index"]

    def invoke(self, data):
        try:
            data.to_excel(self.path, sheet_name=self.sheet, index=self.index)
        except (OSError, UnicodeError) as exc:
            _fail_write(self.path, exc)
        return {}
