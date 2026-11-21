"""环境变量的解析、覆盖与还原。"""

import os
import re
import secrets
import time

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


def apply(workflow_env=None, cli_env=None):
    """按 二级 → 三级 覆盖 os.environ；一级由调用方先写入。"""
    for layer in (workflow_env, cli_env):
        if layer:
            os.environ.update(layer)


def new_run_id():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def snapshot():
    return dict(os.environ)


def restore(state):
    os.environ.clear()
    os.environ.update(state)
