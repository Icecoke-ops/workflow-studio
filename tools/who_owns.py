"""按 docs/owners.json 回答「这个文件归谁」。

    python tools/who_owns.py engine/loader.py        # 打印归属
    python tools/who_owns.py --audit                 # 检查有没有无主文件

改动某个文件先问一句它归谁，就不会出现两个人同时改一处。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNERS = ROOT / "docs" / "owners.json"

SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv", ".mypy_cache"}


def load_rules():
    data = json.loads(OWNERS.read_text(encoding="utf-8"))
    rules = []
    for entry in data.get("rules", []):
        for prefix in entry.get("paths", []):
            rules.append((prefix.replace("\\", "/"), entry["owner"]))
    return rules


def resolve(path, rules):
    """最长前缀优先。"""
    normalized = str(path).replace("\\", "/").lstrip("./")
    best = None
    for prefix, owner in rules:
        if normalized.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, owner)
    return best[1] if best else None


def iter_files():
    for path in ROOT.rglob("*"):
        if path.is_dir():
            continue
        if SKIP_DIRS & set(path.parts):
            continue
        yield path.relative_to(ROOT).as_posix()


def audit(rules):
    unowned = [name for name in iter_files() if resolve(name, rules) is None]
    if unowned:
        print(f"[无主文件] {len(unowned)} 个：")
        for name in unowned:
            print(f"  {name}")
        print("\n在 docs/owners.json 里补规则，或者把这些文件挪进已有目录。")
        return 1
    print("[归属完整] 仓库里每个文件都有负责人")
    return 0


def main(argv):
    rules = load_rules()
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--audit":
        return audit(rules)
    exit_code = 0
    for target in argv:
        owner = resolve(target, rules)
        if owner:
            print(f"{target}  ->  {owner}")
        else:
            print(f"{target}  ->  [无主]")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
