# workflow-studio

一个面向专业开发人员的**数据分析工作流执行引擎**，外加一个本地 Web 可视化编辑器。

引擎只做一件事：按 JSON 描述把插件组件连成一张有向无环图，按依赖顺序执行。核心引擎纯标准库、零第三方依赖；第三方依赖只活在插件里。编辑器是可选的，命令行就能跑完整流程。

## 设计约定

- **引擎薄，插件厚**：引擎不理解业务，只负责加载、校验、排序、执行。
- **JSON 是唯一事实来源**：一个工作流就是一个 JSON 文件，没有数据库、没有隐藏状态。
- **插件是 zip 包**：`plugins/<插件名>.zip`，声明与实现分离。
- **类型不写进工作流**：端口类型来自插件 schema，JSON 里只写连到哪个节点的哪个端口。
- **只管 DAG**：循环暂不支持，有环直接报错。

## 目录

| 目录 | 内容 |
|---|---|
| `engine/` | 工作流引擎：加载、校验、排序、执行、CLI，零第三方依赖 |
| `plugins/src/core/` | 示例插件：`LoadCSV`、`SelectColumns`、`PredictModel` |
| `plugins/src/linreg/` | 示例插件：`MakeLinearData`、`FitLinearRegression`、`Evaluate` |
| `studio/` | 本地 Web 后端（标准库 `ThreadingHTTPServer`）+ 前端构建产物 |
| `frontend/` | Vite + Vue 3 可视化编辑器源码 |
| `tools/` | 打包插件、构建前端、查文件负责人 |
| `tests/` | 测试套件 |
| `workflows/` | 示例工作流 |
| `docs/` | 契约文档与文件归属表 |

## 快速开始

需要 Python 3.12。示例插件依赖 `numpy` 和 `pandas`：

```bash
pip install numpy pandas
```

**1. 打包插件**（源码在 `plugins/src/`，打包成 `plugins/*.zip`）

```bash
python tools/build_plugins.py
```

**2. 命令行跑一个工作流**

```bash
python -m engine plugins                          # 列出插件、类型、组件和端口
python -m engine validate workflows/linreg_demo.json
python -m engine run workflows/linreg_demo.json
```

跑通的示例会打印每个节点的耗时和输出摘要，最后给出 MSE / RMSE / MAE / R²。

**3. 起可视化编辑器**

```bash
npm --prefix frontend install      # 首次需要
python tools/build_web.py          # 构建前端并拷贝到 studio/web
python -m studio --port 8765
```

打开 <http://127.0.0.1:8765>。改完前端代码后重新执行 `python tools/build_web.py` 即可，刷新页面生效。

Studio 的其他参数：

```bash
python -m studio --plugins plugins --host 127.0.0.1 --port 8765
```

## 工作流长什么样

```json
{
  "name": "linreg_demo",
  "nodes": [
    {
      "id": "n1",
      "plugin": "linreg",
      "component": "MakeLinearData",
      "config": { "n_samples": 200, "slope": 2.0, "intercept": 1.0, "noise": 0.5, "seed": 42 },
      "inputs": {}
    },
    {
      "id": "n2",
      "plugin": "linreg",
      "component": "FitLinearRegression",
      "config": { "feature": "x", "target": "y" },
      "inputs": { "data": { "from": "n1", "port": "data" } }
    }
  ]
}
```

节点只有五个字段：`id`、`plugin`、`component`、`config`、`inputs`。连线是 `inputs.<输入端口> = {"from": 上游节点 id, "port": 上游输出端口}`。没有输入的节点就是起点，不存在专门的 start 节点。

## 写一个插件

```
plugins/src/myp/          # 目录名必须等于 PLUGIN_NAME
├── __init__.py           # 必须有：zipimport 不支持隐式命名空间包
├── requirements.txt      # 第三方依赖，一行一个
├── components.py         # 只放声明：PLUGIN_NAME / PLUGIN_VERSION / PLUGIN_TITLE / COMPONENTS
└── impl/                 # 组件实现，一个组件一个文件
    ├── __init__.py
    └── my_component.py
```

组件继承 `engine.api.Component`，实现三个静态 schema 方法和 `invoke`：

```python
from engine.api import Component

class MyComponent(Component):
    name = "MyComponent"
    title = "我的组件"
    desc = "一句话说明"

    @staticmethod
    def config_schema():  return {"n": {"type": "integer", "title": "数量", "default": 10}}
    @staticmethod
    def input_schema():   return {"data": {"types": ["std_1.0@table"], "title": "输入"}}
    @staticmethod
    def output_schema():  return {"result": {"type": "std_1.0@table", "title": "输出"}}

    def __init__(self, config):
        self.n = config["n"]

    def invoke(self):
        return {"result": ...}   # 必须覆盖 output_schema 的全部端口
```

类型标识是 `插件名_版本@类型名`，例如 `std_1.0@table`。插件内可以直接写短名（`table`）表示自己的类型，写全名表示引用别的插件的类型。引擎内置 `std` 命名空间提供 `table` / `number` / `string` / `boolean` / `model` 五个标准类型。

打包就是把 `plugins/src/myp/` 打成 `plugins/myp.zip`，`python tools/build_plugins.py` 会校验目录名与 `PLUGIN_NAME` 是否一致。

完整的字段规则（schema 里每个键的含义、类型规则、工作流字段白名单）看 **[docs/CONTRACT.md](docs/CONTRACT.md)**。

## 测试

```bash
python tests/run_all.py        # 引擎/插件/CLI 全量用例
python tests/smoke.py          # 端到端冒烟
python tests/studio_api.py     # Web 后端接口
python tools/who_owns.py --audit   # 检查每个文件都有负责人
```

`tests/` 下 8 个文件、125 个用例。每个文件也能单独运行，例如 `python tests/test_loader.py`。

## 开发约定

文件归属写在 `docs/owners.json`，`tools/who_owns.py <路径>` 查某个文件归谁负责。接口契约（插件格式、类型规则、工作流 JSON、HTTP API）以 `docs/CONTRACT.md` 为准，改动契约要同时改文档和 `studio/contract.py` 里的校验器。

## 许可证

MIT，见 [LICENSE](LICENSE)。
