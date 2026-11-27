"""table 插件声明：选列、行操作、缺失值、探查。"""

from table.impl.columns import CastColumn, DropColumns, RenameColumns, SelectColumns
from table.impl.inspect import ValueCounts
from table.impl.missing import DropMissing, FillMissing
from table.impl.rows import ConcatTables, FilterRows, HeadRows, SortRows

PLUGIN_NAME = "table"
PLUGIN_VERSION = "1.0"
PLUGIN_TITLE = "数据处理"
COMPONENTS = [
    SelectColumns,
    DropColumns,
    RenameColumns,
    CastColumn,
    FilterRows,
    SortRows,
    HeadRows,
    ConcatTables,
    FillMissing,
    DropMissing,
    ValueCounts,
]
