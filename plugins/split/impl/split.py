"""数据划分：训练/测试切分、拆特征 X 与目标 Y。"""

from split.impl.base import TableIn


class SplitTable(TableIn):
    name = "SplitTable"
    title = "切分训练/测试"
    desc = "切分表格为训练集和测试集，比例可调"

    @staticmethod
    def config_schema():
        return {
            "test_size": {
                "type": "number",
                "title": "测试集比例",
                "desc": "0 到 1 之间，例如 0.2 表示 20% 给测试集",
                "default": 0.2,
                "min": 0,
                "max": 1,
                "step": 0.05,
            },
            "seed": {
                "type": "integer",
                "title": "随机种子",
                "desc": "固定后每次切分结果一致",
                "min": 0,
            },
            "shuffle": {
                "type": "boolean",
                "title": "打乱顺序",
                "desc": "取消则按原顺序前段 train、后段 test",
                "default": True,
            },
        }

    @staticmethod
    def output_schema():
        return {
            "train": {"type": "std_1.0@table", "title": "训练集"},
            "test": {"type": "std_1.0@table", "title": "测试集"},
        }

    def __init__(self, config):
        self.test_size = config["test_size"]
        self.seed = config.get("seed")
        self.shuffle = config["shuffle"]
        if not 0 < self.test_size < 1:
            raise ValueError(f"test_size 必须在 (0, 1) 之间，实际 {self.test_size}")

    def invoke(self, data):
        import numpy as np

        total = len(data)
        if total < 2:
            raise ValueError(f"数据只有 {total} 行，无法切分")
        positions = np.arange(total)
        if self.shuffle:
            np.random.default_rng(self.seed).shuffle(positions)
        n_test = max(1, int(round(total * self.test_size)))
        if n_test >= total:
            raise ValueError(f"数据 {total} 行，切不出 {n_test} 行测试集")
        train = data.iloc[positions[:-n_test]].reset_index(drop=True)
        test = data.iloc[positions[-n_test:]].reset_index(drop=True)
        return {"train": train, "test": test}


class SplitXY(TableIn):
    name = "SplitXY"
    title = "拆分 X / Y"
    desc = "拆出特征表和目标表，两表行序一一对应"

    @staticmethod
    def config_schema():
        return {
            "feature": {
                "type": "array",
                "title": "特征列",
                "desc": "作为 X 的列名数组，按此顺序输出",
                "required": True,
                "min": 1,
            },
            "target": {
                "type": "string",
                "title": "目标列",
                "desc": "作为 Y 的列名",
                "required": True,
            },
        }

    @staticmethod
    def output_schema():
        return {
            "x": {"type": "std_1.0@table", "title": "特征表 X"},
            "y": {"type": "std_1.0@table", "title": "目标表 Y"},
        }

    def __init__(self, config):
        self.feature = list(config["feature"])
        self.target = config["target"]
        duplicates = sorted(
            {column for column in self.feature if self.feature.count(column) > 1}
        )
        if duplicates:
            raise ValueError(f"feature 里有重复列名：{duplicates}")

    def invoke(self, data):
        missing = [
            column
            for column in self.feature + [self.target]
            if column not in data.columns
        ]
        if missing:
            raise ValueError(f"列不存在：{missing}（可用：{list(data.columns)}）")
        if self.target in self.feature:
            raise ValueError(f"目标列 {self.target} 不能同时出现在特征列里")
        return {"x": data[self.feature], "y": data[[self.target]]}
