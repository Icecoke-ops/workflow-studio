"""按列名挑选列。"""

from engine.api import Component


class SelectColumns(Component):
    name = "SelectColumns"
    title = "选择列"
    desc = "按逗号分隔的列名保留指定列"

    @staticmethod
    def config_schema():
        return {
            "columns": {
                "type": "string",
                "title": "列名",
                "desc": "逗号分隔，例如 x,y",
                "required": True,
            },
            "strict": {
                "type": "boolean",
                "title": "列不存在时报错",
                "desc": "勾选后缺列直接失败；取消则静默跳过缺失的列",
                "default": True,
            },
        }

    @staticmethod
    def input_schema():
        return {"data": {"types": ["std_1.0@table"], "required": True, "title": "数据表"}}

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "结果表"}}

    def __init__(self, config):
        self.columns = [c.strip() for c in config["columns"].split(",") if c.strip()]
        self.strict = config["strict"]

    def invoke(self, data):
        if not self.columns:
            raise ValueError("columns 不能为空")
        missing = [c for c in self.columns if c not in data.columns]
        if missing and self.strict:
            raise ValueError(f"列不存在：{missing}（可用：{list(data.columns)}）")
        keep = [c for c in self.columns if c in data.columns]
        return {"table": data[keep]}
