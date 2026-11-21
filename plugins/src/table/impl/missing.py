"""缺失值填充与删除。"""

from table.impl.base import TableIn
from table.impl.checks import parse_json_value, require_columns


class FillMissing(TableIn):
    name = "FillMissing"
    title = "填充缺失值"
    desc = (
        "按均值 / 中位数 / 众数 / 常量填充空值；接上参考表时统计量取自它（例如训练集），"
        "不接时统计量在当前表上计算——建模请把训练集接到 reference，否则测试集会参与统计"
    )

    @staticmethod
    def config_schema():
        return {
            "columns": {
                "type": "array",
                "title": "列名",
                "desc": "要处理的列名数组；留空表示全部列",
                "default": [],
            },
            "strategy": {
                "type": "enum",
                "title": "填充方式",
                "desc": "mean/median 只适用于数值列",
                "required": True,
                "choices": [
                    {"value": "mean", "label": "均值"},
                    {"value": "median", "label": "中位数"},
                    {"value": "mode", "label": "众数"},
                    {"value": "constant", "label": "常量"},
                ],
            },
            "value": {
                "type": "string",
                "title": "常量值",
                "desc": '仅 strategy=constant：数字写 0，字符串写 "空" 或直接 空',
            },
        }

    @staticmethod
    def input_schema():
        return {
            "data": {"types": ["std_1.0@table"], "required": True, "title": "数据表"},
            "reference": {
                "types": ["std_1.0@table"],
                "required": False,
                "title": "参考表",
                "desc": "统计量取自这张表（例如训练集）；不接则用 data 自己算",
            },
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "结果表"}}

    def __init__(self, config):
        self.columns = config["columns"]
        self.strategy = config["strategy"]
        text = config.get("value")
        self.value = None if text is None else parse_json_value(text)

    def invoke(self, data, reference=None):
        import pandas as pd

        targets = self.columns or list(data.columns)
        require_columns(data, targets)
        if self.strategy == "constant" and (
            self.value is None or isinstance(self.value, (dict, list))
        ):
            raise ValueError("strategy=constant 需要用 value 给出标量")
        source = data if reference is None else reference
        if self.strategy != "constant" and reference is not None:
            missing = [column for column in targets if column not in source.columns]
            if missing:
                raise ValueError(
                    f"参考表缺少列：{missing}（参考表可用：{list(source.columns)}）"
                )
        result = data.copy()
        for column in targets:
            filled = result[column]
            if self.strategy == "constant":
                result[column] = filled.fillna(self.value)
                continue
            stats = source[column]
            if self.strategy in ("mean", "median"):
                if not pd.api.types.is_numeric_dtype(filled):
                    raise ValueError(
                        f"数据列 {column} 不是数值列，不能用 {self.strategy} 填充"
                    )
                if reference is not None and not pd.api.types.is_numeric_dtype(stats):
                    raise ValueError(
                        f"参考表列 {column} 不是数值列，不能用 {self.strategy} 填充"
                    )
            if self.strategy == "mean":
                fill = stats.mean()
            elif self.strategy == "median":
                fill = stats.median()
            else:
                modes = stats.mode(dropna=True)
                if modes.empty:
                    continue
                fill = modes.iloc[0]
            result[column] = filled.fillna(fill)
        return {"table": result}


class DropMissing(TableIn):
    name = "DropMissing"
    title = "删除缺失行"
    desc = "删掉含缺失值的行"

    @staticmethod
    def config_schema():
        return {
            "columns": {
                "type": "array",
                "title": "列名",
                "desc": "只在哪些列上判断缺失；留空表示全部列",
                "default": [],
            },
            "how": {
                "type": "enum",
                "title": "判断方式",
                "desc": "any 任一列缺失就删，all 全部列缺失才删",
                "default": "any",
                "choices": [
                    {"value": "any", "label": "任一缺失"},
                    {"value": "all", "label": "全部缺失"},
                ],
            },
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "结果表"}}

    def __init__(self, config):
        self.columns = config["columns"]
        self.how = config["how"]

    def invoke(self, data):
        subset = self.columns or None
        if subset:
            require_columns(data, subset)
        return {"table": data.dropna(subset=subset, how=self.how)}
