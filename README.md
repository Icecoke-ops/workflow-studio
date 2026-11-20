# workflow-studio

一个面向专业开发人员的**数据分析工作流执行引擎**，外加一个本地 Web 可视化编辑器。

引擎只做一件事：按 JSON 描述把插件组件连成一张有向无环图，按依赖顺序执行。核心引擎纯标准库、零第三方依赖；第三方依赖只活在插件里。编辑器是可选的，命令行就能跑完整流程。

## 设计约定

- **引擎薄，插件厚**：引擎不理解业务，只负责加载、校验、排序、执行。
- **JSON 是唯一事实来源**：一个工作流就是一个 JSON 文件，没有数据库、没有隐藏状态。
- **插件是 zip 包**：`plugins/<插件名>.zip`，声明与实现分离。
- **类型不写进工作流**：端口类型来自插件 schema，JSON 里只写连到哪个节点的哪个端口。
- **只管 DAG**：循环暂不支持，有环直接报错。
- **引擎能独立跑**：只把 `engine/` 拷走就能用，不依赖 studio、frontend，也不依赖任何具体插件。

## 目录

| 目录 | 内容 |
|---|---|
| `engine/` | 工作流引擎：加载、校验、排序、执行、CLI，零第三方依赖 |
| `plugins/src/fileio/` | 数据读写：CSV / JSON / Excel 的加载与保存（5 个组件） |
| `plugins/src/table/` | 数据处理：选列改列、过滤排序、缺失值、值计数（11 个组件） |
| `plugins/src/split/` | 数据划分：切训练/测试集、按列拆特征 X 与目标 Y（2 个组件） |
| `plugins/src/ml/` | 机器学习：5 个回归模型 + 回归评估（依赖 scikit-learn） |
| `plugins/src/core/` | 模型应用：`PredictModel`，接任何符合 `std_1.0@model` 的模型 |
| `studio/` | 本地 Web 后端（标准库 `ThreadingHTTPServer`）+ 前端构建产物 |
| `frontend/` | Vite + Vue 3 可视化编辑器源码 |
| `tools/` | 打包插件、构建前端、查文件负责人 |
| `tests/` | 测试套件 |
| `workflows/` | 示例工作流 |
| `docs/` | 契约文档与文件归属表 |

## 内置组件

插件按**职责**分包，依赖也跟着分开：装不装 scikit-learn 决定你能不能用 `ml`，跟读不读 CSV 无关。

| 插件 | 组件 |
|---|---|
| `fileio`（pandas、openpyxl） | `LoadCSV` `LoadJSON` `LoadExcel` `SaveCSV` `SaveExcel` |
| `table`（pandas） | `SelectColumns` `DropColumns` `RenameColumns` `CastColumn` `FilterRows` `SortRows` `HeadRows` `ConcatTables` `FillMissing` `DropMissing` `ValueCounts` |
| `split`（pandas、numpy） | `SplitTable` `SplitXY` |
| `ml`（scikit-learn） | `LinearRegression` `Ridge` `Lasso` `RandomForestRegressor` `GradientBoostingRegressor` `EvaluateRegression` |
| `core`（无第三方依赖） | `PredictModel` |

`SplitTable` 输出 `train` 和 `test` 两个端口；`SplitXY` 输出特征表 `x` 和目标表 `y`，分别接预测和评估。`PredictModel` 接任何 `std_1.0@model`，所以模型插件换了也不用改流程。

## 快速开始

需要 Python 3.12。示例插件依赖 `pandas`、`numpy`、`openpyxl`、`scikit-learn`：

```bash
pip install pandas numpy openpyxl scikit-learn
```

**1. 打包插件**（源码在 `plugins/src/`，打包成 `plugins/*.zip`）

```bash
python tools/build_plugins.py
```

**2. 准备数据**

示例工作流从 `${workspace}/data.csv` 读数据，仓库不附带任何数据文件。在工作目录放一个两列 CSV 就行，`x` 是特征、`y` 是目标：

```csv
x,y
0.0,1.2
1.0,3.1
2.0,4.9
```

**3. 命令行跑一个工作流**

```bash
python -m engine plugins                          # 列出插件、类型、组件和端口
python -m engine validate workflows/regression_demo.json
python -m engine run workflows/regression_demo.json
```

跑通的示例会打印每个节点的耗时和输出摘要，最后给出 MSE / RMSE / MAE / R² / MAPE。

**插件从哪加载**

默认扫两处：工程里的 `plugins/`（跟当前工作目录无关，永远是这个目录），加上 `-p/--plugins-dir` 指定的目录，可以写多个：

```bash
python -m engine run --plugins-dir D:\workspace\space --plugins-dir C:\analy_env auto_analy.json
```

每个目录只扫一层 `*.zip`，不递归。目录不存在只警告并跳过，不中断。想只用自定义目录，把工程里的 `plugins/` 删掉即可。不同目录出现同名插件会直接报错，不会静默覆盖。

**环境变量**

路径这类东西不必每次写全，用环境变量传：

```bash
python -m engine -e DATA_DIR=D:\data -e MODEL_DIR=D:\models run auto_analy.json
```

优先级从高到低：命令行 `-e` > 工作流 JSON 顶层 `env` > 引擎自动注入。

引擎自动提供四个变量：`workspace`（启动时的工作目录）、`engine_version`（引擎版本）、`workflow`（本次运行的 JSON 路径）、`run_id`（每次运行唯一）。

插件里用 `engine.api.expand_env` 就能引用它们：

```python
from engine.api import expand_env
self.path = expand_env(config["path"])    # "${workspace}/data/sales.csv"
```

工作流自己需要的配置也能写在 JSON 顶层 `env` 里，可视化编辑器顶栏有「环境变量」按钮可以图形化编辑。

**4. 起可视化编辑器**

```bash
npm --prefix frontend install      # 首次需要
python tools/build_web.py          # 构建前端并拷贝到 studio/web
python -m studio --port 8765
```

打开 <http://127.0.0.1:8765>。改完前端代码后重新执行 `python tools/build_web.py` 即可，刷新页面生效。

Studio 的其他参数：

```bash
python -m studio --plugins-dir D:\workspace\space --host 127.0.0.1 --port 8765
```

## 工作流长什么样

```json
{
  "name": "regression_demo",
  "nodes": [
    {
      "id": "n1",
      "plugin": "fileio",
      "component": "LoadCSV",
      "config": { "path": "${workspace}/data.csv" },
      "inputs": {}
    },
    {
      "id": "n2",
      "plugin": "split",
      "component": "SplitTable",
      "config": { "seed": 42 },
      "inputs": { "data": { "from": "n1", "port": "table" } }
    },
    {
      "id": "n3",
      "plugin": "ml",
      "component": "LinearRegression",
      "config": { "feature": ["x"], "target": "y" },
      "inputs": { "data": { "from": "n2", "port": "train" } }
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

`tests/` 下 15 个文件、218 个用例。每个文件也能单独运行，例如 `python tests/test_loader.py`。

## 开发约定

文件归属写在 `docs/owners.json`，`tools/who_owns.py <路径>` 查某个文件归谁负责。接口契约（插件格式、类型规则、工作流 JSON、HTTP API）以 `docs/CONTRACT.md` 为准，改动契约要同时改文档和 `studio/contract.py` 里的校验器。

## 许可证

MIT，见 [LICENSE](LICENSE)。
