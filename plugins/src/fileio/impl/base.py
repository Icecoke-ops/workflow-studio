"""表格读写组件的公共端口：读取组件声明空输入和数据表输出，写入组件只接收一张数据表。"""

from engine.api import Component


class TableIn(Component):
    """只接收一张数据表、没有输出的写入组件：继承它就少写两份 schema。"""

    @staticmethod
    def input_schema():
        return {"data": {"types": ["std_1.0@table"], "required": True, "title": "数据表"}}

    @staticmethod
    def output_schema():
        return {}


class ReadTable(Component):
    """只读文件的组件：没有输入，输出一张数据表。"""

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"table": {"type": "std_1.0@table", "title": "数据表"}}
