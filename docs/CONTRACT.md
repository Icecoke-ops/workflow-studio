# 接口契约（单一事实来源）

> 实现可以自由，契约不行。改动这里的任何一条，要同时改代码与测试。

---

## 1. 引擎边界

引擎（`engine/`）必须能在脱离仓库其余部分的条件下独立运行：

- **不依赖任何具体插件**。一个插件都没有，或者只有第三方插件、官方插件全删光，引擎照样能加载、校验、执行工作流。
- **不认识 studio 和 frontend**。`engine/` 下的源码不出现、不 import 这两个目录的任何东西，也不为 studio 加任何兼容分支。依赖方向只有一个：studio → engine。
- **插件目录可缺省**。全局目录是引擎包同级的 `plugins/`（与当前工作目录无关），缺失只警告不中断；`-p/--plugins-dir` 可重复，追加扫描任意多个目录。
- **标准类型属于引擎**。`std_1.0@*` 五个类型和 `PredictorModel` 契约定义在 `engine/stdtypes.py`，不由任何插件提供。

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
- 插件名必须是 **`sys.path` 上查不到的**顶层名：加载前用 `PathFinder.find_spec(包名)` 检查，只要能找到 `loader` 非空的模块（磁盘上的标准库模块、已安装的第三方包）就拒绝——插件目录会进 `sys.path`，重名会顶掉全进程对它的 import。`std` 是引擎保留的命名空间，另行拒绝。内置模块（`sys`、`time` 等）不在 `sys.path` 上，`PathFinder` 查不到，因此不单独拦截；但它们的 import 由内置加载器优先解析，zip 顶不掉，不构成风险
- **每个含 `.py` 的目录都必须有 `__init__.py`**（zipimport 不支持隐式命名空间包）
- 源文件不能放在 zip 根目录

`requirements.txt` 只检查依赖**是否已安装**。写了版本约束（如 `pandas>=2.0`）时引擎会在 stderr 提示「只检查是否安装，不校验版本」，不会因此拦住加载。

同一个进程里重复加载同名插件 = **真正重载**：引擎会先清掉 `sys.modules` 里该插件包下的旧模块，再按新 zip 重新导入。所以「改了插件重新 build + load」能拿到新代码，不会复用旧类。

### 2.2 components.py

只做注册，实现写在别的模块里：

```python
from table.impl.columns import SelectColumns

PLUGIN_NAME = "table"         # [A-Za-z][A-Za-z0-9_]*
PLUGIN_VERSION = "1.0"        # \d+\.\d+
PLUGIN_TITLE = "数据处理"
COMPONENTS = [SelectColumns]
```

四个常量都在加载期校验：`PLUGIN_NAME` 必须与 zip 内目录名一致、`PLUGIN_VERSION` 形如 `1.0`、`PLUGIN_TITLE` 必须是字符串（不写或空串则回退为插件名）、`COMPONENTS` 必须是非空列表。

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

`name` / `title` / `desc` 都必须是字符串：`title` 不是字符串会在**插件加载期**报错，而不是等到 Studio 拼载荷时才炸。

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
  "name": "regression_demo",
  "env": {"DATA_DIR": "D:\\data"},
  "nodes": [
    {"id": "n1", "plugin": "fileio", "component": "LoadCSV",
     "config": {"path": "${workspace}/data.csv"}, "inputs": {}},
    {"id": "n2", "plugin": "ml", "component": "LinearRegression",
     "config": {"feature": ["x"], "target": "y"},
     "inputs": {"data": {"from": "n1", "port": "table"}}}
  ]
}
```

- 字段白名单：顶层 `name`/`nodes`/`env`/`addition`（见 5.2）；节点 `id`/`plugin`/`component`/`config`/`inputs`；连线 `from`/`port`。未知字段报错。
- **类型不写进 JSON**，只来自插件 schema。
- 边记在输入侧；一个输入端口只能有一个来源。
- 无输入的节点即起点，没有特殊 start 节点。
- 文件编码必须是 UTF-8（可带 BOM）；GBK 等其它编码直接报错。
- 扩展名习惯用 `.flow`，内容就是本节的 JSON。引擎与 CLI 不检查扩展名；Studio 按 `.flow` 判断「点开进画布」，其它文本文件只读预览。
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
| `workspace` | 进程启动时的工作目录（绝对路径）；Studio 下是项目根 |
| `engine_version` | 引擎版本 |
| `workflow` | 本次运行的 JSON 绝对路径；Studio 下是写入系统临时目录的副本 |
| `run_id` | 本次运行标识（时间戳 + 短随机串），每跑一次都不同 |

**不建议**用二级或三级覆盖上面四个值。程序不拦，但把 `workspace` 写死成某台机器的路径后，换台机器就崩。

时序：组件 `__init__` 里读到的必然是合并后的最终值。**不要在模块 import 时读环境变量**，那时三级还没应用。

插件展开路径用 `engine.api.expand_env`：

```python
from engine.api import expand_env
self.path = expand_env(config["path"])   # "${workspace}/data/x.csv"
```

只认 `${NAME}` 一种写法，未定义变量抛 `ValueError`，不做静默保留。

### 5.2 addition 扩展字段（编辑器私有，引擎不解释）

```json
"addition": {
  "client": "workflow-studio",
  "version": 1,
  "positions": {"n1": {"x": 80, "y": 60}},
  "groups": [
    {
      "id": "g1",
      "title": "子图 1",
      "collapsed": true,
      "position": {"x": 520, "y": 180},
      "members": ["n1", "n2"]
    }
  ]
}
```

`addition` 是**单个客户端私有的整块附加区**，用来存一切与执行无关的数据（节点坐标、编辑器分组等）。

- **引擎只承认这个字段存在**：它在顶层白名单里，但引擎不解释、不校验、不修改，`addition` 是对象、字符串还是数字都不影响校验与执行。写错类型不会报错。
- **没有命名空间隔离**：`addition` 整块属于当前客户端。换个客户端打开时它可能被整块覆盖或丢弃，这是有意的取舍——文件本身永远可用，只是布局和分组没了。
- **靠两个字段认来源**：`client`（字符串，本编辑器是 `workflow-studio`）与 `version`（整数格式版本）。客户端遇到 `client` 不符或 `version` 高于自己支持的值，应当**整块忽略并提示**，不要报错拒绝加载，也不要去猜别人的格式。
- **保存时整块重写自己的**，不与别人的内容合并。
- 只读路径（`validate`、`run`、预览）不写文件，因此不会破坏其它客户端写入的内容。
- 其它顶层字段**不在此列**：写错的白名单字段仍然报「存在未知字段」，`addition` 只放行它自己。第三方客户端若要存自己的数据，应整块使用 `addition` 或向维护者提出新增顶层字段。
- 子集约定（本编辑器当前写入的键）：`positions` 是 `{节点 id: {x, y}}`，只对 `nodes` 里存在的 id 有意义，缺的节点由编辑器自行布局；`groups` 每项是 `{id, title, collapsed, members}`，可选 `position: {x, y}`（只在折叠时用来放卡片位置）。`members` 里放节点 id，也可以放另一个组的 id——子图可以嵌套，一个单元只属于一个组。两者都只是编辑器约定，引擎与其它客户端不解释。

---

## 6. Studio HTTP API

> 面向智能体的使用文档（skill 包）见 [docs/skill/SKILL.md](skill/SKILL.md)。

Studio 是两层进程：

| 进程 | 启动方式 | 端口 | 职责 |
|---|---|---|---|
| launcher（落地页） | `python -m studio` | 固定，默认 8765 | 管理项目子进程、浏览服务端目录、发落地页 |
| 项目服务 | launcher 拉起 `python -m studio --serve <项目根>` | 随机（`--port 0`），实际端口写进 `--port-file` | 项目内文件读写、插件加载、校验/执行/调试 |

`--serve` 是内部参数，用户入口只有 `python -m studio`。打开一个目录起一个项目进程；同一目录再次打开复用已运行实例；关闭即结束子进程；重启是在**同一端口**重起（端口未释放时重试 10 次 × 100 ms，仍失败回「端口被占用，重启失败」，不偷换端口）。项目进程启动后 `chdir` 到项目根，`/api/run` 与调试子进程里的相对路径都按项目根解析。

两个服务都只绑 `127.0.0.1`，没有远程访问开关。

### 6.1 launcher API

所有响应 UTF-8，`Content-Type: application/json; charset=utf-8`。

| 方法 | 路径 | 请求 / 响应 |
|---|---|---|
| GET | `/api/health` | `{"ok":true}` |
| GET | `/api/projects` | `{"ok":true,"projects":[{"root","name","port","pid","url"}],"errors":[]}` |
| POST | `/api/projects` | `{"path":"<目录>"}` → `{"ok":true,"project":{"root","name","port","pid","url"}}`；失败 `ok:false`、`project:null` |
| POST | `/api/projects/close` | `{"root":"<目录>"}` → `{"ok":true,"errors":[]}`；未运行回 `ok:false` |
| POST | `/api/projects/restart` | `{"root":"<目录>"}` → 同 open |
| GET | `/api/fs/dirs` | `?path=<目录>`，空串表示盘符列表 → `{"ok":true,"path","parent","entries":[{"name","path"}]}`；`path` 为空串、`parent` 为 null 表示盘符层 |
| GET | `/` | `studio/landing/index.html`（单文件静态页，无外部资源）；带 `?close=<项目根>` 时先弹确认，用户确认后才关闭该项目 |

`url` 是 `http://127.0.0.1:<port>`，落地页在新标签页直接跳过去。打开项目时如果同目录已有实例，返回同一个 `port`/`pid`，不另起进程。

错误口径：请求体不是 JSON 对象、缺字段、`path` 指向不存在或不是目录（`/api/projects`、`/api/fs/dirs`）时回 400（`{"ok":false,"errors":[…]}`）；业务失败（项目未运行、端口被占用、子进程启动失败）回 200 + `ok:false`。项目服务不同：**所有业务失败都回 200 + `ok:false`**，只有报文形状错误才 4xx（§6.2）。

### 6.2 项目服务 API

| 方法 | 路径 | 响应 |
|---|---|---|
| GET | `/api/health` | `{"ok":true,"engine":"0.7.0","plugins":6,"components":27}` |
| GET | `/api/plugins` | `{"plugins":[{name,version,title,types:[{id,desc}],components:[{name,title,desc,config_schema,input_schema,output_schema}]}]}` |
| GET | `/api/project` | `{"ok":true,"root","name","launcher","plugins":{"global":n,"project":n},"skipped":[{"file","path","reason","source"}],"errors":[]}` |
| GET | `/api/tree` | `?path=<项目内相对路径>`（空串=项目根）→ `{"ok":true,"path","entries":[{name,path,kind:"dir"\|"file",size?}],"errors":[]}`，只列一层，目录在前 |
| GET | `/api/file` | `?path=` → `{"ok":true,"path","kind":"text"\|"binary"\|"too_large","size","text","errors":[]}` |
| GET | `/api/stat` | `?path=` → `{"ok":true,"path","kind":"file"\|"missing"\|"dir","size","mtime_ns","errors":[]}`；`mtime_ns` 是 `st_mtime_ns`（整数纳秒），目录与缺失文件的两值为 `null`；文件不存在回 `kind:"missing"`（200，不是错误），供前端轮询判断磁盘变更 |
| POST | `/api/file` | `{"path","text"}` → `{"ok":true,"path","size","mtime_ns","errors":[]}`，原子写；`text` 必须是合法 UTF-8（孤立代理项回 `ok:false`）。落盘后 `os.stat` 取 `mtime_ns`；已写入但取不到 stat 时回 `ok:false`（此时文件可能已写入） |
| POST | `/api/mkdir` | `{"path"}` → `{"ok":true,"path","errors":[]}` |
| POST | `/api/rename` | `{"path","new_name"}` → `{"ok":true,"path","errors":[]}`；`new_name` 必须能原样落盘：不含分隔符、`<>:"\|?*`、控制字符，不以点或空格结尾，不是 CON/PRN/AUX/NUL/COM1-9/LPT1-9 保留名。`/api/file` POST 与 `/api/mkdir` 的路径每一段也按这套名字规则校验 |
| POST | `/api/delete` | `{"path"}` → `{"ok":true,"path","errors":[]}`；目录必须为空，项目根不可删 |
| POST | `/api/validate` | 请求 `{"workflow":{...}}` → `{"ok":bool,"errors":[],"warnings":[],"order":[]}` |
| POST | `/api/run` | 请求同上 → `{"ok":bool,"errors":[],"warnings":[],"order":[],"nodes":[{id,component,ms,outputs:{端口:preview},"error":null}]}` |
| POST | `/api/debug/start` | 请求同上 → `{"ok":true,"session":"<id>","port":8801,"token":"<随机串>"}` |
| POST | `/api/debug/stop` | 请求 `{"session":"<id>"}` → `{"ok":true}` |
| GET | `/`、`/static/*` | 回 `studio/web/` 下的文件（`/` 回 `index.html`） |

`engine` 是引擎版本字符串（取自 `engine/__init__.py` 的 `__version__`），**示例里的数字随发版变化，不属于契约**；`plugins` / `components` 是当前加载的插件数与组件数。

`input_schema` 每项额外带 `type_labels`（短名数组），`output_schema` 每项额外带 `type_label`，供界面显示。

插件加载：全局目录（引擎包同级 `plugins/`）始终参与；项目根下 `plugins/` 存在时作为项目插件一起加载。同名插件硬报错——`/api/project` 回 `ok:false`、`errors` 带两个绝对路径，`health` 的插件数归零，但文件接口照常可用；非插件 zip 只进 `skipped`（带 `source: "global"|"project"`），不报错。

路径规则：所有 `path` 都是**项目内相对路径**，拒绝 `..`、绝对路径、盘符、UNC，也拒绝经链接（junction / 符号链接）指到项目外。文本文件上限 1 MiB，含 NUL 判为 `binary`。

错误口径：请求体不是 JSON 对象（解析失败、顶层不是对象、缺 `workflow`）回 400，未知路径回 404，请求体超过 16 MiB 回 413，响应体均为 `{"ok":false,"errors":[具体消息]}`。业务失败（校验不通过、执行期异常、文件操作失败）回 200 + `ok:false`，原因进 `errors`——`/api/run` 的执行期异常**不回 500**。`/api/stat` 缺 `path` 参数回 400，路径非法或越界回 200 + `ok:false`（与其他业务失败一致，此时不含 `path`/`kind`/`size`/`mtime_ns`）。服务端自身**载荷违反契约**（`ContractError`，我方 bug）回 500 + 字段级消息，原样给调用方；其余**意外异常**回 500 + `{"ok":false,"errors":["服务器内部错误"]}`，完整栈只写服务端日志，不把内部路径或异常原文暴露给前端。客户端中途断开直接静默，不写响应。

### 6.3 调试会话

调试是**子进程 + 钩子**，Studio 自己不 import 引擎跑图。前端拿到 `port`/`token` 后直连钩子的 WebSocket（§9.6），Studio 只负责起和杀。

- `start`：把请求里的 `workflow` 原样写进系统临时目录的 JSON，`secrets` 随机 token，spawn `python -m engine run --hook hooks/http_debug -e workspace=<项目根> -e hook_port=0 -e hook_port_file=<临时目录>/debug_<session>.port -e hook_token=<token> <临时文件>`；**Studio 不自己挑端口**，只等钩子把 bind 时的实际端口写进那个文件（**超时 10 秒**，超时杀子进程、删临时文件、回 `ok:false`，并把子进程 stderr 尾部带进 `errors`）。子进程提前崩同样立刻失败，不等满超时。
  - 为什么不「先挑空闲端口再连一下」：端口在挑选和真正 bind 之间会被别人占走，而「连得上」无法区分自己的钩子和别人的监听——那会把别人的钩子当成就绪（已踩过，偶发 WebSocket 1000 关闭）。端口由 bind 分配、文件由钩子写完，窗口不存在。
- **子进程 cwd = 项目根**，仓库根经 `PYTHONPATH` 注入（cwd 不再是仓库根，否则 `-m engine` 找不到）。`${workspace}` 显式传项目根，且排在其他 `-e` 之前，用户自己的覆盖仍然生效。
- **插件必须原样透传**：项目根下有 `plugins/` 时追加 `--plugins-dir <项目根>/plugins`，与 Studio 主进程加载的是同一批 zip；否则调试子进程看到的插件跟主进程不一致，那种差异以后极难查。`-e` 同样原样透传。
- **同一时刻只允许一个调试会话**；新 `start` 先按 `stop` 流程关掉旧的。
- `stop`：先 `POST http://127.0.0.1:<port>/shutdown` 让它自己退，3 秒内没退就 `kill`；删临时文件。未知 `session` 回 `ok:false`。
- 子进程的 stdout/stderr 由 Studio 接管，不混进 Studio 自己的输出；Studio 进程退出时关掉所有调试子进程。Windows 上调试子进程被放进 Job Object（父进程死掉即终止）；其它平台没有等价兜底，项目进程被 SIGTERM 时调试子进程可能残留——当前只在 Windows 实测。

### 6.4 绑定与认证

launcher 与项目服务都固定绑 `127.0.0.1`，并校验请求来源：

- `Host` 只接受 `127.0.0.1:<本端口>` 与 `localhost:<本端口>`，否则 403；挡 DNS rebinding。
- POST 若带 `Origin`，必须与 `http://127.0.0.1:<本端口>` / `http://localhost:<本端口>` 同源，否则 403；无 `Origin`（curl、测试）放行。挡住本机其它页面的跨源读写。

服务没有认证，能连上端口的人都可以调 `/api/run`、读写项目文件，所以不提供局域网暴露，也不要把它当多用户服务用。

### 6.5 前端构建约束（踩过坑）

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
| 指定插件目录 | `python -m engine run -p <dir> <json>` |
| 指定环境变量 | `python -m engine -e DATA_DIR=D:\data -e MODEL_DIR=D:\models run <json>` |
| 挂执行钩子 | `python -m engine run --hook <钩子路径> -e hook_port=<端口> -e hook_token=<token> <json>`（`http_debug` 还要 `-e hook_port_file=<文件>`，`hook_port=0` 即系统分配） |
| 起 Web 服务 | `python -m studio`（落地页，默认 8765；项目进程由它拉起） |
| 构建前端 | `python tools/build_web.py` |
| 冒烟 | `python tests/smoke.py` |
| 全量测试 | `python tests/run_all.py` |

`-p/--plugins-dir` 可重复，写在子命令前后都有效。实际扫描 = 引擎包同级的 `plugins/` + 所有指定目录，每个目录只扫一层 `*.zip`，不递归；不同目录出现同名插件直接报错，不静默覆盖。

---

## 8. 刻意不做（别再提）

单 env 隔离、沙箱、环执行、并发分支、重试、断点续跑、中间产物落盘、撤销重做、自动布局。

---

## 9. 执行钩子

引擎只提供**事件表与分发器**（`engine/hooks.py`）。具体钩子一个都不放进 `engine/`，都在 `hooks/<名字>/`，与 `plugins/` 平级，不进引擎包。

### 9.1 加载与注册

`python -m engine run --hook <路径> <json>`，v1 只允许一个 `--hook`，重复指定报错。

- 路径是目录：找 `hook.py`，没有就找 `__init__.py`；是文件：直接加载。**目录里有 `__init__.py` 时按 Python 包加载**，可以用 `from .xxx import ...` 拆成多个文件；单文件 `hook.py` 只适合小钩子。
- 模块必须有 `install(ctx)`。缺了报错退出，不做静默降级。
- `install` 里用 `ctx.on(事件名, 回调)` 注册。**未知事件名直接报错并列出全部合法名**（拼写错误不许静默失效）。
- `install` 在插件加载完成之后、`plugins_loaded` 事件触发之前调用；此刻 `ctx.execution` 是 `None`，等实例全部建好才填上——前三个事件（`plugins_loaded` / `workflow_loaded` / `env_ready`）的回调拿到的 `execution` 参数同样是 `None`。
- 可选定义 `serve(execution)`：定义了它就由它驱动整轮运行（引擎**不自动跑任何节点**，它自己调 `run_node` / `run_all`），返回即运行结束；没定义则由引擎按 `order` 顺序跑完。`result_file` 不需要它，`http_debug` 必须有。
- 传参一律走已有的 `-e`，不新增命令行参数。

回调签名统一为 `fn(data: dict, execution) -> None`：**原地改 `data` 生效**，引擎在回调返回后只回读该事件允许的字段（见 9.2 表最后一列），其余改动忽略；返回值不用。多个钩子将来串联时就是同一份 `data` 依次传下去，结构与就地修改天然一致。

### 9.2 事件表

一次运行的固定顺序：

```
plugins_loaded → workflow_loaded → env_ready
  → 全部节点先建实例: node_create_before → node_create_after   （初始化错误一次暴露，不跑到一半才炸）
  → 逐节点: node_invoke_before → node_end
→ run_end
```

| 事件 | 触发点 | `data` | 回读字段 |
|---|---|---|---|
| `plugins_loaded` | 插件全部加载完，工作流还没读 | `plugins: [名字]`、`components: int`、`types: int` | 无（只读） |
| `workflow_loaded` | JSON 读进、**全量校验之前** | `workflow: dict`（原始 JSON）、`path: str` | `workflow` → 重新全量校验，失败即中止 |
| `env_ready` | 三级 env 合并写进 `os.environ` 之后 | `env: {键: 值}`（工作流 `env` 与 `-e` 的合并结果，不含引擎自动注入的 `workspace` / `engine_version`） | `env` → 覆盖写回 `os.environ`，不删除未出现的键 |
| `node_create_before` | `cls(config)` 之前 | `node: str`、`config: dict` | `config` → 校验后按它重建 |
| `node_create_after` | 实例建好之后 | `node: str`、`instance: object` | 无（不承诺"替换实例"的语义） |
| `node_invoke_before` | 输入取齐、`invoke()` 之前 | `node: str`、`inputs: {端口: 值}` | `inputs` → 键集必须与**工作流实际接线的**输入端口一致（可选端口没接就不要求），否则报错 |
| `node_end` | `invoke()` 成功且输出校验通过之后 | `node: str`、`outputs: {端口: 值}`、`duration_ms: float` | `outputs` → 再走一次输出校验 |
| `run_end` | 跑完或中止（中止时也触发） | `status: "ok"\|"failed"`、`order: [str]`、`error: str\|None`、`duration_ms: float` | 无（只读） |

回调抛异常 = 中止整个运行，包装成 `RunAborted`（原异常挂 `__cause__`），`run_end` 仍触发。节点执行失败抛 `ExecutionError`，该节点状态记为 `failed`。

### 9.3 Execution

```python
class Execution:
    registry: Registry
    workflow: Workflow | None                # workflow_loaded 之后才有
    order: list[str]                         # 拓扑序
    values: dict[tuple[str, str], object]    # (节点 id, 端口) -> 真实对象，就是"程序的堆"
    results: dict[str, NodeResult]           # 节点 id -> 本轮结果（输出 + 耗时）
    status: dict[str, str]                   # 节点 id -> unrun | fresh | stale | failed
    errors: dict[str, str]                   # 节点 id -> 失败原因（成功即清），全仓唯一一份
    warnings: list[str]                      # 校验阶段的警告

    def run_node(self, node_id, config=None) -> NodeResult
    def run_all(self, on_node_done=None) -> dict[str, NodeResult]
    def close(self) -> None
```

- 构造 `Execution(workflow, registry)` 时建全部实例（逐个触发 `node_create_before` / `node_create_after`），`status` 全为 `unrun`。
- `run_node` 顺序：节点不存在 → 报错；`config` 给了且与当前不同 → `node_create_before` → 校验 → **先构造新实例，构造成功才 `close()` 旧实例并替换**（构造失败则旧实例与 config 原样保留、直接抛错，节点状态不变——否则会留下一个「看着 fresh、其实跑不了」的节点）；**重建成功时该节点的旧输出立即作废**（从 `values`/`results` 里删掉、状态回 `unrun`）：旧输出是用旧参数算的，留着会让下游读到错的数；`node_create_after`；收输入（缺则 `MissingInput`）；`node_invoke_before` → `invoke()` → 校验输出 → `node_end` → 写 `values` → 标 `fresh`，并**递归**把已成为 `fresh` 的下游标 `stale`（从没跑过的保持 `unrun`，否则跑完第一个节点全图都变 stale，状态会骗人）。
- `run_all` = 按 `order` 逐个 `run_node`，**不发 `run_end`**。
- `close()` 幂等，关掉全部实例。

两个入口，分开用：

```python
def execute(registry, path, cli_env=None, hook=None, on_start=None, on_node_done=None) -> Execution
def run(workflow, registry, on_node_done=None) -> dict[str, NodeResult]
```

- `execute` 是带钩子的完整驱动：装钩子 → `plugins_loaded` → 读 JSON → `workflow_loaded` → 校验 → 合并 env → `env_ready` → `on_start(execution)` → 建实例 → 钩子有 `serve` 就交给它驱动、没有就 `run_all` → `run_end` → `close`。CLI 的 `run` 子命令走这里；`on_start` 让它在**开跑之前**就能打出警告和 `[开始执行]`，失败运行时这行也不能缺。
- `run` 保留给「手里已经有校验过的 Workflow」的调用方（Studio 现有代码、smoke、测试）：只跑节点、不发前置三个事件，行为与今天逐字节一致。

引擎侧异常：`RunAborted`（钩子回调抛异常，原异常挂 `__cause__`）、`MissingInput`（缺输入，继承 `ExecutionError`）、`HookError`（钩子路径、缺 `install`、未知事件名）、`ValidationFailed`（带 `report`，CLI 靠它逐条还原 `[错误]`）。

### 9.4 缺输入报错

```
节点 n3（ml.GradientBoostingRegressor）缺少输入：
  model  ← 来自 n5「保存模型」，该节点尚未执行
  data   ← 来自 n1「读取 CSV」，已执行 ✓
建议：先执行 n5
```

每行是 `端口 ← 来自 <来源节点>「<节点名>」，<该节点尚未执行|已执行 ✓>`；`建议`取第一个尚未执行的来源。缺输入的节点**状态保持 `unrun`**（它确实没跑过），错误记在该节点的 `error` 字段、命令级 `phase` 为 `failed`。

`run_end` 的 `status`：本轮有执行期异常（`error` 非空）**或 `execution.errors` 非空**就是 `"failed"`（缺输入这类节点没开跑、只记 `errors` 的情况也算失败）；`serve` 钩子自己吞掉了异常也不例外。节点的每一种失败都先写进 `errors`，所以判据只看 `errors`，不再额外看 `status`；钩子不要去清 `errors`。`error` 字段只表达「本轮被异常打断」的原因，节点级原因看 `errors`。

### 9.5 官方钩子：`hooks/result_file/`

只注册 `run_end`，把结果写进 `hook_result_path` 指定的 JSON。**`install` 阶段就检查这个变量，没设直接报错退出，不开跑**（别等跑完才抱怨）。真实对象用 `engine.preview.preview()` 转成字符串——JSON 装不下 DataFrame。

```json
{"status":"ok","error":null,"order":["n1","n2"],
 "nodes":{"n1":{"duration_ms":12.3,"outputs":{"data":"DataFrame shape=(100, 2)"}}}}
```

### 9.6 官方钩子：`hooks/http_debug/`

WebSocket 服务，Studio 的调试器直连。引擎启动后**不自动跑任何节点**，一切等命令。该钩子依赖 `websockets`（已在仓库根 `requirements.txt` 里声明，锁在实测过的大版本）；**版本或底层接口不符时钩子直接拒绝启动**，错误文案带当前版本与 `pip install -r requirements.txt`，不会静默连不上。

- `hook_port`（可选）：给了就绑这个端口，`0` 或省略由系统分配。
- `hook_token`（必填，缺则拒绝启动）。
- `hook_port_file`（必填）：**钩子绑定成功之后**立刻把实际端口写进这个文件（纯文本一行数字）。Studio 以「这个文件出现」作为就绪信号，**不再靠尝试连接端口来判断**——「连得上」不等于「那是自己的子进程」，端口被别的会话占用时会把别人的钩子当成自己的。
- 地址 `ws://127.0.0.1:<hook_port>/?token=<hook_token>`；带 `Origin` 时必须匹配 `http://127.0.0.1:<任意端口>` 或 `http://localhost:<任意端口>`。
- **握手被拒一律先回 HTTP 响应再关连接**，不静默断联：token 不符回 `403 bad token`、`Origin` 不符回 `403 bad origin`、缺 `Upgrade` 由库回 `426`、报文头语法非法回 `400 bad request`。响应带 `Connection: close` 与简短正文，发完 `shutdown` 写端再关，避免 RST 吃掉正文。预检只覆盖**语法**，且要求完整报文头在**一次 4096 字节读取**内：超过 4096 字节、分包到达的头，以及语义非法（如 129 个头、非零或重复 `Content-Length`）仍可能被直接关闭——那是库自身的行为，不额外模拟。
- 同一时刻只执行一条命令，忙时回 `error`（**`inspect` 例外**：它只读堆，执行中也可以发）。

命令（客户端 → 服务）：

| 命令 | 含义 | 回应 |
|---|---|---|
| `{"cmd":"state"}` | 要状态快照 | `state` |
| `{"cmd":"run_node","id":"n3","config":{...}}` | 跑一个节点，`config` 可省 | `ack` → `state` |
| `{"cmd":"continue"}` | 从第一个非 `fresh` 节点顺序跑到结束 | `ack` → `state` |
| `{"cmd":"stop"}` | 中止当前执行（**在节点之间生效**，正在跑的节点会跑完） | `ack` |
| `{"cmd":"inspect","id":"n1"}` | 取该节点当前的**详细**输入/输出预览（不执行、不改状态） | `inspect` |

推送（服务 → 客户端）：

```json
{"type":"state","data":{"phase":"idle","current":null,"order":["n1"],
  "nodes":{"n1":{"status":"unrun","duration_ms":null,"error":null,"outputs":{}}}}}
{"type":"log","node":"n1","stream":"stdout","text":"epoch 3/50 ..."}
{"type":"ack","cmd":"run_node"}
{"type":"error","message":"节点 n3（ml.X）缺少输入：…"}
{"type":"inspect","data":{"node":"n1","inputs":{"data":"shape=(60, 2)…"},"outputs":{"table":"shape=(60, 2)…"}}}
```

`inspect` 是**只读**命令：不执行节点、不改任何状态。`inputs` 按工作流连线从上游已产出的值解析，`outputs` 取该节点已完成的结果；**没有值的端口不出现**（刚连上时两个字典都可能为空，这不是错误）。文本由 `engine.preview.detail()` 生成，比 `state` 里的短摘要详细（表格给 shape、列名、dtype、前 20 行与数值列 `describe()`；模型给类型与参数；其余按类型多给几行），**单个端口文本上限 16384 个字符**（与 `preview()` 的 `MAX_CHARS` 同口径，按字符不按字节），超出截断并在末尾注明。未知节点回 `error`（`未知节点：n1`）。

节点状态**只有 `state` 一条通道**：不再有独立的 `event` 推送（`node_end` 的全部信息——`status`/`duration_ms`/`outputs`/`error`——都在节点级 `state` 里，两套就是漂移的起点）。§9.2 的 `node_end` **引擎事件**照旧，那是给所有钩子用的。

- `phase`：`idle | running | paused | ended | failed`。
- `state` 推送时机**三种各一次**：命令开始（`phase=running`）、每个节点结束后、命令/整轮结束（回到 `idle`/`paused`/`ended`/`failed`）。否则 `running` 这个相位永远不会出现，客户端只能自己再造一套「在途」判断。
- `POST http://127.0.0.1:<hook_port>/shutdown` → 钩子退出；Studio 关图时先发这个，3 秒后 `kill` 子进程兜底。钩子侧最多等当前节点 **1.5 秒**，超时直接退出（所以跑得久的节点会被 Studio 的 kill 收掉，这是预期）。该接口只认**单个 TCP 包内**的请求行，不处理分片——本机 Studio 调用满足这个前提。
- **日志捕获是进程级 fd 重定向**（不是替换 `sys.stdout`）：`os.pipe()` + `os.dup2` 接管 fd 1/2，两个读线程按 UTF-8（`errors="replace"`）解码、按 `\n` 与 `\r` 都切行、剥 ANSI 转义码、同节点 500ms 内连续 `\r` 只留最后一条；待发送队列最多 5000 行，客户端积压时丢最旧的——读线程绝不阻塞管道。日志**从客户端连上之后开始推送，之前的输出不补发**（面板一开就连上，实际只会丢掉引擎开跑前那一两行）。启动前必须先关缓冲（`PYTHONUNBUFFERED=1` + `line_buffering=True`），否则日志会攒成大块延迟吐出。`node` 为当前正在跑的节点，节点外为 `null`。

### 9.7 版本边界

v1 一个钩子、无断点（"继续"就是跑到结束）、调试期间改图结构不生效：会话在启动时对工作流取快照，调试中改动画布不影响当前会话（新加的节点回 `节点 n1 不存在`；`inspect` 对快照外的 id 回 `未知节点：n1`），要重新开始调试才按新结构跑。多钩子串联留到输入输出结构能保证一致时再做。
