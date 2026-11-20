"""环境变量的解析、覆盖与还原。"""

import os
import re

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_pairs(pairs):
    """把 ["A=1", "B=x=y"] 解析成 {"A": "1", "B": "x=y"}。"""
    result = {}
    for item in pairs:
        if not isinstance(item, str) or "=" not in item:
            raise ValueError(f"环境变量格式不合法：{item!r}（应为 NAME=VALUE）")
        name, value = item.split("=", 1)
        if not NAME_RE.match(name):
            raise ValueError(f"环境变量名不合法：{item!r}（应为 NAME=VALUE）")
        result[name] = value
    return result


def snapshot():
    return dict(os.environ)


def restore(state):
    os.environ.clear()
    os.environ.update(state)
