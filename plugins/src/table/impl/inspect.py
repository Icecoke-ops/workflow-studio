"""表格探查。"""

from table.impl.base import TableIn
from table.impl.checks import require_columns


class ValueCounts(TableIn):
    name = "ValueCounts"
    title = "值计数"
    desc = "统计一列里每个取值出现的次数或占比"

    @staticmethod
    def config_schema():
        return {
            "column": {
                "type": "string",
                "title": "列名",
                "desc": "要统计的列",
                "required": True,
            },
            "normalize": {
                "type": "boolean",
                "title": "显示占比",
                "desc": "勾选后输出比例而不是次数",
                "default": False,
            },
        }

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "计数表"}}

    def __init__(self, config):
        self.column = config["column"]
        self.normalize = config["normalize"]
        output = "proportion" if self.normalize else "count"
        if self.column == output:
            raise ValueError(
                f"列名与输出列名冲突：要统计的列名是 {self.column!r}，"
                f"输出列也叫 {output!r}；请先给该列改名"
            )

    def invoke(self, data):
        require_columns(data, [self.column])
        counts = data[self.column].value_counts(normalize=self.normalize)
        table = counts.reset_index()
        table.columns = [self.column, "proportion" if self.normalize else "count"]
        return {"table": table}
