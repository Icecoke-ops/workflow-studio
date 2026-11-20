"""类型标识：``插件名_版本@类型名``，例如 ``school_bean_0.1@stu``。

规则：
- 插件名：``[A-Za-z][A-Za-z0-9_]*``
- 版本号：``\\d+\\.\\d+``
- 类型名：``[A-Za-z][A-Za-z0-9_]*``

插件源码里允许写短名（``"table"``），加载时补全成本插件的类型标识；
写了 ``@`` 的一律视为全名，原样使用（用来引用 ``core`` 或其他插件的类型）。
"""

import re

from .errors import TypeIdError

_TYPE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)_(\d+\.\d+)@([A-Za-z][A-Za-z0-9_]*)$")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+$")


def is_name(value):
    return isinstance(value, str) and bool(_NAME_RE.match(value))


def is_version(value):
    return isinstance(value, str) and bool(_VERSION_RE.match(value))


def qualify(plugin, version, type_name):
    """拼出完整类型标识，并顺带校验三段格式。"""
    if not is_name(plugin):
        raise TypeIdError(f"插件名不合法：{plugin!r}（只允许字母开头，含字母数字下划线）")
    if not is_version(version):
        raise TypeIdError(f"版本号不合法：{version!r}（应为 主.次，例如 1.0）")
    if not is_name(type_name):
        raise TypeIdError(f"类型名不合法：{type_name!r}（只允许字母开头，含字母数字下划线）")
    return f"{plugin}_{version}@{type_name}"


def parse(type_id):
    """拆开完整类型标识，返回 (插件名, 版本, 类型名)。"""
    if not isinstance(type_id, str):
        raise TypeIdError(
            f"类型标识不合法：{type_id!r}，应为 插件名_版本@类型名"
            f"（实际类型 {type(type_id).__name__}）"
        )
    match = _TYPE_RE.match(type_id)
    if not match:
        raise TypeIdError(
            f"类型标识不合法：{type_id!r}，应为 插件名_版本@类型名，例如 std_1.0@table"
        )
    return match.group(1), match.group(2), match.group(3)


def resolve(value, plugin, version):
    """把插件源码里写的类型串解析成完整标识。"""
    if not isinstance(value, str) or not value:
        raise TypeIdError(f"类型标识必须是非空字符串，实际 {value!r}")
    if "@" in value:
        parse(value)
        return value
    return qualify(plugin, version, value)
