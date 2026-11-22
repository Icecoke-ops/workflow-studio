"""把 ``plugins/src/<插件>/`` 打包成 ``plugins/<插件>.zip``。

    python tools/build_plugins.py
"""

import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "plugins" / "src"
OUT = ROOT / "plugins"

SKIP_DIRS = {"__pycache__", ".mypy_cache", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def _align_mode(temp: Path, target: Path) -> None:
    """POSIX 上沿用目标原有权限；目标不存在时给 0644。Windows 无操作。"""
    if os.name != "posix":
        return
    try:
        mode = os.stat(target).st_mode & 0o7777
    except FileNotFoundError:
        mode = 0o644
    os.chmod(temp, mode)


def build_one(source: Path, out_dir: Path) -> Path:
    name = source.name
    out_dir = Path(out_dir)
    target = out_dir / f"{name}.zip"
    temp = None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # 先写同目录临时文件，写完 os.replace 原子改名：读方只会看到旧版或新版完整 zip
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{name}.", suffix=".zip.tmp", dir=out_dir
        )
        os.close(handle)
        temp = Path(temp_name)
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source.rglob("*")):
                if path.is_dir():
                    continue
                if set(path.parts) & SKIP_DIRS:
                    continue
                if path.suffix in SKIP_SUFFIX:
                    continue
                archive.write(path, arcname=f"{name}/{path.relative_to(source).as_posix()}")
        _align_mode(temp, target)
        os.replace(temp, target)
    except OSError as exc:
        raise SystemExit(
            f"[打包失败] {target} 写不进去：{exc}\n"
            f"        通常是还有 python 进程在跑（studio / engine）拿住了 zip，关掉再试。"
        ) from exc
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
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
