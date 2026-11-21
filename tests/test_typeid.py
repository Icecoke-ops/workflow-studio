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
    check(parse("acme_0.2@dataset") == ("acme", "0.2", "dataset"), "acme_0.2@dataset 解析结果不对")
    check(parse("acme_0.2@model") == ("acme", "0.2", "model"), "acme_0.2@model 解析结果不对")
    check(
        parse("school_bean_0.1@stu") == ("school_bean", "0.1", "stu"),
        "插件名含下划线时解析结果不对",
    )


def case_parse_invalid():
    bad = [
        "core_1.0",        # 缺 @
        "core_1@table",    # 版本写成 1
        "core_1.0.0@table",
        "1acme_0.2@dataset",  # 插件名数字开头
        "core_1.0@ta-ble",  # 类型名非法字符
        "core_1.0@ta ble",
        "core_1.0@1table",
        "core_1.0@",
        "@table",
        "_acme_0.2@dataset",
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
        resolve("table", "acme", "0.2") == "acme_0.2@table",
        f"短名应补全为 acme_0.2@table，实际 {resolve('table', 'acme', '0.2')!r}",
    )
    check(
        resolve("model", "acme", "0.2") == "acme_0.2@model",
        "短名 model 补全结果不对",
    )


def case_resolve_full_name_unchanged():
    check(
        resolve("acme_0.2@dataset", "acme", "0.2") == "acme_0.2@dataset",
        "带 @ 的全名应原样返回",
    )
    # 没有 @ 就按短类型名处理，"acme_0.2" 不是合法类型名
    expect_raises(
        TypeIdError, lambda: resolve("acme_0.2", "acme", "0.2"), "类型名不合法"
    )


def case_resolve_invalid():
    expect_raises(TypeIdError, lambda: resolve("", "acme", "0.2"), "非空字符串")
    expect_raises(TypeIdError, lambda: resolve(None, "acme", "0.2"), "非空字符串")
    expect_raises(TypeIdError, lambda: resolve("table", "1bad", "0.2"), "插件名不合法")
    expect_raises(TypeIdError, lambda: resolve("table", "acme", "1"), "版本号不合法")
    expect_raises(TypeIdError, lambda: resolve("ta-ble", "acme", "0.2"), "类型名不合法")


def case_qualify():
    check(qualify("acme", "0.2", "dataset") == "acme_0.2@dataset", "qualify 拼接结果不对")
    expect_raises(TypeIdError, lambda: qualify("1core", "1.0", "table"), "插件名不合法")
    expect_raises(TypeIdError, lambda: qualify("acme", "1", "table"), "版本号不合法")
    expect_raises(TypeIdError, lambda: qualify("acme", "0.2", "ta-ble"), "类型名不合法")


def case_predicates():
    for good in ("core", "a1_b", "A", "abc_123"):
        check(is_name(good), f"{good!r} 应该是合法名字")
    for bad in ("", None, "1core", "_x", "a-b", "a b", 1):
        check(not is_name(bad), f"{bad!r} 不应该被当成合法名字")

    for good in ("0.2", "1.0", "12.34"):
        check(is_version(good), f"{good!r} 应该是合法版本")
    for bad in ("1", "1.", ".1", "1.0.0", "", None, 1.0):
        check(not is_version(bad), f"{bad!r} 不应该被当成合法版本")


CASES = [
    ("parse 合法全名", case_parse_full),
    ("parse 非法格式全部报错", case_parse_invalid),
    ("parse 非字符串抛 TypeIdError", case_parse_non_string),
    ("resolve 短名补全为 acme_0.2@table", case_resolve_short_name),
    ("resolve 全名原样返回", case_resolve_full_name_unchanged),
    ("resolve 非法输入报错", case_resolve_invalid),
    ("qualify 三段校验", case_qualify),
    ("is_name / is_version 边界", case_predicates),
]


def main():
    return run_cases("typeid", CASES)


if __name__ == "__main__":
    sys.exit(main())
