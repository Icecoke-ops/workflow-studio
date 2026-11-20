"""测试公共设施：断言、异常匹配、用例循环。

每个 test_*.py 只保留自己的用例，跑测循环统一走这里。
"""

import traceback


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def expect_raises(exc_type, fn, *fragments):
    try:
        fn()
    except exc_type as exc:
        text = str(exc)
        for fragment in fragments:
            check(fragment in text, f"异常信息缺少 {fragment!r}，实际：{text!r}")
        return exc
    except Exception as exc:
        raise AssertionError(
            f"期望 {exc_type.__name__}，实际 {type(exc).__name__}: {exc}"
        ) from None
    raise AssertionError(f"期望 {exc_type.__name__}，但没有抛异常")


def run_cases(label, cases):
    failed = 0
    for name, fn in cases:
        try:
            fn()
        except AssertionError as exc:
            print(f"FAIL {name}: {exc}")
            failed += 1
        except Exception:
            print(f"FAIL {name}: 意外异常")
            traceback.print_exc()
            failed += 1
        else:
            print(f"ok   {name}")
    if failed:
        print(f"\n[FAIL] {label}：{failed}/{len(cases)} 个用例失败")
        return 1
    print(f"\nOK  {label}：{len(cases)} 个用例全部通过")
    return 0
