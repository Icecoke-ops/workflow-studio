# 错误口径与排查

> **读这份文件的时机**：请求失败、`ok:false`、节点执行报错、或者服务连不上时，先在这里按形状定位，再决定改请求还是改工作流。

---

## 1. 两层失败模型

```text
HTTP 状态码  ── 4xx/5xx ──▶ 请求本身有问题（参数、路径、Host、JSON）或服务内部错
             └─ 200 ─────▶ 请求合法；再看 body.ok
body.ok=false（200）───────▶ 业务失败：校验不通过、执行失败、路径越界、项目未运行
```

**只看状态码会把业务失败当成功。** 正确判断：

```python
if status != 200:  # 传输/参数层
    ...
elif not body.get("ok"):  # 业务层
    ...
```

---

## 2. HTTP 层

| 状态 | 真实响应 | 触发条件 |
|---|---|---|
| `400` | `{"ok":false,"errors":["缺少 path 查询参数"]}` | GET `/api/file` 少了 `?path=` |
| `400` | `{"ok":false,"errors":["请求体不是合法 JSON"]}` | body 不是 JSON 对象（含空 body） |
| `400` | `{"ok":false,"errors":["请求体缺少 workflow 对象"]}` | `/api/validate`、`/api/run`、`/api/debug/start` 缺 `workflow` |
| `400` | `{"ok":false,"errors":["请求体缺少 path 字符串"]}` | POST 缺 `path`（`new_name`、`session` 同理） |
| `400` | `{"ok":false,"errors":["目录不存在或不是目录：C:\\nope"]}` | launcher 打开项目 / 浏览目录，路径不可用 |
| `403` | `{"ok":false,"errors":["Host 不被允许：'example.com'"]}` | `Host` 不是 `127.0.0.1:<端口>` / `localhost:<端口>` |
| `403` | `{"ok":false,"errors":["Origin 不被允许：'http://evil'"]}` | POST 带了不同源的 `Origin` |
| `404` | `{"ok":false,"errors":["未知路径：/api/nope"]}` | 路由不存在（注意 `/api/file` 是 GET+POST，别写成 PUT） |
| `413` | `{"ok":false,"errors":["请求体超过 <上限> 字节"]}` | 声明的 `Content-Length` 超过上限：项目服务 `16777216`、launcher `1048576` |
| `500` | `{"ok":false,"errors":["服务器内部错误"]}` | 未预期异常，看服务端终端 traceback |
| `501` | **HTML**（`<html>…Unsupported method ('PUT')…`），不是 JSON | 用了未实现的方法（`PUT`/`PATCH`/`DELETE` 等） |

`403` 基本都是客户端拼错了地址：用 `127.0.0.1`，别用机器名、局域网 IP 或 `0.0.0.0`。

`501` 是传输层直接回的 HTML 错误页，**不在 JSON 错误模型里**：先按状态码判断，不要对非 200 响应无条件 `json.loads`。需要操作文件就用文档里的方法（`/api/file` 只有 GET 与 POST）。

**`目录不存在或不是目录：…` 的处置**：这是 launcher 打开项目（`POST /api/projects`）时的 `400`，说明项目根不存在。处理顺序：

1. 把响应原文交给用户，请他提供或创建一个**已存在的**目录。
2. 想自己找：先 `GET /api/fs/dirs` 浏览已存在目录，别猜路径。
3. **不要**用 shell/本地命令去造目录——当前版本没有创建项目根目录的接口；你造出来的目录不受用户预期管理，也可能没有写权限。项目内子目录不受此限，用 `POST /api/mkdir`。

**体积上限（413）**：上限按请求头里声明的 `Content-Length` 判断——项目服务 16 MiB、launcher 1 MiB。

- 声明值刚过上限、但不超过 **32 MiB**：服务端会把请求体读完，再回干净的 `413` JSON（`{"ok":false,"errors":["请求体超过 <上限> 字节"]}`，项目服务与 launcher 的上限不同，见上面的表）。
- 声明值明显超过（**> 32 MiB**）：服务端最多只再读 32 MiB 请求体就回 413 并**关闭连接**。此时客户端可能还在写，看到的是连接被重置（Windows 常见 `WinError 10053`；Python 里是 `ConnectionAbortedError` / `RemoteDisconnected`），拿不到 JSON。
- **正确做法**：客户端在发送前按自己已知的 `Content-Length` 自查，超限就在本地拒绝，不要依赖服务端的 413；内容太大就拆小，或让流程里的组件落盘、再用 `GET /api/file` 读。

这是有意的取舍：不为了一个注定失败的请求把超大请求体全读进内存。

---

## 3. 业务层（200 + `ok:false`）

### 3.1 工作流校验

| 文案 | 原因 | 改法 |
|---|---|---|
| `nodes 必须是非空数组` | 顶层 `nodes` 缺失/为空/不是数组 | 至少放一个节点 |
| `工作流存在未知字段 ['foo']` | 顶层多了字段 | 删掉；编辑器数据放 `addition` |
| `nodes[0]: 未知字段 ['position']` | 节点里放了编辑器字段 | 只留 `id/plugin/component/config/inputs` |
| `nodes[0]（x）: 组件 nope.Nope 不存在` | `plugin`/`component` 拼错或插件没加载 | 回 `GET /api/plugins` 抄 `name` |
| `nodes[1]（load）: id 重复` | 两个节点同 id | 换唯一 id |
| `nodes[0]（load）.config.path: 缺少必填参数（文件路径）` | `required` 且无 `default` 的参数没给 | 按 `config_schema` 补值 |
| `nodes[0]（load）.config: 未知参数 ['bogus']` | `config` 里多写了 schema 没有的键 | 删掉或改用正确参数名 |
| `env 变量名不合法：'1X'` | `env` 键不符合 `^[A-Za-z_][A-Za-z0-9_]*$` | 换合法名 |
| `nodes（select）.inputs.data: 缺少必填输入（需要 std@table）` | 必填输入没接线 | 补 `inputs.data` |
| `nodes（save）.inputs.data: 类型不匹配，来源输出 std@model，本端口需要 std@table` | 上游输出类型不在下游 `types` 里 | 换上游或换下游，比对完整类型标识 |
| `nodes[0]（z）.inputs.nope: 组件没有这个输入端口（可用：无）` | 端口名拼错 | 照 `input_schema` 的键名 |
| `工作流存在环，这些节点无法排序：['a', 'b']` | 连线成环 | 断开一条边；只支持 DAG |

校验**一次报全部错误**：一次 `validate` 的 `errors` 可能有好几条，按顺序改完再请求，不要一条一条试。（例外：某个节点自身没解析成功——例如 `id` 重复——时，它后面的组件/参数/端口检查会跳过，修完再验一次，见 `flows.md` 第 2 节。）

### 3.2 执行

节点执行失败返回 `200` + `ok:false`，`errors[0]` 是「节点 `<id>`（`plugin.Component`）执行失败：<原因>」，`nodes` 里只有跑过的节点和失败节点（失败节点 `error` 字段非空）。

常见原因：

| 报错片段 | 原因 | 改法 |
|---|---|---|
| `No such file or directory: 'missing.csv'` | 路径相对**项目根**解析，文件不在项目里 | 用 `POST /api/file` 把文件写进项目根（组件在服务端解析相对路径） |
| `列不存在：['x']（可用：['a', 'b']）` | `SelectColumns`/`FilterRows` 里的列名和数据不符 | 先 `GET /api/file` 看表头 |
| `原因` 是组件抛出的校验文案（引擎只取 `str(exc)`，**没有 `ValueError:` 前缀**） | 组件自身校验失败（配置与数据不匹配） | 看组件 `desc`，按报错改参数 |
| `模型插件版本不匹配：该文件由 ml v1.0 保存，当前 ml v2.0；请用当前版本重新训练并保存` | `LoadModel` 读的是别的插件版本存的模型 | 用当前版本重新训练并保存 |

执行是顺序的：失败节点之后的节点不会执行，也不会出现在 `nodes` 里。

### 3.3 文件与路径

| 文案 | 改法 |
|---|---|
| `路径不能包含 ..：'../escape.txt'` | 只用项目内相对路径 |
| `路径必须是项目内相对路径：'/etc/passwd'` | 去掉开头 `/` 或盘符 |
| `父目录不存在：flows` | 先 `POST /api/mkdir {"path":"flows"}` |
| `已存在：flows` | `mkdir` 前先 `GET /api/tree` |
| `不是文件：nope` | 路径是目录或不存在 |
| `不是目录：nope` | `tree` 的 `path` 指向文件 |
| `目录不为空，不能删除：sub` | 先删里面的条目 |
| `目标是目录，不能写入：sub` | `POST /api/file` 的 `path` 指向了目录 |
| `名字是 Windows 保留名：'aux.log'` | 新建/改名用了 `CON`/`PRN`/`AUX`/`NUL`/`COM1-9`/`LPT1-9`（带扩展名也算，如 `aux.log`） | 换一个名字；`mkdir`、`rename` 的 `new_name` 同样受限 |

所有路径都锁在项目根内：绝对路径、盘符、`..`、符号链接绕行都会被拒。

### 3.4 项目与会话

| 文案 | 场景 | 改法 |
|---|---|---|
| `项目未运行：D:\work\demo` | close/restart 传了没打开的项目 | 先 `POST /api/projects`；`root` 用绝对目录，不是 `url` |
| `插件名重复：table（D:\workflow-studio\plugins\table 与 D:\work\demo\plugins\table）` | 全局与项目插件根（或两个 `-p` 目录）出现同名插件目录，加载硬报错：`/api/project` 回 `ok:false`、`errors` 带两个绝对路径，`health` 插件数归零，但文件接口照常可用 | 删掉或改名其中一个目录，再 `POST /api/projects/restart` |
| `端口被占用，重启失败` | 旧进程端口没释放又被别人抢走 | 再试一次 restart；仍失败就 `POST /api/projects/close` 后重新 `POST /api/projects`（会分配新的随机端口；`restart` 没有换端口参数） |
| `未知调试会话：nope` | `debug/stop` 的 `session` 不对 | 用 `debug/start` 返回的 `session` |
| `调试子进程提前退出（exit code 1）` | 工作流不合法，或钩子依赖缺失（例如没装 `websockets`——它在 import 阶段就报 `HookError` 退出，不会等到 10 秒） | 看 `errors` 后几条 stderr；先用 `/api/validate` 验一遍；缺依赖就装 `requirements.txt` |
| `调试子进程 10 秒内没有写出端口文件` | 机器慢、插件加载慢，或端口文件写入失败 | 重试一次；看 stderr 尾部；确认系统临时目录可写、没有被安全软件拦截 |

**插件根下的 `*.zip`（不是错误，也不进 `skipped`）**：引擎只扫插件根下的**子目录**，zip 与其它文件一律忽略、不报错、不出现在 `skipped` 里。装第三方插件：把 zip 解压成**同名目录**放进插件根（目录名必须等于 `PLUGIN_NAME`），再 `POST /api/projects/restart`；改目录里的代码同样只能 restart 生效（不能热加载）。进 `skipped` 的只有两类：没有 `components.py` 的子目录，以及宽容模式下加载失败的插件（缺依赖、缺 `__init__.py`、import 报错等，各带自己的原因）。

---

## 4. 连不上服务

| 现象 | 原因 | 处理 |
|---|---|---|
| `ConnectionRefusedError` | launcher 没起，或端口不对 | `python -m studio --port 8765`；确认端口 |
| 项目服务连不上 | 项目已关闭或子进程崩了 | `GET /api/projects` 看是否还在；不在就重新 `POST /api/projects` |
| launcher 起了但项目打不开 | 返回 `ok:false` + 子进程日志尾部 | 读 `errors[1:]`，通常是项目根不存在或插件加载失败 |
| 请求超时 | `/api/run` 正在跑长任务（同步、无进度） | 等；不要重复提交（会排队） |
| 每个响应后连接就关闭 | 服务按 HTTP/1.0 回包，没有 keep-alive，一次请求一条连接 | 正常现象：每次请求新建连接，不要复用 |
| `/api/run` 跑得比 30 秒久 | `timeout=30` 只是该连接的 socket 读写超时，**不是任务超时** | 长任务照常等它跑完；不要按 30 秒去重试 |

---

## 5. 服务不可用时的 CLI（仅排障；智能体默认走 HTTP）

> HTTP 服务能起来时，一律用接口排查。CLI 只用于 launcher 起不来、端口被占、没有常驻进程的离线场景。
> 注意 CLI 的插件集合与工作目录可能和服务端不同（见 `api.md` 第 3 节），CLI 通过不代表 `/api/run` 通过。

`python -m engine validate|run` 的错误走 stderr，退出码 `1`：

```text
[错误] nodes[0]（x）: 组件 nope.Nope 不存在
[校验失败] 共 1 条错误
```

```text
[执行失败] 节点 load（fileio.LoadCSV）执行失败：…
```

```text
[读取失败] two_nodes.flow 不是合法 JSON：Expecting property name enclosed in double quotes
```

```text
[钩子错误] <钩子目录>：install() 失败：http_debug 钩子必须用 -e hook_token=<token> 指定访问口令
```

区别：命令行失败是**进程退出码**，HTTP 失败是**状态码 + `ok`**；错误文案一致，但插件集合与工作目录可能不同，**CLI 通过不等于 `/api/run` 通过**，不要拿 CLI 结果替代接口结论。

---

## 6. 排查顺序（照这个走）

1. `GET launcher /api/health` 通不通 → 不通先起 launcher。
2. `GET launcher /api/projects` 里有没有目标项目 → 没有就 `POST /api/projects`。
3. `GET <project.url>/api/health` → `plugins` 为 0 说明插件加载失败，看 `/api/project` 的 `errors`。
4. `GET /api/plugins` 里有没有你用的 `plugin` + `component` → 没有就是名字错或插件没进 `plugins/`。
5. `POST /api/validate` 拿全量错误 → 按第 3 节逐条改。
6. 校验过了再 `POST /api/run`；节点失败看 `nodes[].error`。
7. 改过 `plugins/<插件名>/` → `POST /api/projects/restart` 再试（否则仍是旧代码）。

---

## 7. 安全边界与禁区（不是错误，但别踩）

- **只走 Studio HTTP 接口**：项目内文件的读、写、查、删、改名一律走接口，不要用 `read`/`write`/shell 直接改盘（绕过路径锁与原子写）。
- 服务无认证、只绑 `127.0.0.1`；不要用反向代理把它暴露出去。
- `Host` 白名单挡住了 DNS rebinding，但也意味着**不能用容器别名/别的 IP 访问**。
- `/api/run` 会真的执行节点：`SaveCSV` 会覆盖同名文件，`LoadModel` 会反序列化文件（可能执行代码）。只跑可信工作流。
- `/api/delete` 删除文件或空目录（目录非空回 `ok:false`）；删除不可恢复。
- 项目路径被锁在项目根内，越界一律业务失败。
- **不要改产品代码**（`engine/`、`studio/`、`frontend/`、`plugins/`、`tests/`）；发布、提交、打 tag 不在这个 skill 的职责内。
