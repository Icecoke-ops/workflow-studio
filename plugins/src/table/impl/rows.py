"""行级操作：筛选、排序、取前 N、拼接。"""

from engine.api import Component
from table.impl.base import TableIn
from table.impl.checks import parse_json_value, require_columns

_OPS = ("eq", "ne", "gt", "ge", "lt", "le", "in", "contains", "notnull", "isnull")


class FilterRows(TableIn):
    name = "FilterRows"
    title = "筛选行"
    desc = "按一列的比较结果保留行，只做列 + 比较符 + 值"

    @staticmethod
    def config_schema():
        return {
            "column": {
                "type": "string",
                "title": "列名",
                "desc": "参与比较的列",
                "required": True,
            },
            "op": {
                "type": "enum",
                "title": "比较符",
                "desc": "in 需要数组；contains 需要字符串；notnull/isnull 不需要值",
                "required": True,
                "choices": [{"value": value, "label": value} for value in _OPS],
            },
            "value": {
                "type": "string",
                "title": "比较值",
                "desc": '按 JSON 写：数字写 3，字符串写 "abc" 或直接 abc，in 写 [1, 2]；notnull/isnull 不用填',
            },
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "筛选结果"}}

    def __init__(self, config):
        self.column = config["column"]
        self.op = config["op"]
        text = config.get("value")
        self.value = None if text is None else parse_json_value(text)

    def invoke(self, data):
        require_columns(data, [self.column])
        series = data[self.column]
        try:
            mask = self._mask(series)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"列 {self.column} 不支持 {self.op} 比较（value={self.value!r}）：{exc}"
            ) from exc
        return {"table": data[mask]}

    def _mask(self, series):
        if self.op == "notnull":
            return series.notna()
        if self.op == "isnull":
            return series.isna()
        if self.value is None:
            raise ValueError(f"op={self.op} 需要 value")
        if self.op == "in":
            if not isinstance(self.value, list):
                raise ValueError(f"op=in 的 value 必须是数组，例如 [1, 2]，实际 {self.value!r}")
            return series.isin(self.value)
        if self.op == "contains":
            if not isinstance(self.value, str):
                raise ValueError("op=contains 的 value 必须是字符串")
            return series.astype(str).str.contains(self.value, regex=False)
        return {
            "eq": series == self.value,
            "ne": series != self.value,
            "gt": series > self.value,
            "ge": series >= self.value,
            "lt": series < self.value,
            "le": series <= self.value,
        }[self.op]


class SortRows(TableIn):
    name = "SortRows"
    title = "排序"
    desc = "按一列或多列排序"

    @staticmethod
    def config_schema():
        return {
            "by": {
                "type": "array",
                "title": "排序列",
                "desc": "列名数组，先按第一列排",
                "required": True,
                "min": 1,
            },
            "ascending": {
                "type": "boolean",
                "title": "升序",
                "desc": "取消则降序",
                "default": True,
            },
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "排序结果"}}

    def __init__(self, config):
        self.by = config["by"]
        self.ascending = config["ascending"]

    def invoke(self, data):
        require_columns(data, self.by)
        return {"table": data.sort_values(by=self.by, ascending=self.ascending)}


class HeadRows(TableIn):
    name = "HeadRows"
    title = "取前 N 行"
    desc = "保留表格的前 n 行"

    @staticmethod
    def config_schema():
        return {
            "n": {
                "type": "integer",
                "title": "行数",
                "desc": "保留多少行",
                "default": 5,
                "min": 1,
            }
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "结果表"}}

    def __init__(self, config):
        self.n = config["n"]

    def invoke(self, data):
        return {"table": data.head(self.n)}


class ConcatTables(Component):
    name = "ConcatTables"
    title = "纵向拼接"
    desc = "把两张表上下拼成一张"

    @staticmethod
    def config_schema():
        return {
            "ignore_index": {
                "type": "boolean",
                "title": "重排行号",
                "desc": "勾选后连续编号；取消则保留原行号",
                "default": True,
            }
        }

    @staticmethod
    def input_schema():
        return {
            "first": {"types": ["std_1.0@table"], "required": True, "title": "第一张表"},
            "second": {"types": ["std_1.0@table"], "required": True, "title": "第二张表"},
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "拼接结果"}}

    def __init__(self, config):
        self.ignore_index = config["ignore_index"]

    def invoke(self, first, second):
        import pandas as pd

        return {"table": pd.concat([first, second], ignore_index=self.ignore_index)}

