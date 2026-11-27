---
name: workflow-studio
description: 当用户要求创建、编辑、校验、执行 workflow-studio 的工作流（.flow 文件），或读写其项目文件、查看可用插件与组件时使用；也用于排查工作流校验/执行失败。
---

# workflow-studio

本地数据分析工作流：一个项目目录 + 一个 JSON `.flow` + 一小组 HTTP 接口。引擎按 DAG 顺序执行插件组件，`studio` 提供两类本地服务：

- **launcher**（固定端口，默认 `8765`）：打开/关闭/重启项目、浏览目录。
- **项目服务**（随机端口，由 launcher 拉起）：项目文件读写、插件清单、校验、执行、调试。

你是通过 HTTP 操作它，**不改它的产品代码**。

> **铁律（第一条）：不直接读写本地磁盘上的项目文件。**
> 项目文件的读、写、改、建、删、改名、查版本，一律走 Studio 的 HTTP 接口。`read`/`write` 工具、shell 重定向、`os.` 直接改盘都禁止。

为什么不能用本地文件工具：

1. **路径边界只在服务端执行**：相对路径、拒绝 `..`/绝对路径/盘符/链接越界，全在服务端；自己拼路径等于没有边界。
2. **插件状态只在服务端**：加载了哪些插件目录、同名插件直接报错、哪些子目录不是插件（`/api/project` 的 `skipped`），都是进程内状态。
3. **校验与执行要同一份上下文**：`/api/validate` 与 `/api/run` 共用同一 registry；另跑 CLI 的插件集合与工作目录都可能不同。
4. **智能体可能没有本地文件权限**：整个闭环必须只用 HTTP 完成；要落盘就让流程里的 `SaveCSV`/`SaveModel` 写，再 `GET /api/file` 读。

`examples/e2e.py` 连输入文件也走 `POST /api/file`——示例本身在演示接口。

## 正确姿势（照抄；不要用 shell / 本地文件工具）

| 要做的事 | 用接口 | 不要用 |
|---|---|---|
| 进入项目 | `POST /api/projects`（launcher）→ 取 `project.url` | `cd`、自己拼本地路径 |
| 列项目目录 | `GET /api/tree?path=`（只列一层） | `ls`、`dir`、glob |
| 读文件 | `GET /api/file?path=` | `read`、`cat`、`type` |
| 查文件版本 | `GET /api/stat?path=` → `mtime_ns` | `stat`、`ls -l` |
| 读插件与 schema | `GET /api/plugins` | 读 `plugins/<name>/` 源码、翻组件实现 |
| 新建 / 覆盖文件 | `POST /api/file`（整文件） | `write`、`echo >` |
| 新建目录 | `POST /api/mkdir` | `mkdir` |
| 改名 | `POST /api/rename` | `mv`、`ren` |
| 删除 | `POST /api/delete`（删文件或空目录） | `rm`、`del`、`rmdir` |
| 校验 / 执行 | `POST /api/validate`、`POST /api/run` | `python -m engine …` |

**进入项目的链路是固定的**：先 `POST /api/projects`（launcher，默认 `http://127.0.0.1:8765`），从响应里取 `project.url`；之后所有项目接口都打这个 `url`，不要自己猜端口。

## 前置条件

1. Python **3.12**，仓库根目录执行：

   ```bash
   pip install -r requirements.txt   # 只有调试/官方插件需要；引擎本身零依赖
   ```

2. 起 launcher（只绑 `127.0.0.1`，无认证）：

   ```bash
   python -m studio --port 8765
   ```

   看到 `[studio] launcher 监听 http://127.0.0.1:8765/` 即就绪。

   **已经拿到 HTTP 地址时（例如用户只给了 `http://127.0.0.1:8765`，或你没有本机进程权限）**：跳过第 1、2 步，直接进「五步闭环」，把该地址当 launcher 地址；不要为了“准备环境”去起进程或碰本地文件。

3. 探活：

   ```bash
   curl -s http://127.0.0.1:8765/api/health
   # {"ok": true}
   ```

## 五步闭环

### 1. 打开项目

**前置条件：项目根目录必须已经存在**（由用户或宿主环境准备好）。当前版本**没有创建项目根目录的接口**——`POST /api/projects` 对不存在的路径直接回 `400 {"ok":false,"errors":["目录不存在或不是目录：…"]}`。

- 不要用 shell/本地命令创建目录（`mkdir`、`New-Item`、`os.makedirs` 都算）。
- 需要新项目时：先 `GET /api/fs/dirs` 浏览**已存在**的目录，或直接告诉用户「请先准备一个空目录，我再打开它」。
- 这条只限制**项目根**；项目**内部**的子目录属于正常工作，用 `POST /api/mkdir`（见第 3 步）。
- `examples/e2e.py` 用 `tempfile.mkdtemp()` 自建临时根目录，那是**测试脚手架**（脚本自己建、跑完删）；智能体不要照抄，真实项目必须由用户或宿主准备好。

```bash
curl -s -X POST http://127.0.0.1:8765/api/projects \
  -H "Content-Type: application/json" \
  -d '{"path": "D:/work/demo"}'
```

记下响应里的 `project.url`（例如 `http://127.0.0.1:51234`）——后面所有项目接口都用它。幂等：重复打开同一目录返回同一个 `port`/`pid`。

项目里还没有输入文件（如 `data.csv`）时，同样用 `POST /api/file` 写进项目根，不要直接落盘。

> Windows：`cmd` 里 `curl` 单引号不生效（会得到 `请求体不是合法 JSON`）；改用双引号转义，或直接用 `examples/client.py`（推荐）。

### 2. 读插件（接线的唯一事实来源）

```bash
curl -s http://127.0.0.1:51234/api/plugins
```

只关注三样：

- `plugins[].name` → 节点里的 `plugin`（短名，不带版本）。
- `components[].name` → 节点里的 `component`。
- `config_schema` / `input_schema` / `output_schema` → 怎么填参数、谁能接谁。

**不要凭记忆写组件名和参数**，组件随插件版本变化。

### 3. 建/改 flow：GET 全文 → 改 JSON → POST 整文件

**没有节点级 patch 接口。** 修改必须整文件覆盖：

```bash
# 读全文
curl -s "http://127.0.0.1:51234/api/file?path=flows/demo.flow"

# 改完整体写回（新建也可）
curl -s -X POST http://127.0.0.1:51234/api/file \
  -H "Content-Type: application/json" \
  -d '{"path": "flows/demo.flow", "text": "{\"name\": \"demo\", \"nodes\": []}"}'
```

要点：

- 先 `GET` 再改，**保留你不理解的字段**（尤其顶层 `addition` 是编辑器私有布局块，原样带回去）。
- 改前先 `GET /api/stat?path=...` 记下**旧** `mtime_ns`；提交前再 stat 一次，与旧值比对——**一致才写**，不一致说明被编辑器/别的客户端改过，**重新读一遍再改**。`POST /api/file` 返回的 `mtime_ns` 是本次写入后的新版本，留作下一次比对的基准。
- 父目录不存在先 `POST /api/mkdir`。
- 路径只能是项目根内的正斜杠相对路径；`..`、盘符、绝对路径会被拒（业务失败）。
- 不知道怎么写时，用本 skill 目录下 `flows/` 里的三个样例当模板（`minimal.flow`、`two_nodes.flow`、`with_addition.flow`）。

### 4. 校验

```bash
curl -s -X POST http://127.0.0.1:51234/api/validate \
  -H "Content-Type: application/json" \
  -d '{"workflow": {"name": "demo", "nodes": [{"id": "load", "plugin": "fileio", "component": "LoadCSV", "config": {"path": "data.csv"}}]}}'
```

成功：

```json
{"ok": true, "errors": [], "warnings": ["节点 load 是孤立节点（既没有输入也没有下游）"], "order": ["load"]}
```

（单节点示例必然带这条孤立节点警告，不影响 `ok`；两节点连起来跑就没有。）

失败时 `ok:false` 且 `errors` 是**全量**错误列表（不是遇到第一个就停），逐条改完再验：

```json
{"ok": false, "errors": ["nodes[0]（x）: 组件 nope.Nope 不存在"], "warnings": [], "order": []}
```

`order` 是引擎拓扑排序后的执行顺序；`warnings` 不影响 `ok`（孤立节点只是提示）。

### 5. 执行，插件改动后重启

**首选 `/api/run`**：同步返回每个节点的耗时与输出预览。

```bash
curl -s -X POST http://127.0.0.1:51234/api/run \
  -H "Content-Type: application/json" \
  -d '{"workflow": {"name": "demo", "nodes": [{"id": "load", "plugin": "fileio", "component": "LoadCSV", "config": {"path": "data.csv"}}]}}'
```

```json
{"ok": true, "errors": [], "warnings": ["节点 load 是孤立节点（既没有输入也没有下游）"], "order": ["load"],
 "nodes": [{"id": "load", "component": "fileio.LoadCSV", "ms": 960.04,
            "outputs": {"table": "DataFrame 2 行 × 2 列 ['a', 'b']\n   a  b\n0  1  2\n1  3  4"},
            "error": null}]}
```

- `outputs` 是**预览字符串**，不是原始对象；要完整结果让流程末尾用 `SaveCSV`/`SaveExcel` 落盘，再 `GET /api/file` 读。
- `ok:false` 时看 `errors[0]` 与失败节点的 `nodes[].error`。
- 没有取消接口：`/api/run` 会一直同步到你全部节点跑完。

**插件目录变了必须重启**：launcher 只在项目子进程**启动时**加载一次插件，**不能热加载**。第三方插件 = 解压成**同名目录**（目录名必须等于 `PLUGIN_NAME`）放进 `plugins/`；改完目录里的代码同样要 restart 才生效：

```bash
curl -s -X POST http://127.0.0.1:8765/api/projects/restart \
  -H "Content-Type: application/json" \
  -d '{"root": "D:/work/demo"}'
```

端口不变、`pid` 变新。不重启就仍在跑旧插件。

工作结束：

```bash
curl -s -X POST http://127.0.0.1:8765/api/projects/close \
  -H "Content-Type: application/json" -d '{"root": "D:/work/demo"}'
```

## 从 schema 造 config、从类型接线（速记）

- `config` 按 `config_schema` 填：`required` 且无 `default` 的必须给；有 `default` 的可省略（引擎补默认值，不回写文件）；参数的 `type`/`choices`/`min`/`max` 必须满足。
- `inputs` 形状是 `{入端口: {"from": 上游节点id, "port": 上游输出端口}}`；类型必须**完整标识相等**（`std_1.0@table`），显示短名 `std@table` 不能用来判断。
- `required: true` 的输入必须接；连线不能成环。
- 字符串参数里的 `${NAME}` 由组件自己展开，只有描述里写明"支持 ${变量}"的才有效；`env` 里定义变量。

细节与全部真实报错见 `references/flows.md`。

## 调试 WebSocket（只在需要逐步看时用）

`/api/run` 是一次性批量执行；交互式调试走 `/api/debug/start` 起的 WebSocket：

- 五条命令：`state` / `inspect` / `run_node` / `continue` / `stop`。
- 五种推送：`ack` / `state` / `log` / `error` / `inspect`。
- 执行类命令一次只能一条，在跑时再发会得到 `{"type":"error","message":"正在执行"}`。

协议细节见 `references/api.md` 第 4 节。**批量任务不要用调试接口**。

## 错误处理口径

两类失败，判断顺序固定：

1. **HTTP 4xx/5xx**：请求不合法（`400`）、Host/Origin 不对（`403`）、路由不存在（`404`）、体积超限（`413`）、服务内部错（`500`）。
2. **HTTP 200 + `ok:false`**：业务失败——校验不通过、节点执行失败、路径越界、项目未运行、调试会话不存在。

```python
if status != 200:
    raise StudioError(f"HTTP {status}")        # 501 等可能是 HTML，先别 json.loads
if not (isinstance(body, dict) and body.get("ok")):
    errors = body.get("errors") if isinstance(body, dict) else None
    raise StudioError(errors or ["ok=false"])
```

`errors` 是字符串数组，第一条通常就是根因；校验错误可能有多条。全部真实文案见 `references/errors.md`。

## 什么时候读哪份

| 需要什么 | 读 |
|---|---|
| 某个接口的字段、真实请求/响应、状态码、CLI、WS 协议 | `references/api.md` |
| 怎么拼 `config`、怎么接 `inputs`、`env`/`addition`、校验错误怎么改 | `references/flows.md` |
| 报错了怎么定位、错误文案对照、排查顺序 | `references/errors.md` |
| 一套能跑的客户端/端到端示例 | `examples/client.py`、`examples/e2e.py` |
| 可直接当模板的 flow | `flows/minimal.flow`、`flows/two_nodes.flow`、`flows/with_addition.flow` |

## 能力边界（细节见 references）

- **没有节点级 patch**：改 flow 只能 GET 全文 → 改 JSON → POST 整文件。
- **没有取消接口**：`/api/run` 同步跑完；要逐步控制改用调试 WebSocket。
- **文件操作有边界**：`delete` 删文件或空目录（目录非空回 `ok:false`）；读不了二进制与 >1 MiB；`tree` 只列一层。
- **没有创建项目根目录的接口**：目录必须由用户或宿主准备好。
- 完整清单：`references/api.md` §5；安全与禁区：`references/errors.md` §7。

## 安装

1. 把 `docs/skill/` 整个目录复制到你的智能体 skill 目录。
2. **把目录重命名为 `workflow-studio/`**——规范加载器要求目录名与 frontmatter 的 `name` 一致，本包 `name` 是 `workflow-studio`。
3. 装好后结构：`workflow-studio/SKILL.md` + `references/` + `examples/` + `flows/`。

自检（进到 `workflow-studio/` 目录里跑）：

```bash
python examples/e2e.py --launcher http://127.0.0.1:8765
```

它会在临时目录里建项目，依次走完打开→插件→建 flow→校验→执行→重启→关闭并断言，最后打印 `OK`。
