"""把 ``plugins/src/<插件>/`` 打包成 ``plugins/<插件>.zip``。

    python tools/build_plugins.py
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "plugins" / "src"
OUT = ROOT / "plugins"

SKIP_DIRS = {"__pycache__", ".mypy_cache", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def build_one(source: Path, out_dir: Path) -> Path:
    name = source.name
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.zip"
    try:
        target.unlink(missing_ok=True)
    except PermissionError:
        # 文件被别的进程持有删除锁（zipimport 会一直拿着 zip）。
        # 原地覆盖也能写，别让构建卡死。
        pass
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source.rglob("*")):
                if path.is_dir():
                    continue
                if set(path.parts) & SKIP_DIRS:
                    continue
                if path.suffix in SKIP_SUFFIX:
                    continue
                archive.write(path, arcname=f"{name}/{path.relative_to(source).as_posix()}")
    except OSError as exc:
        raise SystemExit(
            f"[打包失败] {target} 写不进去：{exc}\n"
            f"        通常是还有 python 进程在跑（studio / engine）拿住了 zip，关掉再试。"
        ) from exc
    return target


def build_all(out_dir) -> list:
    built = []
    if not SRC.is_dir():
        return built
    for source in sorted(SRC.iterdir()):
        if not source.is_dir() or not (source / "__init__.py").is_file():
            continue
        built.append(build_one(source, Path(out_dir)))
    return built


def main() -> int:
    targets = build_all(OUT)
    if not targets:
        print(f"[打包] {SRC} 下没有找到插件")
        return 1
    for target in targets:
        print(f"[打包] {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
