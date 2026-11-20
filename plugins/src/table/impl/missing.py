"""缺失值填充与删除。"""

from table.impl.base import TableIn
from table.impl.checks import parse_json_value, require_columns


class FillMissing(TableIn):
    name = "FillMissing"
    title = "填充缺失值"
    desc = "按均值 / 中位数 / 众数 / 常量填充空值"

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
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "结果表"}}

    def __init__(self, config):
        self.columns = config["columns"]
        self.strategy = config["strategy"]
        text = config.get("value")
        self.value = None if text is None else parse_json_value(text)

    def invoke(self, data):
        import pandas as pd

        targets = self.columns or list(data.columns)
        require_columns(data, targets)
        if self.strategy == "constant" and (
            self.value is None or isinstance(self.value, (dict, list))
        ):
            raise ValueError("strategy=constant 需要用 value 给出标量")
        result = data.copy()
        for column in targets:
            series = result[column]
            if self.strategy == "constant":
                result[column] = series.fillna(self.value)
                continue
            if self.strategy in ("mean", "median"):
                if not pd.api.types.is_numeric_dtype(series):
                    raise ValueError(
                        f"列 {column} 不是数值列，不能用 {self.strategy} 填充"
                    )
            # ponytail: 统计量在整表上算，训练/测试严格隔离需要预处理器类型，等真有需求再升级
            if self.strategy == "mean":
                fill = series.mean()
            elif self.strategy == "median":
                fill = series.median()
            else:
                modes = series.mode(dropna=True)
                if modes.empty:
                    continue
                fill = modes.iloc[0]
            result[column] = series.fillna(fill)
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
