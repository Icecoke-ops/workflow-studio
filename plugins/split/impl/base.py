"""表格组件的公共输入端口。"""

from engine.api import Component


class TableIn(Component):
    """只接收一张数据表的组件：继承它就少写一份 input_schema。"""

    @staticmethod
    def input_schema():
        return {"data": {"types": ["std_1.0@table"], "required": True, "title": "数据表"}}
