"""项目根内的文件读写：所有路径都锁在项目根内，越界即业务失败。"""

import os
import tempfile
from pathlib import Path

MAX_READ = 1024 * 1024  # 1 MiB：超过只回类型与大小，不把整份文件读进内存


class ProjectError(Exception):
    """业务失败；消息直接给人看。"""


class Project:
    def __init__(self, root):
        root = Path(root)
        if not root.is_dir():
            raise ProjectError(f"项目目录不存在或不是目录：{root}")
        self.root = root.resolve()
        self.name = self.root.name or str(self.root)

    # -- 路径 ------------------------------------------------------------
    def resolve(self, rel):
        """项目内相对路径 → 绝对路径；越界抛 ProjectError。"""
        parts = _rel_parts(rel)
        target = self.root.joinpath(*parts)
        try:
            resolved = target.resolve()
        except OSError as exc:
            raise ProjectError(f"无法解析路径 {rel!r}：{exc}") from None
        if not _inside(self.root, resolved):
            raise ProjectError(f"路径越出项目根：{rel!r}")
        return resolved

    # -- 读 --------------------------------------------------------------
    def list_dir(self, rel):
        """列一层：目录在前、文件在后，各自按 name.casefold() 排序。"""
        parts = _rel_parts(rel)
        directory = self.resolve(rel)
        if not directory.is_dir():
            raise ProjectError(f"不是目录：{_display(parts)}")
        dirs, files = [], []
        try:
            with os.scandir(directory) as scanned:
                for entry in scanned:
                    try:
                        is_dir = entry.is_dir()
                        size = None if is_dir else entry.stat().st_size
                    except OSError:
                        continue  # 扫描期间消失的条目直接跳过
                    item = {
                        "name": entry.name,
                        "path": "/".join(parts + [entry.name]),
                        "kind": "dir" if is_dir else "file",
                    }
                    if size is not None:
                        item["size"] = size
                    (dirs if is_dir else files).append(item)
        except OSError as exc:
            raise ProjectError(
                f"读取目录失败 {_display(parts)}：{_reason(exc)}"
            ) from None
        dirs.sort(key=lambda item: item["name"].casefold())
        files.sort(key=lambda item: item["name"].casefold())
        return {
            "ok": True,
            "path": "/".join(parts),
            "entries": dirs + files,
            "errors": [],
        }

    def read_text(self, rel):
        """读文本；二进制或超过 1 MiB 时只回类型与大小。"""
        parts = _rel_parts(rel)
        if not parts:
            raise ProjectError("路径不能为空")
        path = self.resolve(rel)
        if not path.is_file():
            raise ProjectError(f"不是文件：{_display(parts)}")
        try:
            with path.open("rb") as handle:
                size = os.fstat(handle.fileno()).st_size
                if size > MAX_READ:
                    return _file_result(parts, size, "too_large")
                raw = handle.read(MAX_READ + 1)
        except OSError as exc:
            raise ProjectError(f"读取失败 {_display(parts)}：{_reason(exc)}") from None
        if len(raw) > MAX_READ:  # stat 之后文件又变大了
            return _file_result(parts, len(raw), "too_large")
        if b"\x00" in raw:
            return _file_result(parts, size, "binary")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return _file_result(parts, size, "binary")
        return _file_result(parts, size, "text", text)

    # -- 写 --------------------------------------------------------------
    def write_text(self, rel, text):
        """新建或覆盖文本文件：同目录临时文件 + os.replace，UTF-8 无 BOM。"""
        parts = _rel_parts(rel)
        if not parts:
            raise ProjectError("路径不能为空")
        if not isinstance(text, str):
            raise ProjectError("写入内容必须是字符串")
        path = self.resolve(rel)
        if path.is_dir():
            raise ProjectError(f"目标是目录，不能写入：{_display(parts)}")
        parent = path.parent
        if not parent.is_dir():
            raise ProjectError(f"父目录不存在：{_parent_display(parts)}")
        data = text.encode("utf-8")
        try:
            fd, temporary = tempfile.mkstemp(
                dir=str(parent), prefix=".studio-", suffix=".tmp"
            )
        except OSError as exc:
            raise ProjectError(f"写入失败 {_display(parts)}：{_reason(exc)}") from None
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temporary, path)
        except OSError as exc:
            raise ProjectError(f"写入失败 {_display(parts)}：{_reason(exc)}") from None
        finally:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True, "path": "/".join(parts), "size": len(data), "errors": []}

    def mkdir(self, rel):
        parts = _rel_parts(rel)
        if not parts:
            raise ProjectError("路径不能为空")
        path = self.resolve(rel)
        if _exists(path):
            raise ProjectError(f"已存在：{_display(parts)}")
        parent = path.parent
        if not parent.is_dir():
            raise ProjectError(f"父目录不存在：{_parent_display(parts)}")
        try:
            os.mkdir(path)
        except FileExistsError:
            raise ProjectError(f"已存在：{_display(parts)}") from None
        except OSError as exc:
            raise ProjectError(
                f"创建目录失败 {_display(parts)}：{_reason(exc)}"
            ) from None
        return {"ok": True, "path": "/".join(parts), "errors": []}

    def rename(self, rel, new_name):
        parts = _rel_parts(rel)
        if not parts:
            raise ProjectError("不能重命名项目根")
        if not isinstance(new_name, str) or not new_name:
            raise ProjectError("新名字不能为空")
        if new_name in (".", "..") or "/" in new_name or "\\" in new_name:
            raise ProjectError(f"新名字只能是单个名字：{new_name!r}")
        source = self.resolve(rel)
        if not _exists(source):
            raise ProjectError(f"不存在：{_display(parts)}")
        target = source.with_name(new_name)
        target_parts = parts[:-1] + [new_name]
        if _exists(target):
            raise ProjectError(f"目标已存在：{_display(target_parts)}")
        try:
            os.rename(source, target)
        except OSError as exc:
            raise ProjectError(
                f"重命名失败 {_display(parts)}：{_reason(exc)}"
            ) from None
        return {"ok": True, "path": "/".join(target_parts), "errors": []}

    def delete(self, rel):
        parts = _rel_parts(rel)
        if not parts:
            raise ProjectError("不能删除项目根")
        path = self.resolve(rel)
        if not _exists(path):
            raise ProjectError(f"不存在：{_display(parts)}")
        try:
            if path.is_symlink() or not path.is_dir():
                os.unlink(path)
            else:
                if any(path.iterdir()):
                    raise ProjectError(f"目录不为空，不能删除：{_display(parts)}")
                os.rmdir(path)
        except OSError as exc:
            raise ProjectError(f"删除失败 {_display(parts)}：{_reason(exc)}") from None
        return {"ok": True, "path": "/".join(parts), "errors": []}


# ---- 路径 --------------------------------------------------------------

def _rel_parts(rel):
    """把项目内相对路径切成段；绝对路径、盘符、UNC、.. 一律拒绝。"""
    if not isinstance(rel, str):
        raise ProjectError("路径必须是字符串")
    if "\x00" in rel:
        raise ProjectError(f"路径含非法字符：{rel!r}")
    if rel.startswith(("/", "\\")) or (len(rel) > 1 and rel[1] == ":"):
        raise ProjectError(f"路径必须是项目内相对路径：{rel!r}")
    parts = [part for part in rel.replace("\\", "/").split("/") if part and part != "."]
    if ".." in parts:
        raise ProjectError(f"路径不能包含 ..：{rel!r}")
    return parts


def _inside(root, target):
    """normcase 比较：挡住大小写差异、8.3 短名和符号链接绕出去。"""
    root_key = os.path.normcase(str(root))
    target_key = os.path.normcase(str(target))
    return target_key == root_key or target_key.startswith(root_key + os.sep)


def _exists(path):
    return path.exists() or path.is_symlink()


def _display(parts):
    return "/".join(parts) or "."


def _parent_display(parts):
    return "/".join(parts[:-1]) or "."


def _reason(exc):
    return exc.strerror or str(exc)


def _file_result(parts, size, kind, text=None):
    return {
        "ok": True,
        "path": "/".join(parts),
        "kind": kind,
        "size": size,
        "text": text,
        "errors": [],
    }
