"""engine.typeid 类型标识格式测试。

直接运行：python tests/test_typeid.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.errors import TypeIdError
from engine.typeid import is_name, is_version, parse, qualify, resolve

from _harness import check, expect_raises, run_cases


def case_parse_full():
    check(parse("core_1.0@table") == ("core", "1.0", "table"), "core_1.0@table 解析结果不对")
    check(parse("linreg_0.1@model") == ("linreg", "0.1", "model"), "linreg_0.1@model 解析结果不对")
    check(
        parse("school_bean_0.1@stu") == ("school_bean", "0.1", "stu"),
        "插件名含下划线时解析结果不对",
    )


def case_parse_invalid():
    bad = [
        "core_1.0",        # 缺 @
        "core_1@table",    # 版本写成 1
        "core_1.0.0@table",
        "1core_1.0@table",  # 插件名数字开头
        "core_1.0@ta-ble",  # 类型名非法字符
        "core_1.0@ta ble",
        "core_1.0@1table",
        "core_1.0@",
        "@table",
        "_core_1.0@table",
        "",
        None,
    ]
    for value in bad:
        expect_raises(TypeIdError, lambda v=value: parse(v), "类型标识不合法")


def case_parse_non_string():
    """parse 收到非 str 必须抛 TypeIdError，而不是 TypeError。"""
    for value in (None, 123, 1.5, [], {}):
        exc = expect_raises(TypeIdError, lambda v=value: parse(v), "类型标识不合法")
        check("实际类型" in str(exc), f"非字符串输入应说明实际类型，实际：{exc}")


def case_resolve_short_name():
    check(
        resolve("table", "linreg", "0.1") == "linreg_0.1@table",
        f"短名应补全为 linreg_0.1@table，实际 {resolve('table', 'linreg', '0.1')!r}",
    )
    check(
        resolve("model", "linreg", "0.1") == "linreg_0.1@model",
        "短名 model 补全结果不对",
    )


def case_resolve_full_name_unchanged():
    check(
        resolve("core_1.0@table", "linreg", "0.1") == "core_1.0@table",
        "带 @ 的全名应原样返回",
    )
    # 没有 @ 就按短类型名处理，"core_1.0" 不是合法类型名
    expect_raises(
        TypeIdError, lambda: resolve("core_1.0", "linreg", "0.1"), "类型名不合法"
    )


def case_resolve_invalid():
    expect_raises(TypeIdError, lambda: resolve("", "linreg", "0.1"), "非空字符串")
    expect_raises(TypeIdError, lambda: resolve(None, "linreg", "0.1"), "非空字符串")
    expect_raises(TypeIdError, lambda: resolve("table", "1bad", "0.1"), "插件名不合法")
    expect_raises(TypeIdError, lambda: resolve("table", "linreg", "1"), "版本号不合法")
    expect_raises(TypeIdError, lambda: resolve("ta-ble", "linreg", "0.1"), "类型名不合法")


def case_qualify():
    check(qualify("core", "1.0", "table") == "core_1.0@table", "qualify 拼接结果不对")
    expect_raises(TypeIdError, lambda: qualify("1core", "1.0", "table"), "插件名不合法")
    expect_raises(TypeIdError, lambda: qualify("core", "1", "table"), "版本号不合法")
    expect_raises(TypeIdError, lambda: qualify("core", "1.0", "ta-ble"), "类型名不合法")


def case_predicates():
    for good in ("core", "a1_b", "A", "abc_123"):
        check(is_name(good), f"{good!r} 应该是合法名字")
    for bad in ("", None, "1core", "_x", "a-b", "a b", 1):
        check(not is_name(bad), f"{bad!r} 不应该被当成合法名字")

    for good in ("0.1", "1.0", "12.34"):
        check(is_version(good), f"{good!r} 应该是合法版本")
    for bad in ("1", "1.", ".1", "1.0.0", "", None, 1.0):
        check(not is_version(bad), f"{bad!r} 不应该被当成合法版本")


CASES = [
    ("parse 合法全名", case_parse_full),
    ("parse 非法格式全部报错", case_parse_invalid),
    ("parse 非字符串抛 TypeIdError", case_parse_non_string),
    ("resolve 短名补全为 linreg_0.1@table", case_resolve_short_name),
    ("resolve 全名原样返回", case_resolve_full_name_unchanged),
    ("resolve 非法输入报错", case_resolve_invalid),
    ("qualify 三段校验", case_qualify),
    ("is_name / is_version 边界", case_predicates),
]


def main():
    return run_cases("typeid", CASES)


if __name__ == "__main__":
    sys.exit(main())
