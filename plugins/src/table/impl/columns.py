"""列的挑选、删除、改名与类型转换。"""

from table.impl.base import TableIn
from table.impl.checks import require_columns


class SelectColumns(TableIn):
    name = "SelectColumns"
    title = "选择列"
    desc = "挑出需要的列，可自行决定先后顺序"

    @staticmethod
    def config_schema():
        return {
            "columns": {
                "type": "array",
                "title": "列名",
                "desc": "要保留的列名数组，例如 [\"x\", \"y\"]",
                "required": True,
                "min": 1,
            },
            "strict": {
                "type": "boolean",
                "title": "列不存在时报错",
                "desc": "勾选后缺列直接失败；取消则静默跳过缺失的列",
                "default": True,
            },
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "结果表"}}

    def __init__(self, config):
        self.columns = config["columns"]
        self.strict = config["strict"]
        duplicates = sorted({c for c in self.columns if self.columns.count(c) > 1})
        if duplicates:
            raise ValueError(f"columns 里有重复列名：{duplicates}")

    def invoke(self, data):
        if self.strict:
            require_columns(data, self.columns)
        keep = [column for column in self.columns if column in data.columns]
        if not keep:
            raise ValueError(f"选不出任何列（可用：{list(data.columns)}）")
        return {"table": data[keep]}


class DropColumns(TableIn):
    name = "DropColumns"
    title = "删除列"
    desc = "删掉指定的列，一次可以删掉多列"

    @staticmethod
    def config_schema():
        return {
            "columns": {
                "type": "array",
                "title": "列名",
                "desc": "要删除的列名数组",
                "required": True,
                "min": 1,
            }
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "结果表"}}

    def __init__(self, config):
        self.columns = config["columns"]

    def invoke(self, data):
        require_columns(data, self.columns)
        return {"table": data.drop(columns=self.columns)}


class RenameColumns(TableIn):
    name = "RenameColumns"
    title = "重命名列"
    desc = "把旧列名换成新名字，一次可改多列"

    @staticmethod
    def config_schema():
        return {
            "mapping": {
                "type": "json",
                "title": "改名映射",
                "desc": "对象，例如 {\"old\": \"new\"}",
                "required": True,
            }
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "结果表"}}

    def __init__(self, config):
        self.mapping = config["mapping"]

    def invoke(self, data):
        if not isinstance(self.mapping, dict):
            raise ValueError("mapping 必须是对象（旧列名→新列名）")
        require_columns(data, list(self.mapping))
        result = data.rename(columns=self.mapping)
        duplicated = result.columns[result.columns.duplicated()].tolist()
        if duplicated:
            raise ValueError(
                f"重命名后列名重复：{duplicated}（mapping：{self.mapping}）；"
                f"请避免改成表里已有的列名"
            )
        return {"table": result}


class CastColumn(TableIn):
    name = "CastColumn"
    title = "转换列类型"
    desc = "转换一列的数据类型，可转成数值、文本、布尔或日期"

    @staticmethod
    def config_schema():
        return {
            "column": {
                "type": "string",
                "title": "列名",
                "desc": "要转换的列",
                "required": True,
            },
            "to": {
                "type": "enum",
                "title": "目标类型",
                "desc": "转换后的类型",
                "required": True,
                "choices": [
                    {"value": "int", "label": "整数"},
                    {"value": "float", "label": "浮点数"},
                    {"value": "str", "label": "字符串"},
                    {"value": "bool", "label": "布尔"},
                    {"value": "datetime", "label": "日期时间"},
                ],
            },
            "errors": {
                "type": "enum",
                "title": "转换失败时",
                "desc": "raise 直接报错；coerce 转不动的值变成缺失",
                "default": "raise",
                "choices": [
                    {"value": "raise", "label": "报错"},
                    {"value": "coerce", "label": "变成缺失值"},
                ],
            },
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "结果表"}}

    def __init__(self, config):
        self.column = config["column"]
        self.to = config["to"]
        self.errors = config["errors"]

    def invoke(self, data):
        import pandas as pd

        require_columns(data, [self.column])
        series = data[self.column]
        try:
            converted = self._convert(pd, series)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"列 {self.column} 转 {self.to} 失败：{exc}") from exc
        result = data.copy()
        result[self.column] = converted
        return {"table": result}

    def _convert(self, pd, series):
        if self.to == "int":
            return pd.to_numeric(series, errors=self.errors).astype("Int64")
        if self.to == "float":
            return pd.to_numeric(series, errors=self.errors).astype(float)
        if self.to == "str":
            return series.astype(str)
        if self.to == "bool":
            return _to_bool(pd, series, self.errors, self.column)
        return pd.to_datetime(series, errors=self.errors)


_TRUE = {"1", "true", "yes", "y", "是"}
_FALSE = {"0", "false", "no", "n", "否"}


def _to_bool(pd, series, errors, column):
    """数值列按 1/0、文本列按常见字面量；astype(bool) 会把 "0" 也当成 True，不能用。"""
    if pd.api.types.is_bool_dtype(series):
        return series.astype("boolean")
    if pd.api.types.is_numeric_dtype(series):
        converted = series.map({1: True, 0: False}).astype("boolean")
    else:
        lowered = series.astype("string").str.strip().str.lower()
        converted = lowered.map(
            lambda value: True
            if isinstance(value, str) and value in _TRUE
            else False
            if isinstance(value, str) and value in _FALSE
            else pd.NA
        ).astype("boolean")
    if errors == "raise":
        bad = series[converted.isna() & series.notna()]
        if not bad.empty:
            raise ValueError(
                f"列 {column} 有 {len(bad)} 个值无法转成布尔"
                f"（布尔只接受 1/0、true/false、yes/no、是/否）：{list(bad.head(5))}"
            )
    return converted

