"""逐个运行 tests/test_*.py 并汇总。

直接运行：python tests/run_all.py
全部通过 exit 0，有失败 exit 1。
"""

import importlib.util
import sys
import traceback
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

ORDER = [
    "test_typeid.py",
    "test_schema.py",
    "test_loader.py",
    "test_workflow.py",
    "test_runner.py",
    "test_cli.py",
    "test_preview.py",
    "test_contract.py",
]


def load_test_module(path, index):
    spec = importlib.util.spec_from_file_location(f"_test_{index}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_files():
    files = [TESTS_DIR / name for name in ORDER if (TESTS_DIR / name).is_file()]
    extra = sorted(
        path for path in TESTS_DIR.glob("test_*.py") if path.name not in ORDER
    )
    return files + extra


def main():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if str(TESTS_DIR) not in sys.path:
        sys.path.insert(0, str(TESTS_DIR))

    files = collect_files()
    if not files:
        print("没有找到任何 test_*.py")
        return 1

    failed = []
    for index, path in enumerate(files):
        print(f"\n===== {path.name} =====")
        try:
            module = load_test_module(path, index)
            code = module.main()
        except SystemExit as exc:
            code = exc.code or 0
        except Exception:
            traceback.print_exc()
            code = 1
        if code:
            failed.append(path.name)

    print("\n===== 汇总 =====")
    for path in files:
        print(f"{'FAIL' if path.name in failed else 'PASS'}  {path.name}")
    print(f"\n共 {len(files)} 个测试文件，失败 {len(failed)} 个")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
