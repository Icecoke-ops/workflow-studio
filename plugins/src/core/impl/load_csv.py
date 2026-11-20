"""读取 CSV 文件。"""

from engine.api import Component, expand_env


class LoadCSV(Component):
    name = "LoadCSV"
    title = "读取 CSV"
    desc = "把 CSV 文件读成表格"

    @staticmethod
    def config_schema():
        return {
            "path": {
                "type": "string",
                "title": "文件路径",
                "desc": "绝对路径（如 D:\\data\\sales.csv）；也可写相对路径，按进程工作目录解析",
                "required": True,
            },
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

    def invoke(self):
        import pandas as pd

        return {"table": pd.read_csv(self.path, encoding=self.encoding)}
