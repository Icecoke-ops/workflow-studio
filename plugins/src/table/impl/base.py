"""表格组件的公共端口：输入一张数据表，输出一张结果表。"""

from engine.api import Component


class TableIn(Component):
    """只接收一张数据表、输出一张结果表的组件：继承它就少写两份 schema。"""

    @staticmethod
    def input_schema():
        return {"data": {"types": ["std_1.0@table"], "required": True, "title": "数据表"}}

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "结果表"}}
