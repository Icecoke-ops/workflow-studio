# 接口契约（单一事实来源）

> 由 Chief 维护。**任何人要改这里的任何一条，先找 Chief，改完同步更新本文件。**
> 实现可以自由，契约不行。

---

## 1. 文件归属

**唯一事实来源是 [`docs/owners.json`](owners.json)**，这里不再抄一份表——两处维护必然漂移。
查某个文件归谁：`python tools/who_owns.py <路径>`；查有没有无主文件：`--audit`。

规则：
- 谁都不改别人目录下的文件。
- Reviewer、Occam 只读，不改任何文件。
- Tester 只写测试，不改产品代码；测出 bug 报给该文件负责人。
- 跨目录的需求先找 Chief。

### 1.1 引擎边界

引擎（`engine/`）必须能在脱离仓库其余部分的条件下独立运行：

- **不依赖任何具体插件**。一个插件都没有，或者只有第三方插件、官方插件全删光，引擎照样能加载、校验、执行工作流。
- **不认识 studio 和 frontend**。`engine/` 下的源码不出现、不 import 这两个目录的任何东西，也不为 studio 加任何兼容分支。依赖方向只有一个：studio → engine。
- **插件目录可缺省**。全局目录是引擎包同级的 `plugins/`（与当前工作目录无关），缺失只警告不中断；`-p/--plugins-dir` 可重复，追加扫描任意多个目录。
- **标准类型属于引擎**。`std_1.0@*` 五个类型和 `PredictorModel` 契约定义在 `engine/stdtypes.py`，不由任何插件提供。

`tests/test_standalone.py` 固化了前两条，破坏它就会红。

---

## 2. 插件契约

### 2.1 zip 结构

```
<插件名>.zip
└─ <插件名>/
   ├─ __init__.py          # 必须
   ├─ components.py        # 必须，只放声明
   ├─ types.py             # 可选，TYPES = {"短类型名": "说明"}
   ├─ requirements.txt     # 可选，一行一个依赖
   └─ ...                  # 任意子目录、源文件、数据文件
```

硬规则：
- zip 顶层**恰好一个**目录，且目录名 == `PLUGIN_NAME` == zip 文件名主干
- **每个含 `.py` 的目录都必须有 `__init__.py`**（zipimport 不支持隐式命名空间包）
- 源文件不能放在 zip 根目录

同一个进程里重复加载同名插件 = **真正重载**：引擎会先清掉 `sys.modules` 里该插件包下的旧模块，再按新 zip 重新导入。所以「改了插件重新 build + load」能拿到新代码，不会复用旧类。

### 2.2 components.py

只做注册，实现写在别的模块里：

```python
from core.impl.load_csv import LoadCSV

PLUGIN_NAME = "core"          # [A-Za-z][A-Za-z0-9_]*
PLUGIN_VERSION = "1.0"        # \d+\.\d+
PLUGIN_TITLE = "基础组件"
COMPONENTS = [LoadCSV]
```

### 2.3 组件类

必须继承 `engine.api.Component`，少实现一个抽象方法在**加载时**就报错：

```python
class LoadCSV(Component):
    name = "LoadCSV"      # 本插件内唯一，合法标识符
    title = "读取 CSV"
    desc = "把 CSV 文件读成表格"

    @staticmethod
    def config_schema(): return {...}
    @staticmethod
    def input_schema():  return {...}
    @staticmethod
    def output_schema(): return {...}

    def __init__(self, config): ...        # config 已校验、已填默认值
    def invoke(self, **inputs): ...        # 必须返回 {输出端口名: 值}
    def close(self): ...                   # 可选
```

`invoke` 返回的键集合必须与 `output_schema()` 的键集合**完全相等**，多一个少一个都是执行错误。

---

## 3. 类型契约

完整标识：`插件名_版本@类型名`，例 `std_1.0@table`、`acme_0.2@dataset`。

- 插件名、类型名：`[A-Za-z][A-Za-z0-9_]*`
- 版本：`\d+\.\d+`
- 插件源码里写**短名**（`"table"`）= 解析成**本插件**的类型；写**全名**（`"std_1.0@table"`）= 原样使用
- 输出端口只能是**单一**类型；输入端口是**类型列表**，表示接受其中任一
- 兼容判断是字符串全等。插件升版本 → 旧 workflow 全部失配，这是接受的代价

### 3.1 标准类型（引擎内置，永远可用）

定义在 `engine/stdtypes.py`，不依赖任何插件：

| 类型 | 含义 | 绑定的契约 |
|---|---|---|
| `std_1.0@table` | pandas.DataFrame | 无（运行时不做类型检查） |
| `std_1.0@number` | int / float | 无 |
| `std_1.0@string` | 字符串 | 无 |
| `std_1.0@boolean` | 布尔 | 无 |
| `std_1.0@model` | 预测模型 | **必须继承 `engine.api.PredictorModel`** |

`std_` 是保留命名空间：插件不能叫 `std`，加载时直接拒绝。

### 3.2 第三方类型

- **可以定义**：插件在自己的 `types.py` 里声明，标识带自己的前缀，例如 `acme_0.2@dataset`
- **可以被引用**：别的插件在 schema 里写全名即可，**不需要 import 对方任何代码**
- **可以互相复用**：B 接收 A 定义的类型是零耦合的

约束：**只有引擎能定义「被继承的契约」**（`MODELS`）。第三方类型只是名义标签，不能绑定抽象基类——否则每个插件都自称标准，生态就散了。

### 3.3 契约类类型的两道强制

以 `std_1.0@model` 为例：

1. **继承但没实现 `predict`** → 构造模型时抛 `TypeError`，报在产出方节点里
2. **没继承** → 引擎输出校验拦住，报在产出方节点和端口上

所以 `pre` / `infer` 这类改名，第一次执行就会被抓住。

---

## 4. Schema 契约

### 4.1 config_schema（初始化参数）

```python
{"path": {
    "type": "string",        # string|integer|number|boolean|enum|json|array
    "title": "文件路径",
    "desc": "绝对路径，也可写相对路径（按进程工作目录解析）",
    "required": True,         # 无 default 时必须给值
    "default": None,
    "min": None, "max": None, # 数字范围 / 数组长度
    "step": None,
    "choices": None,          # enum 必填：[{"value":..,"label":..} | 标量]
    "pattern": None,          # string 的正则
}}
```

**控件由 `type` 决定，插件不指定 UI 样式**：`enum` → 下拉、`boolean` → 开关、`integer/number` → 数字框、`json` → 多行文本、其余 → 单行文本。

未知字段直接报错（防拼错）。

补充规则：
- `enum` 的候选项区分 `true` 与 `1`：`choices: [1]` 不接受 `true`
- `min` / `max` / `step` 只允许出现在 `integer` / `number` / `array` 上，且 `min` 不能大于 `max`；违反在**插件加载时**报错
- `list` / `dict` 类型的 `default` 会按节点深拷贝，不共享同一对象

### 4.2 input_schema / output_schema

```python
# 输入
{"data": {"types": ["std_1.0@table"], "required": True, "title": "数据", "desc": ""}}
# 输出
{"table": {"type": "std_1.0@table", "title": "结果", "desc": ""}}
```

---

## 5. 工作流 JSON

```json
{
  "name": "linreg_demo",
  "env": {"DATA_DIR": "D:\\data"},
  "nodes": [
    {"id": "n1", "plugin": "linreg", "component": "MakeLinearData",
     "config": {...}, "inputs": {}},
    {"id": "n2", "plugin": "linreg", "component": "FitLinearRegression",
     "config": {...},
     "inputs": {"data": {"from": "n1", "port": "data"}}}
  ]
}
```

- 字段白名单：顶层 `name`/`nodes`/`env`；节点 `id`/`plugin`/`component`/`config`/`inputs`；连线 `from`/`port`。未知字段报错。
- **类型不写进 JSON**，只来自插件 schema。
- 边记在输入侧；一个输入端口只能有一个来源。
- 无输入的节点即起点，没有特殊 start 节点。
- 文件编码必须是 UTF-8（可带 BOM）；GBK 等其它编码直接报错。
- `name` 必须是字符串；省略可以，写成 `null`/数字/布尔会被拒。

### 5.1 环境变量

工作流运行时，引擎把三类来源合并进 `os.environ`，同名时高级别覆盖低级别：

| 级别 | 来源 | 例子 |
|---|---|---|
| 一级 | 引擎自动注入 | `workspace`、`engine_version`、`workflow`、`run_id` |
| 二级 | 工作流 JSON 顶层 `env` | `"env": {"DATA_DIR": "D:\\data"}` |
| 三级 | 命令行 `-e/--env` | `-e DATA_DIR=D:\data` |

优先级：**三级 > 二级 > 一级**。

内置变量：

| 变量 | 值 |
|---|---|
| `workspace` | 进程启动时的工作目录（绝对路径） |
| `engine_version` | 引擎版本 |
| `workflow` | 本次运行的 JSON 绝对路径；Studio 下是写入 `%TEMP%\workflow-studio\` 的临时副本 |
| `run_id` | 本次运行标识（时间戳 + 短随机串），每跑一次都不同 |

**不建议**用二级或三级覆盖上面四个值。程序不拦，但把 `workspace` 写死成某台机器的路径后，换台机器就崩。

时序：组件 `__init__` 里读到的必然是合并后的最终值。**不要在模块 import 时读环境变量**，那时三级还没应用。

插件展开路径用 `engine.api.expand_env`：

```python
from engine.api import expand_env
self.path = expand_env(config["path"])   # "${workspace}/data/x.csv"
```

只认 `${NAME}` 一种写法，未定义变量抛 `ValueError`，不做静默保留。

---

## 6. Studio HTTP API

所有响应 UTF-8，`Content-Type: application/json; charset=utf-8`。

| 方法 | 路径 | 响应 |
|---|---|---|
| GET | `/api/health` | `{"ok":true,"engine":"0.1.0","plugins":3,"components":6}` |
| GET | `/api/plugins` | `{"plugins":[{name,version,title,types:[{id,desc}],components:[{name,title,desc,config_schema,input_schema,output_schema}]}]}` |
| POST | `/api/validate` | 请求 `{"workflow":{...}}` → `{"ok":bool,"errors":[],"warnings":[],"order":[]}` |
| POST | `/api/run` | 请求同上 → `{"ok":bool,"errors":[],"warnings":[],"order":[],"nodes":[{id,component,ms,outputs:{端口:preview},"error":null}]}` |
| GET | `/`、`/static/*` | 回 `studio/web/` 下的静态文件 |

`input_schema` 每项额外带 `type_labels`（短名数组），`output_schema` 每项额外带 `type_label`，供界面显示。

`/api/run` 的执行期异常**不回 500**，返回 `ok:false` 并把原因写进 `errors`。

### 6.1 前端构建约束（踩过坑）

后端静态路由是 `/static/<file>` → `studio/web/<file>`（剥掉 `/static/` 前缀后按相对路径找文件）。所以 Vite 必须构建成：

```js
base: '/static/'      // 构建时生效，dev 用 '/'
```

产物落在 `studio/web/assets/`，页面引用 `/static/assets/index-x.js`，剥前缀后正好命中。

**不能**改成 `base:'./'` + `assetsDir:'static'`：那样页面引用 `./static/index-x.js`，会被解析成 `/static/index-x.js`，剥前缀后去找 `web/index-x.js`，而文件其实在 `web/static/index-x.js`，全部 404 白屏。

---

## 7. 命令

| 用途 | 命令 |
|---|---|
| 打包插件 | `python tools/build_plugins.py` |
| 命令行引擎 | `python -m engine run <json>` / `validate` / `plugins` |
| 指定插件目录 | `python -m engine run --plugins-dir <dir> --plugins-dir <dir> <json>` |
| 指定环境变量 | `python -m engine -e DATA_DIR=D:\data -e MODEL_DIR=D:\models run <json>` |
| 起 Web 服务 | `python -m studio --port 8765` |
| 构建前端 | `python tools/build_web.py` |
| 冒烟 | `python tests/smoke.py` |
| 全量测试 | `python tests/run_all.py` |

`-p/--plugins-dir` 可重复，写在子命令前后都有效。实际扫描 = 引擎包同级的 `plugins/` + 所有指定目录，每个目录只扫一层 `*.zip`，不递归；不同目录出现同名插件直接报错，不静默覆盖。

解释器统一用 `C:\Users\zh\.conda\envs\flow\python.exe`。

沙箱限制：跑子进程必须走 `cmd /c "... > %TEMP%\log.txt 2>&1"` 再读日志，否则会因命名管道被拒而失败。

---

## 8. 刻意不做（别再提）

单 env 隔离、沙箱、环执行、并发分支、重试、断点续跑、中间产物落盘、撤销重做、自动布局、多标签页。

---

## 9. 不留历史包袱（硬规则）

**不写兼容层。** 迁移一次改完，旧形状当场清掉。

具体：

- 旧类型名、旧组件、旧字段、旧配置键、旧函数签名——功能迁走的那一次改动里一起删，不留"为了兼容旧版本"的分支
- 不为"万一还有旧文件"写兜底代码。确实要处理存量文件，写一次性转换脚本，**转换完把脚本一起删**
- 兼容代码不是保险，是利息。今天省一次迁移，明天每次改都要照顾它
- 注释只写**为什么**（约束、踩过的坑、非显然的取舍），不写**是什么**（代码已经说了）。迁移后过期的示例、过时的注释，一并更新或删掉
- 不用的依赖、不用的文件、不用的导出、不用的字段，立即删
- 测试只描述**当前设计**。迁移完成后，「某东西已删除」这类断言可以一起删——它守的是一段已经结束的历史
- 判断标准一句话：**如果删掉它，只有"看旧代码的人"会不舒服，那就删。**
