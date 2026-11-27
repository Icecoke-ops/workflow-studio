"""端到端自检：打开项目 → 读插件 → 建 flow → 校验 → 执行 → 读结果 → 重启 → 关闭。

    python docs/skill/examples/e2e.py --launcher http://127.0.0.1:8765

前置：launcher 已在跑（`python -m studio --port 8765`）。脚本自己在临时目录建项目，
结束时关闭项目并删除临时目录；全程断言，任何一步不符就非零退出。
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from client import Launcher, StudioError


def pick(plugins, plugin_name, component_name):
    """按名字取组件 schema；取不到直接失败（名字来自 /api/plugins，不凭记忆写）。"""
    for plugin in plugins["plugins"]:
        if plugin["name"] != plugin_name:
            continue
        for component in plugin["components"]:
            if component["name"] == component_name:
                return component
    raise AssertionError(f"插件清单里没有组件 {plugin_name}.{component_name}")


def check_config(component, config):
    """照着 config_schema 自检：required 且无 default 的参数必须给。"""
    schema = component["config_schema"]
    for name, spec in schema.items():
        if spec.get("required") and "default" not in spec:
            assert name in config, f"{component['name']}.{name} 是必填参数，没有给值"
    for name in config:
        assert name in schema, f"{component['name']} 没有参数 {name}（未知参数会被校验拒绝）"
    return config


def main():
    parser = argparse.ArgumentParser(description="workflow-studio 端到端自检")
    parser.add_argument("--launcher", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    launcher = Launcher(args.launcher)
    root = Path(tempfile.mkdtemp(prefix="ws-skill-e2e-"))

    project = None
    try:
        # 1. 打开项目
        opened = launcher.open_project(str(root))
        assert opened["ok"], opened
        info = opened["project"]
        assert Path(info["root"]).resolve() == root.resolve(), (info["root"], root)
        project = launcher.project(url=info["url"])
        # 输入文件同样走接口写进项目根（不直接落盘）
        seeded = project.write_file("data.csv", "a,b\n1,2\n3,4\n")
        assert seeded["ok"], seeded
        print(f"[1/7] 打开项目 {info['name']} → {info['url']}（已写入 data.csv）")

        # 2. 读插件，确认组件存在
        health = project.health()
        assert health["ok"] and health["plugins"] >= 1, health
        plugins = project.plugins()
        load = pick(plugins, "fileio", "LoadCSV")
        select = pick(plugins, "table", "SelectColumns")
        save = pick(plugins, "fileio", "SaveCSV")
        assert "table" in load["output_schema"] and "data" in select["input_schema"]
        print(f"[2/7] 插件 {health['plugins']} 个 / 组件 {health['components']} 个")

        # 3. 建 flow：config 照 config_schema 填，inputs 照输出/输入类型接
        flow = {
            "name": "e2e：读 CSV 选列另存",
            "nodes": [
                {
                    "id": "load",
                    "plugin": "fileio",
                    "component": "LoadCSV",
                    "config": check_config(load, {"path": "data.csv"}),
                },
                {
                    "id": "select",
                    "plugin": "table",
                    "component": "SelectColumns",
                    "config": check_config(select, {"columns": ["a"]}),
                    "inputs": {"data": {"from": "load", "port": "table"}},
                },
                {
                    "id": "save",
                    "plugin": "fileio",
                    "component": "SaveCSV",
                    "config": check_config(save, {"path": "result.csv"}),
                    "inputs": {"data": {"from": "select", "port": "table"}},
                },
            ],
        }
        assert project.mkdir("flows")["ok"]
        # 改文件前先 stat：还不存在时 kind=missing，不会报错
        assert project.stat_file("flows/demo.flow")["kind"] == "missing"
        text = json.dumps(flow, ensure_ascii=False, indent=2)
        written = project.write_file("flows/demo.flow", text)
        assert written["ok"] and written["size"] == len(text.encode("utf-8")), written
        # 写后 stat 必须与写入响应里的 mtime_ns 一致
        stat = project.stat_file("flows/demo.flow")
        assert stat["kind"] == "file", stat
        assert stat["size"] == written["size"] and stat["mtime_ns"] == written["mtime_ns"], (stat, written)
        assert project.read_file("flows/demo.flow")["text"] == text
        print("[3/7] flow 已写入，stat 版本与读回内容一致")

        # 4. 校验
        report = project.validate(flow)
        assert report["ok"], report["errors"]
        assert report["order"] == ["load", "select", "save"], report["order"]
        print(f"[4/7] 校验通过，顺序 {report['order']}")

        # 5. 执行并读结果
        result = project.run(flow)
        assert result["ok"], result["errors"]
        assert [node["id"] for node in result["nodes"]] == ["load", "select", "save"]
        assert "DataFrame 2 行" in result["nodes"][0]["outputs"]["table"]
        saved = project.read_file("result.csv")
        assert saved["kind"] == "text", saved
        # pandas 在 Windows 上按 os.linesep 写行尾，统一成 \n 再比较
        assert saved["text"].replace("\r\n", "\n") == "a\n1\n3\n", repr(saved["text"])
        print("[5/7] 执行成功，结果文件内容正确")

        # 6. 重启（插件改动后必须走这里；端口不变、pid 变）
        restarted = launcher.restart_project(str(root))
        assert restarted["ok"], restarted
        assert restarted["project"]["url"] == info["url"], restarted
        assert restarted["project"]["pid"] != info["pid"], restarted
        project = launcher.project(url=restarted["project"]["url"])
        assert project.health()["ok"]
        print(f"[6/7] 重启完成，pid {info['pid']} → {restarted['project']['pid']}")

        # 7. 关闭
        closed = launcher.close_project(str(root))
        assert closed["ok"], closed
        remaining = [item for item in launcher.projects()["projects"] if item["root"] == str(root)]
        assert not remaining, remaining
        project = None
        print("[7/7] 关闭完成")
    except (AssertionError, StudioError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        if project is not None:
            try:
                launcher.close_project(str(root))
            except StudioError:
                pass
        shutil.rmtree(root, ignore_errors=True)

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
