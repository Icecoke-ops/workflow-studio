"""行级操作：筛选、排序、取前 N、拼接。"""

import operator

from engine.api import Component
from table.impl.base import TableIn
from table.impl.checks import parse_json_value, require_columns

_OPS = ("eq", "ne", "gt", "ge", "lt", "le", "in", "contains", "notnull", "isnull")


class FilterRows(TableIn):
    name = "FilterRows"
    title = "筛选行"
    desc = "筛选出满足条件的行，每次只看一列"

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
        import pandas as pd

        if self.op == "notnull":
            return series.notna()
        if self.op == "isnull":
            return series.isna()
        if self.value is None:
            raise ValueError(f"op={self.op} 需要 value")
        if self.op == "in":
            if not isinstance(self.value, list):
                raise ValueError(f"op=in 的 value 必须是数组，例如 [1, 2]，实际 {self.value!r}")
            kind = _check_values(pd, series, self.value, in_list=True)
            values = self.value
            if kind == "datetime":
                dates = [value for value in values if value is not None]
                if not dates:
                    return series.isin([])
                try:
                    values = pd.to_datetime(dates)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"op=in 的日期值不合法：{dates!r}（{exc}）") from exc
                _check_datetime_tz(
                    pd, series, getattr(values, "tz", None), dates, allow_naive_value=True
                )
                values = _localize_datetime_values(pd, series, values)
            return series.isin(values)
        if self.op == "contains":
            if not isinstance(self.value, str):
                raise ValueError("op=contains 的 value 必须是字符串")
            return series.astype(str).str.contains(self.value, regex=False)
        kind = _check_values(pd, series, self.value)
        if kind == "datetime" and isinstance(self.value, str):
            _validate_datetime_value(pd, series, self.value)
        return _COMPARE[self.op](series, self.value)


class SortRows(TableIn):
    name = "SortRows"
    title = "排序"
    desc = "调整行的先后顺序，可指定一列或多列"

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
    desc = "只保留表格开头那几行，行数可调"

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

    def __init__(self, config):
        self.n = config["n"]

    def invoke(self, data):
        return {"table": data.head(self.n)}


class ConcatTables(Component):
    name = "ConcatTables"
    title = "纵向拼接"
    desc = "把第二张表格接在第一张表格后面"

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


_KIND_LABEL = {
    "number": "数值",
    "bool": "布尔",
    "datetime": "日期时间",
    "category": "分类",
    "string": "字符串",
}
_VALUE_LABEL = {"number": "数字", "bool": "布尔", "string": "字符串"}
_HINT = {
    "string": '；请写成字符串，例如 "3"',
    "number": "；数字请直接写，不要加引号",
    "bool": "；布尔请直接写 true/false，不要加引号",
    "datetime": '；请写日期字符串，例如 "2024-01-01"',
    "category": "",
}

_COMPARE = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "ge": operator.ge,
    "lt": operator.lt,
    "le": operator.le,
}

_INFERRED_KIND = {
    "integer": "number",
    "floating": "number",
    "decimal": "number",
    "int": "number",
    "float": "number",
    "string": "string",
    "unicode": "string",
    "str": "string",
    "boolean": "bool",
    "bool": "bool",
    "datetime": "datetime",
    "datetime64": "datetime",
    "date": "datetime",
    "categorical": "category",
}

_ALLOWED = {
    "string": {"scalar": {"string", "other"}, "in": {"string", "other"}},
    "number": {"scalar": {"number", "bool", "other"}, "in": {"number", "bool", "other"}},
    "bool": {"scalar": {"number", "bool", "other"}, "in": {"number", "bool", "other"}},
    "datetime": {"scalar": {"string", "other"}, "in": {"string", "other"}},
    "category": {"scalar": {"string", "other"}, "in": None},
    "mixed": {"scalar": None, "in": None},
}


def _series_kind(pd, series):
    """按实际值判断列类型；infer_dtype 内部带 dtype 快路径，object 数值列也能认。"""
    return _INFERRED_KIND.get(pd.api.types.infer_dtype(series, skipna=True), "mixed")


def _value_kind(value):
    return _INFERRED_KIND.get(type(value).__name__, "other")


def _check_values(pd, series, value, in_list=False):
    """按列的实际值类型拦住静默 0 行的错配，返回列类型供调用方复用。"""
    kind = _series_kind(pd, series)
    allowed = _ALLOWED[kind]["in" if in_list else "scalar"]
    if allowed is None:
        return kind
    items = value if in_list else [value]
    bad = [item for item in items if _value_kind(item) not in allowed]
    if not bad:
        return kind
    bad_kind = _value_kind(bad[0])
    if in_list:
        raise ValueError(
            f"这是{_KIND_LABEL[kind]}列，op=in 的数组里不能有{_VALUE_LABEL[bad_kind]}：{bad}"
            f"{_HINT.get(kind, '')}"
        )
    raise ValueError(
        f"这是{_KIND_LABEL[kind]}列，不能与{_VALUE_LABEL[bad_kind]} {bad[0]!r} 比较"
        f"{_HINT.get(kind, '')}"
    )


def _validate_datetime_value(pd, series, value):
    """日期串先解析：非法日期、时区错配都是静默 False，这里提前报出来。"""
    try:
        parsed = pd.to_datetime(value, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"日期值不合法：{value!r}（{exc}）；日期时间列请写 2024-01-01 这样的日期字符串"
        ) from exc
    _check_datetime_tz(pd, series, getattr(parsed, "tz", None), [value], allow_naive_value=True)


def _check_datetime_tz(pd, series, value_tz, values, allow_naive_value=False):
    if not pd.api.types.is_datetime64_any_dtype(series):
        return
    column_tz = series.dt.tz
    if value_tz is not None and column_tz is None:
        raise ValueError(
            f"这是无时区的日期时间列，不能与时区日期 {values!r} 比较；请去掉时区偏移"
        )
    if value_tz is None and column_tz is not None and not allow_naive_value:
        raise ValueError(
            f"这是带时区的日期时间列，请写带时区的日期（列时区 {column_tz}）"
        )


def _localize_datetime_values(pd, series, values):
    """op=in 的无时区日期按列时区解释，与 eq 拿字符串比较（能命中）对齐。"""
    if not pd.api.types.is_datetime64_any_dtype(series):
        return values
    column_tz = series.dt.tz
    if values.tz is None and column_tz is not None:
        return values.tz_localize(column_tz)
    return values



