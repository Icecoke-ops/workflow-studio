"""环境变量：``engine.env`` 的解析/快照还原，以及插件用的 ``expand_env``。

直接运行：python tests/test_env.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.api import expand_env
from engine.env import parse_pairs, restore, snapshot

from _harness import check, env_guard, expect_raises, run_cases


def case_parse_pairs_split_on_first_equals():
    pairs = parse_pairs(["A=1", "B=x=y"])
    check(pairs == {"A": "1", "B": "x=y"}, f"解析结果不对：{pairs!r}")


def case_parse_pairs_invalid():
    for bad in ("A", "1BAD=1", "=v"):
        exc = expect_raises(ValueError, lambda item=bad: parse_pairs([item]))
        check(
            repr(bad) in str(exc),
            f"错误信息应指出非法项 {bad!r}，实际：{exc}",
        )


def case_snapshot_restore_full():
    with env_guard():
        os.environ["ENGINE_ENV_KEEP"] = "before"
        os.environ["ENGINE_ENV_DROP"] = "keep"
        os.environ.pop("ENGINE_ENV_NEW", None)
        state = snapshot()
        check(
            state == dict(os.environ),
            "snapshot 应是整份 os.environ 的快照",
        )

        os.environ.update({"ENGINE_ENV_KEEP": "after", "ENGINE_ENV_NEW": "created"})
        os.environ.pop("ENGINE_ENV_DROP", None)

        restore(state)
        check(
            os.environ.get("ENGINE_ENV_KEEP") == "before",
            f"restore 应还原被改动的键，实际 {os.environ.get('ENGINE_ENV_KEEP')!r}",
        )
        check(
            os.environ.get("ENGINE_ENV_DROP") == "keep",
            f"restore 应还原被删掉的键，实际 {os.environ.get('ENGINE_ENV_DROP')!r}",
        )
        check(
            "ENGINE_ENV_NEW" not in os.environ,
            "restore 应清掉快照之后新增的键",
        )


def case_expand_env_one_var():
    with env_guard():
        os.environ["ENGINE_ENV_DIR"] = "/data"
        check(
            expand_env("${ENGINE_ENV_DIR}/x") == "/data/x",
            f"展开结果不对：{expand_env('${ENGINE_ENV_DIR}/x')!r}",
        )


def case_expand_env_many_vars():
    with env_guard():
        os.environ["ENGINE_ENV_LEFT"] = "a"
        os.environ["ENGINE_ENV_RIGHT"] = "b"
        check(
            expand_env("${ENGINE_ENV_LEFT}-${ENGINE_ENV_RIGHT}/${ENGINE_ENV_LEFT}") == "a-b/a",
            "同一个串里的多个变量应全部展开",
        )


def case_expand_env_undefined():
    with env_guard():
        os.environ.pop("ENGINE_ENV_NOPE", None)
        expect_raises(
            ValueError,
            lambda: expand_env("${ENGINE_ENV_NOPE}/x"),
            "环境变量未定义",
            "ENGINE_ENV_NOPE",
        )


def case_expand_env_non_string():
    check(expand_env(None) is None, "None 应原样返回")
    check(expand_env(123) == 123, "非字符串应原样返回")


CASES = [
    ("parse_pairs 按第一个 = 切分", case_parse_pairs_split_on_first_equals),
    ("parse_pairs 非法项报错并指出是哪一项", case_parse_pairs_invalid),
    ("snapshot/restore 全量还原（含新增与删除）", case_snapshot_restore_full),
    ("expand_env 展开单个变量", case_expand_env_one_var),
    ("expand_env 展开多个变量", case_expand_env_many_vars),
    ("expand_env 未定义变量报错含名字", case_expand_env_undefined),
    ("expand_env 非字符串原样返回", case_expand_env_non_string),
]


def main():
    return run_cases("env", CASES)


if __name__ == "__main__":
    sys.exit(main())
