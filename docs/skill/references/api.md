# workflow-studio API 参考

> **读这份文件的时机**：已经确定要调接口（打开项目、读插件、读写文件、校验、执行、重启、调试），需要一个字段一个字段地照抄请求与判断响应时。

本文所有请求都真起服务跑过，响应为准。**端口、pid、耗时、token、session 每次运行都不同**，文中已换成中性示例值（`D:\work\demo`、`51234`、`4321`）；字段名、层级、类型与真实响应一致。`engine` / 插件版本号随发版变化。

---

## 0. 通用约定

### 0.1 两个进程、两个 base URL

| 进程 | 启动 | 地址 | 管什么 |
|---|---|---|---|
| launcher | `python -m studio --port 8765` | `http://127.0.0.1:8765`（默认固定端口） | 打开/关闭/重启项目、浏览服务端目录、落地页 |
| 项目服务 | launcher 自动拉起 `python -m studio --serve <项目根> --port 0` | `http://127.0.0.1:<随机端口>`，端口由 launcher 告诉你在响应里的 `project.url` | 项目内文件读写、插件、校验、执行、调试 |

只监听 `127.0.0.1`，**没有认证**。不要把它暴露到网络上。

### 0.2 请求头约束（硬性）

两个服务都校验 `Host`：必须等于 `127.0.0.1:<本服务端口>` 或 `localhost:<本服务端口>`，否则

```http
HTTP/1.0 403 Forbidden
{"ok": false, "errors": ["Host 不被允许：'example.com'"]}
```

POST 若带 `Origin`，必须与 Host 同源（`http://127.0.0.1:<端口>` 或 `http://localhost:<端口>`），否则同样 403 `Origin 不被允许：…`。命令行客户端不自动带 Origin，不受影响。

### 0.3 请求体

- 只收 JSON 对象；解析不出对象就 `400 {"ok":false,"errors":["请求体不是合法 JSON"]}`。
- 上限：项目服务 16 MiB，launcher 1 MiB；超过是 `413`。
- 不检查 `Content-Type`，但建议 `application/json`。
- 项目内路径一律**正斜杠相对路径**（`data/x.csv`），禁止绝对路径、盘符、`..`；写入要求父目录已存在。
- Windows 的 `cmd` 里 `curl` **不认单引号**：`-d '{...}'` 会把单引号原样送进 body，得到上面的 `请求体不是合法 JSON`。改用双引号并转义内层引号，或直接跑 `examples/client.py`（推荐）。

### 0.4 两种失败，别混

**HTTP 层失败**（`4xx/5xx`）：请求本身不合法或服务器出错。

```json
{"ok": false, "errors": ["缺少 path 查询参数"]}
```

**业务层失败**（`HTTP 200` + `ok:false`）：请求合法，但校验不通过、执行失败、路径越界、项目未运行。

```json
{"ok": false, "errors": ["不是目录：nope"]}
```

判断顺序永远是：先看 HTTP 状态码，再看 `ok`，最后看 `errors` 文案。**只看状态码会把业务失败当成功。**

**例外——未实现的方法**：`PUT /api/file` 这类请求由传输层直接回 **501 + HTML**（`<html>…Unsupported method ('PUT')…`），不是上面的 JSON 信封。所以：先按状态码判断，**不要对非 200 响应无条件 `json.loads`**。

### 0.5 同步/异步与副作用

| 接口 | 同步 | 副作用 |
|---|---|---|
| 全部 GET | 同步 | 无 |
| `POST /api/validate` | 同步、纯函数 | 无 |
| `POST /api/run` | **同步阻塞**到全部节点执行完 | 执行节点（可能写文件、写模型），临时改环境变量后恢复 |
| `POST /api/file` 等 | 同步 | 落盘 |
| `POST /api/debug/start` | 同步等子进程就绪（最长 10 秒） | 起调试子进程 |
| `POST /api/projects/restart` | 同步等新子进程就绪 | 杀掉旧进程、起新进程 |

`/api/run` **没有取消接口、没有进度推送**；长任务期间它独占执行锁（同一服务上第二个 `/api/run` 排队），其他接口照常响应。

---

## 1. launcher：5 条路径 / 6 个操作

### GET /api/health

存活探测。无副作用。

```http
GET http://127.0.0.1:8765/api/health
```

```json
{"ok": true}
```

### GET /api/projects

列出当前由本 launcher 管理的项目。

```http
GET http://127.0.0.1:8765/api/projects
```

```json
{
  "ok": true,
  "errors": [],
  "projects": [
    {
      "root": "D:\\work\\demo",
      "name": "demo",
      "port": 51234,
      "pid": 4321,
      "url": "http://127.0.0.1:51234"
    }
  ]
}
```

`projects` 里只会有启动成功、还在跑的项目；已退出的会被自动清理。

### POST /api/projects

打开项目：目录存在则由 launcher 拉起一个项目服务子进程。

```http
POST http://127.0.0.1:8765/api/projects
Content-Type: application/json

{"path": "D:\\work\\demo"}
```

```json
{
  "ok": true,
  "errors": [],
  "project": {
    "root": "D:\\work\\demo",
    "name": "demo",
    "port": 51234,
    "pid": 4321,
    "url": "http://127.0.0.1:51234"
  }
}
```

- **幂等**：同一目录再次打开返回同一个 `port` / `pid`，不会起第二个进程。
- **已知限制**：没有创建项目根目录的接口，`path` 必须指向**已存在**的目录；不存在的路径立刻 `400`。
- 目录不存在：`400` + `{"ok":false,"errors":["目录不存在或不是目录：D:\\nope"]}`。拿到这条不要自己造目录：把原文给用户，请他提供或创建一个已存在的目录（项目内子目录仍用 `POST /api/mkdir`）。
- 子进程起不来：`200` + `ok:false`，`errors` 第一条是原因，后面附子进程日志尾部。

### GET /api/fs/dirs

浏览服务端目录，只回子目录（不含文件）。项目外也能用，`path` 可空。

```http
GET http://127.0.0.1:8765/api/fs/dirs
```

```json
{
  "ok": true,
  "errors": [],
  "path": "",
  "parent": null,
  "entries": [
    {"name": "C:", "path": "C:\\"},
    {"name": "D:", "path": "D:\\"}
  ]
}
```

带 `path` 时（`?path=D:\\work\\demo`）：

```json
{
  "ok": true,
  "errors": [],
  "path": "D:\\work\\demo",
  "parent": "D:\\work",
  "entries": [{"name": "sub", "path": "D:\\work\\demo\\sub"}]
}
```

- Windows 上不带 `path` 回盘符；非 Windows 回 `/` 的子目录。
- 路径不是目录：`400` + `{"ok":false,"errors":["目录不存在或不是目录：…"]}`。返回的 `path` 是**原样回显传入值**：传绝对路径回绝对路径，传相对路径回相对路径，调用方自己决定要不要给模型看。

### POST /api/projects/close

关闭项目子进程。

```http
POST http://127.0.0.1:8765/api/projects/close
Content-Type: application/json

{"root": "D:\\work\\demo"}
```

```json
{"ok": true, "errors": []}
```

传的是**项目根**，不是 `url`。未运行：`200` + `{"ok":false,"errors":["项目未运行：D:\\work\\demo"]}`。

### POST /api/projects/restart

重启项目进程：同一个端口、新的 pid。**插件 zip 改动后必须走这里**（见 `SKILL.md` 五步闭环第 5 步）。

```http
POST http://127.0.0.1:8765/api/projects/restart
Content-Type: application/json

{"root": "D:\\work\\demo"}
```

```json
{
  "ok": true,
  "errors": [],
  "project": {"root": "D:\\work\\demo", "name": "demo", "port": 51234, "pid": 4302, "url": "http://127.0.0.1:51234"}
}
```

- 端口保持不变，`pid` 变化；旧进程先停再起。
- 未运行：`200` + `{"ok":false,"errors":["项目未运行：…"],"project":null}`。
- 端口被别的进程抢走：`200` + `{"ok":false,"errors":["端口被占用，重启失败"],"project":null}`。

---

## 2. 项目服务：13 条路径 / 14 个操作

以下 `BASE` 指 `project.url`，例如 `http://127.0.0.1:51234`。

### GET /api/health

引擎版本与插件/组件数量（版本号为示例，随发版变化）。

```http
GET http://127.0.0.1:51234/api/health
```

```json
{"ok": true, "engine": "0.7.1", "plugins": 6, "components": 27}
```

### GET /api/plugins

**接线的唯一事实来源**：插件、类型、组件、端口 schema、参数 schema。

```http
GET http://127.0.0.1:51234/api/plugins
```

```json
{
  "plugins": [
    {
      "name": "std",
      "version": "1.0",
      "title": "标准类型",
      "types": [
        {"id": "std_1.0@table", "desc": "表格数据（pandas.DataFrame）"},
        {"id": "std_1.0@number", "desc": "数值（int 或 float）"},
        {"id": "std_1.0@string", "desc": "字符串"},
        {"id": "std_1.0@boolean", "desc": "布尔值"},
        {"id": "std_1.0@model", "desc": "预测模型，载体必须继承 PredictorModel 并实现 predict(frame)"}
      ],
      "components": []
    },
    {
      "name": "fileio",
      "version": "1.0",
      "title": "数据读写",
      "types": [],
      "components": [
        {
          "name": "LoadCSV",
          "title": "读取 CSV",
          "desc": "读取 CSV 文件并转成表格，可切换编码",
          "config_schema": {
            "path": {
              "type": "string",
              "title": "文件路径",
              "desc": "绝对路径优先；也可写相对路径，按进程工作目录解析，支持 ${变量}",
              "required": true
            },
            "encoding": {
              "type": "enum",
              "title": "编码",
              "desc": "Windows 上中文 CSV 常是 GBK，读出来乱码就换这个",
              "default": "utf-8",
              "choices": [
                {"value": "utf-8", "label": "UTF-8"},
                {"value": "gbk", "label": "GBK"}
              ]
            },
            "sep": {"type": "string", "title": "分隔符", "desc": "默认逗号", "default": ","},
            "header": {"type": "boolean", "title": "首行为表头", "desc": "关闭时列名是 0、1、2…", "default": true}
          },
          "input_schema": {},
          "output_schema": {
            "table": {"type": "std_1.0@table", "type_label": "std@table", "title": "数据表", "desc": ""}
          }
        }
      ]
    }
  ]
}
```

字段含义：

- `plugins[].name` → 写进节点 `plugin` 的值（短名，**不带版本**）。
- `plugins[].types[].id` → 完整类型标识 `插件名_版本@类型名`；接线时比对的就是它。
- `components[].input_schema.<端口>.types` → 该输入端口接受的类型集合；`required` 决定是否必须接线。
- `components[].output_schema.<端口>.type` → 该输出端口产出的类型。
- `type_labels` / `type_label` → 给人看的短名（`std@table`），接线判断用完整 `type`，不要用 label。
- `config_schema` → 造 `config` 的依据，见 `references/flows.md`。

### GET /api/project

当前项目根与插件加载概况。

```http
GET http://127.0.0.1:51234/api/project
```

```json
{
  "ok": true,
  "root": "D:\\work\\demo",
  "name": "demo",
  "launcher": "http://127.0.0.1:8765",
  "plugins": {"global": 5, "project": 0},
  "skipped": [],
  "errors": []
}
```

- `plugins.global`：来自引擎自带 `plugins/`；`plugins.project`：来自本项目根下 `plugins/`。
- `skipped`：坏 zip 被跳过时是 `[{"file": "...", "path": "...", "reason": "...", "source": "global"|"project"}]`。
- 插件加载失败时 `ok:false` 且 `errors` 非空（此时健康接口的 `plugins` 为 0）。

### GET /api/tree

列项目内**一层**目录。

```http
GET http://127.0.0.1:51234/api/tree?path=
```

```json
{
  "ok": true,
  "path": "",
  "entries": [
    {"name": "data.csv", "path": "data.csv", "kind": "file", "size": 15},
    {"name": "flows", "path": "flows", "kind": "dir"}
  ],
  "errors": []
}
```

- 目录在前、文件在后，各按名字不区分大小写排序。
- `size` 只有 `kind=file` 时出现。
- 不是目录：`200` + `{"ok":false,"errors":["不是目录：nope"]}`。

### GET /api/file

读项目内文本文件。

```http
GET http://127.0.0.1:51234/api/file?path=data.csv
```

```json
{
  "ok": true,
  "path": "data.csv",
  "kind": "text",
  "size": 15,
  "text": "a,b\r\n1,2\r\n3,4\r\n",
  "errors": []
}
```

- `kind` 三种：`text`（有 `text`）、`binary`（含 NUL 或非 UTF-8）、`too_large`（>1 MiB）。后两种 `text` 为 `null`。
- 不是文件：`200` + `{"ok":false,"errors":["不是文件：nope"]}`。
- 缺 `path` 参数：`400`。

### GET /api/stat

只查文件版本信息，**不读内容**；用来判断文件是否存在、是否被改过。

```http
GET http://127.0.0.1:51234/api/stat?path=data.csv
```

```json
{
  "ok": true,
  "path": "data.csv",
  "kind": "file",
  "size": 15,
  "mtime_ns": 1795689807077378000,
  "errors": []
}
```

- `kind` 三种：`file`（有 `size`/`mtime_ns`）、`dir`、`missing`。后两种 `size` 与 `mtime_ns` 都是 `null`。
- 不存在不算业务失败：`ok:true` + `kind:"missing"`。
- 路径越界仍是业务失败：`200` + `{"ok":false,"errors":["路径不能包含 ..：'../x'"]}`。
- 缺 `path` 参数：`400`。

**改文件前先 stat，确认没被外部改动**（推荐动作）：

1. `GET /api/stat?path=flows/demo.flow`，记下**旧** `mtime_ns`（`kind:"missing"` 表示文件还不存在，旧值按空处理）。
2. `GET /api/file?path=flows/demo.flow` 读全文，改 JSON。
3. **写之前再 `GET /api/stat` 一次**：与第 1 步的旧值**相同**才 `POST /api/file`；不同说明期间被编辑器/别的客户端改过，**重新读一遍再改**。
4. `POST /api/file` 返回的 `mtime_ns` 是**本次写入后的新版本**，留作下一次比对的基准——不要拿它和写前的旧值比，那必然不相等。

### POST /api/file

新建或**整文件覆盖**写文本。**没有节点级 patch、没有局部编辑接口**——改 flow 必须 GET 全文、改完整体 POST 回来。

```http
POST http://127.0.0.1:51234/api/file
Content-Type: application/json

{"path": "flows/minimal.flow", "text": "{\n  \"name\": \"最小示例\"\n}"}
```

```json
{"ok": true, "path": "flows/minimal.flow", "size": 28, "mtime_ns": 1795689807077378000, "errors": []}
```

- `mtime_ns` 是**本次写入后的新版本**：写前那次 `GET /api/stat` 的旧值用于比对，写入返回的这个值留作下一次的基准。

- UTF-8 落盘（无 BOM），先写同目录临时文件再原子替换；不会出现半个文件。
- 父目录不存在：`200` + `{"ok":false,"errors":["父目录不存在：flows"]}`（先 `POST /api/mkdir`）。
- 路径含 `..` 或绝对路径：`200` + `{"ok":false,"errors":["路径不能包含 ..：'../x.txt'"]}`。
- 请求体缺 `text` 字符串：`400 {"ok":false,"errors":["请求体缺少 text 字符串"]}`。

### POST /api/mkdir

新建目录（父目录必须已存在）。

```http
POST http://127.0.0.1:51234/api/mkdir

{"path": "flows"}
```

```json
{"ok": true, "path": "flows", "errors": []}
```

已存在：`200` + `{"ok":false,"errors":["已存在：flows"]}`。

### POST /api/rename

同目录内重命名文件或目录。

```http
POST http://127.0.0.1:51234/api/rename

{"path": "flows/old.flow", "new_name": "new.flow"}
```

```json
{"ok": true, "path": "flows/new.flow", "errors": []}
```

- `new_name` 只能是单段名字（不含 `/`、`\`），Windows 非法字符/保留名会被拒：`200` + `ok:false`。
- 目标已存在：`200` + `{"ok":false,"errors":["目标已存在：flows/new.flow"]}`。

### POST /api/delete

删除文件或**空**目录。

```http
POST http://127.0.0.1:51234/api/delete

{"path": "flows/old.flow"}
```

```json
{"ok": true, "path": "flows/old.flow", "errors": []}
```

目录非空：`200` + `{"ok":false,"errors":["目录不为空，不能删除：flows"]}`。

### POST /api/validate

只校验，不执行，无副作用。

```http
POST http://127.0.0.1:51234/api/validate
Content-Type: application/json

{"workflow": {"name": "最小示例：读取 CSV", "nodes": [{"id": "load", "plugin": "fileio", "component": "LoadCSV", "config": {"path": "data.csv"}}]}}
```

成功：

```json
{
  "ok": true,
  "errors": [],
  "warnings": ["节点 load 是孤立节点（既没有输入也没有下游）"],
  "order": ["load"]
}
```

失败（`ok:false` 时 `order` 为空数组）：

```json
{
  "ok": false,
  "errors": ["nodes[0]（x）: 组件 nope.Nope 不存在"],
  "warnings": [],
  "order": []
}
```

- `warnings` 不影响 `ok`（孤立节点只是提示）。
- 校验器**一次报全部错误**，不是遇到第一个就停。
- 缺 `workflow` 对象：`400 {"ok":false,"errors":["请求体缺少 workflow 对象"]}`。

### POST /api/run

校验并执行，同步返回**每个节点的实际输出预览**。这是智能体的首选执行入口。

```http
POST http://127.0.0.1:51234/api/run
Content-Type: application/json

{"workflow": {"name": "两节点：读取 CSV 后选列", "env": {"INPUT": "data.csv"}, "nodes": [{"id": "load", "plugin": "fileio", "component": "LoadCSV", "config": {"path": "${INPUT}", "encoding": "utf-8", "sep": ",", "header": true}}, {"id": "select", "plugin": "table", "component": "SelectColumns", "config": {"columns": ["a"], "strict": true}, "inputs": {"data": {"from": "load", "port": "table"}}}]}}
```

成功：

```json
{
  "ok": true,
  "errors": [],
  "warnings": [],
  "order": ["load", "select"],
  "nodes": [
    {
      "id": "load",
      "component": "fileio.LoadCSV",
      "ms": 960.04,
      "outputs": {"table": "DataFrame 2 行 × 2 列 ['a', 'b']\n   a  b\n0  1  2\n1  3  4"},
      "error": null
    },
    {
      "id": "select",
      "component": "table.SelectColumns",
      "ms": 0.73,
      "outputs": {"table": "DataFrame 2 行 × 1 列 ['a']\n   a\n0  1\n1  3"},
      "error": null
    }
  ]
}
```

节点执行失败（`HTTP 200`，`ok:false`；失败节点带 `error`，之后的节点不出现）：

```json
{
  "ok": false,
  "errors": ["节点 load（fileio.LoadCSV）执行失败：[Errno 2] No such file or directory: 'missing.csv'"],
  "warnings": ["节点 load 是孤立节点（既没有输入也没有下游）"],
  "order": ["load"],
  "nodes": [
    {
      "id": "load",
      "component": "fileio.LoadCSV",
      "ms": 0.0,
      "outputs": {},
      "error": "节点 load（fileio.LoadCSV）执行失败：[Errno 2] No such file or directory: 'missing.csv'"
    }
  ]
}
```

校验不通过时：`ok:false`，`errors` 是校验错误，`nodes` 为 `[]`。

```json
{
  "ok": false,
  "errors": ["nodes 必须是非空数组"],
  "warnings": [],
  "order": [],
  "nodes": []
}
```

- `outputs` 是**预览字符串**，不是原始对象；要看完整内容让节点把结果写文件（`SaveCSV`）再用 `GET /api/file` 读。
- `ms` 每个节点耗时，随机器变化。
- 工作流 `env` 会临时写进进程环境变量，执行完恢复；相对路径按**项目根**解析。
- 执行期间占执行锁；没有取消接口。

### POST /api/debug/start

起调试子进程：执行交给 `python -m engine run --hook hooks/http_debug`，由它开 WebSocket。给**交互式前端**用；批量跑用 `/api/run`。

```http
POST http://127.0.0.1:51234/api/debug/start
Content-Type: application/json

{"workflow": {"name": "两节点：读取 CSV 后选列", "nodes": [ ... ]}}
```

```json
{
  "ok": true,
  "session": "624c0bf80e29433ea97a216cd00aa0f0",
  "port": 65429,
  "token": "H75e5zjvPgcJumRB_FFHTA"
}
```

- 调试子进程**不会自动跑节点**，连上后发命令驱动（见第 4 节）。
- 同一时刻只有一个会话；新的 `start` 会先关掉旧的。
- 工作流不合法：`200` + `ok:false`，`errors` 首条是「调试子进程提前退出（exit code 1）」，后面是 stderr 尾部：

```json
{
  "ok": false,
  "errors": [
    "调试子进程提前退出（exit code 1）",
    "[错误] nodes[0]（x）: 组件 nope.Nope 不存在",
    "[校验失败] 共 1 条错误"
  ]
}
```

### POST /api/debug/stop

```http
POST http://127.0.0.1:51234/api/debug/stop

{"session": "624c0bf80e29433ea97a216cd00aa0f0"}
```

```json
{"ok": true}
```

未知 session：`200` + `{"ok":false,"errors":["未知调试会话：nope"]}`。

---

## 3. engine CLI（降级运维：服务不可用或 CI 自检时才用）

> **读这节的前提**：HTTP 服务不可用（launcher 起不来、端口被占、CI 里没有常驻进程）时，用 CLI 做离线校验与排查。
> 智能体的默认路径**只有 HTTP**：`/api/validate`、`/api/run`。不要把 CLI 当常规执行通道——两者上下文不同，结论可能不一致。

手工跑 CLI 与 Studio 的差异：

- **插件集合**：CLI 默认只扫工程 `plugins/`（再加 `-p` 指定的目录）；项目服务加载的是引擎内置插件 + 项目根下 `plugins/`。同一份 flow 可能一边能跑、一边报「组件不存在」。
- **工作目录**：CLI 的相对路径按**当前 shell 目录**解析；Studio 按**项目根**解析。
- **环境变量**：CLI 的 `-e` 只对本次进程生效；`/api/run` 会在执行期间临时注入 flow 的 `env`，执行完恢复。
- **失败口径**：CLI 是**进程退出码 1**，HTTP 是**状态码 + `ok`**；文案一致，但判断方式不要混。

通用参数（写在子命令前或后都行）：

| 参数 | 作用 |
|---|---|
| `-p, --plugins-dir DIR` | 插件 zip 目录，可重复；默认工程 `plugins/` |
| `-e, --env KEY=VALUE` | 设环境变量，可重复；在流程 `env` 之后覆盖，只对 `run` 生效 |
| `--hook PATH` | 执行钩子（目录或 `.py`），最多一个，只对 `run` 生效 |

### 列插件

```bash
python -m engine plugins
```

```text
std  v1.0  标准类型
  zip : <builtin>
  类型 : std_1.0@table  —— 表格数据（pandas.DataFrame）
  ...
fileio  v1.0  数据读写
  zip : <插件目录>/fileio.zip
  组件 : LoadCSV  读取 CSV
         读取 CSV 文件并转成表格，可切换编码
         出 table: std@table
```

### 校验

```bash
python -m engine validate two_nodes.flow
```

```text
[校验通过] 两节点：读取 CSV 后选列，2 个节点
执行顺序：load -> select
```

有警告时：

```text
[警告] 节点 load 是孤立节点（既没有输入也没有下游）
[校验通过] 最小示例：读取 CSV，1 个节点
执行顺序：load
```

失败时错误走 stderr，退出码 1：

```text
[错误] nodes[0]（x）: 组件 nope.Nope 不存在
[校验失败] 共 1 条错误
```

### 执行

```bash
python -m engine run two_nodes.flow
```

```text
[开始执行] 两节点：读取 CSV 后选列，2 个节点

[load] fileio.LoadCSV  585.1 ms
  table -> DataFrame 2 行 × 2 列 ['a', 'b']
       a  b
    0  1  2
    1  3  4

[select] table.SelectColumns  0.5 ms
  table -> DataFrame 2 行 × 1 列 ['a']
       a
    0  1
    1  3

[完成] 共 2 个节点
```

退出码：`0` 成功；`1` 读取失败 / 校验失败 / 执行失败 / 钩子错误。相对路径按**当前目录**解析，不是按 flow 文件所在目录。

`--hook` 缺参数的真实报错：

```text
[钩子错误] <钩子目录>：install() 失败：http_debug 钩子必须用 -e hook_token=<token> 指定访问口令
```

调试钩子由 `/api/debug/start` 自动带齐 `-e hook_port / hook_port_file / hook_token`，一般不需要手起。

---

## 4. 调试 WebSocket（交互式前端用）

> 只用于逐步调试/看日志。批量执行请用 `/api/run`。

### 4.1 连接

`POST /api/debug/start` 返回 `port` 与 `token`，然后：

```text
ws://127.0.0.1:<port>/?token=<token>
```

- token 不对：握手 `403 bad token`；`Origin` 存在且不是 `http://127.0.0.1:<任意端口>` / `http://localhost:<任意端口>`：`403 bad origin`。
- 同一端口还接受 `POST /shutdown`（Studio 内部停会话用，返回 `200 bye`）。
- 所有命令与推送都是一行 JSON 对象。

### 4.2 五条命令

| 命令 | 请求 | 作用 | 备注 |
|---|---|---|---|
| `state` | `{"cmd":"state"}` | 取当前快照 | 只读，空闲可发 |
| `inspect` | `{"cmd":"inspect","id":"<节点id>"}` | 看某节点的上游输入与自身输出 | 只读，**不执行**，不占执行锁 |
| `run_node` | `{"cmd":"run_node","id":"<节点id>"}` | 只跑一个节点 | 节点必须在 `order` 里 |
| `continue` | `{"cmd":"continue"}` | 按顺序跑完剩下所有节点 | 跳过状态为 `fresh` 的节点 |
| `stop` | `{"cmd":"stop"}` | 请求中止 | 立即 `ack`；正在跑的节点不会被打断，当前位置停下 |

执行类命令（`run_node` / `continue`）执行中再发会得到 `{"type":"error","message":"正在执行"}`；`stop` 与 `inspect` 在任何时候都能发。

真实往返（请求 → 依序收到的推送）：

```json
{"cmd": "run_node", "id": "load"}
```
```json
{"type": "ack", "cmd": "run_node"}
{"type": "state", "data": {"phase": "running", "current": "load", "order": ["load", "select"], "nodes": {"load": {"status": "unrun", "duration_ms": null, "error": null, "outputs": {}}, "select": {"status": "unrun", "duration_ms": null, "error": null, "outputs": {}}}}}
{"type": "state", "data": {"phase": "running", "current": null, "order": ["load", "select"], "nodes": {"load": {"status": "fresh", "duration_ms": 880.5, "error": null, "outputs": {"table": "DataFrame 2 行 × 2 列 ['a', 'b']\n   a  b\n0  1  2\n1  3  4"}}, "select": {"status": "unrun", "duration_ms": null, "error": null, "outputs": {}}}}}
{"type": "state", "data": {"phase": "idle", "current": null, "order": ["load", "select"], "nodes": {"load": {"status": "fresh", "duration_ms": 880.5, "error": null, "outputs": {"table": "DataFrame 2 行 × 2 列 ['a', 'b']\n   a  b\n0  1  2\n1  3  4"}}, "select": {"status": "unrun", "duration_ms": null, "error": null, "outputs": {}}}}}
```

`inspect` 真实响应（`inputs` 来自上游已产出的值，上游没跑就是空）：

```json
{"cmd": "inspect", "id": "select"}
```
```json
{
  "type": "inspect",
  "data": {
    "node": "select",
    "inputs": {
      "data": "DataFrame shape=(2, 2)\n列：a int64，b int64\n前 20 行：\n   a  b\n0  1  2\n1  3  4\n…"
    },
    "outputs": {}
  }
}
```

`run_node` 传了不存在的节点：

```json
{"cmd": "run_node", "id": "nope"}
```
```json
{"type": "ack", "cmd": "run_node"}
{"type": "state", "data": {"phase": "running", "current": "nope", "…": "…"}}
{"type": "error", "message": "节点 nope 不存在"}
{"type": "state", "data": {"phase": "failed", "current": null, "…": "…"}}
```

未知命令 / 非法 JSON：

```json
{"type": "error", "message": "未知命令：'unknown_cmd'"}
{"type": "error", "message": "命令不是合法 JSON"}
```

### 4.3 五种推送

| `type` | 何时来 | 形状 |
|---|---|---|
| `ack` | 每次执行类命令（`run_node`/`continue`/`stop`）受理后 | `{"type":"ack","cmd":"<命令>"}` |
| `state` | 命令开始、每个节点结束、整轮结束 | `{"type":"state","data":{phase,current,order,nodes}}` |
| `log` | 节点往 stdout/stderr 写了内容 | `{"type":"log","node":"<节点id或null>","stream":"stdout"|"stderr","text":"<一行>"}` |
| `error` | 命令级错误（节点不存在、正在执行、非法命令等） | `{"type":"error","message":"<原因>"}` |
| `inspect` | 回应 `inspect` 命令 | `{"type":"inspect","data":{node,inputs,outputs}}` |

真实 `log` 推送（示例，版本号随发版变化）：

```json
{
  "type": "log",
  "node": "loadmodel",
  "stream": "stderr",
  "text": "[警告] 模型 model.joblib 由引擎 v0.0.1 保存，当前引擎 v0.7.1；继续加载，若预测结果异常请重新训练并保存"
}
```

### 4.4 state 的取值

- `phase`：`idle`（未开始/单节点跑完回到空闲）、`running`、`paused`（`stop` 之后，当前节点跑完即停）、`failed`（**命令级错误或节点执行失败**）、`ended`（所有节点都 `fresh`）。
- 节点 `status` 四种：
  - `unrun`：没跑过。
  - `fresh`：跑过且结果有效。
  - `stale`：跑过，但上游重跑过，结果已过期；`continue` 会重跑它。
  - `failed`：节点执行失败，同时该节点的 `nodes[].error` 非空。
- `inspect` 只把上游状态为 `fresh` 或 `stale` 的值当作可用输入。
- 节点 `outputs` 与 `/api/run` 的 `outputs` 同源，都是预览字符串。
- `current`：正在跑或即将跑的节点 id，空闲为 `null`。

每次推送都是**全量快照**，客户端不需要自己做增量合并。

---

## 5. 能力边界（接口做不到的事）

| 做不到 | 现状 | 正确的替代做法 |
|---|---|---|
| 节点级 / 局部编辑 flow | 只有整文件覆盖 | `GET /api/file` 取全文 → 改 JSON → `POST /api/file` 整份写回（保留 `addition`） |
| 取消一次 `/api/run` | 没有取消接口，同步跑完 | 等它结束；要逐步控制改用 `/api/debug/start` 起的 WS（`stop` 只停后续节点） |
| 跨目录移动文件 | `rename` 只能同目录改名 | `GET /api/file` 读 → `POST /api/file` 写新路径 → `POST /api/delete` 删旧文件 |
| 递归删除目录 | `/api/delete` 删文件或空目录，目录非空回 `ok:false` | 用 `GET /api/tree` 逐层清空，再删父目录 |
| 创建**项目根**目录 | 当前版本不提供；`POST /api/projects` 要求目录已存在 | 请用户准备一个空目录，或 `GET /api/fs/dirs` 选一个已有目录再打开（项目内子目录仍用 `POST /api/mkdir`） |
| 读二进制 / >1 MiB 文件 | 只回 `kind`（`binary`/`too_large`）与 `size`，`text` 为 `null` | 让流程用组件把结果缩成 CSV/文本再 `GET /api/file` 读；二进制内容不在本 skill 能力内 |
| 递归列目录 / 全文搜索 | `tree` 只列一层，没有搜索接口 | 逐层 `GET /api/tree`；搜索先 `GET /api/file` 读文本，在内存里找 |
| 免认证 / 远程访问 | 只绑 `127.0.0.1`、无认证、`Host` 白名单 | 只能本机调用；远程由用户在目标机起服务并自行转发（不在本 skill 范围） |
| 直接改插件 / 改产品代码 | 不在 skill 职责内 | 重新打包 `plugins/*.zip` 后 `POST /api/projects/restart`；改代码找维护者 |

---

## 6. 一页速查

```text
launcher
  GET  /api/health
  GET  /api/projects
  POST /api/projects            {"path": "<绝对目录>"}
  GET  /api/fs/dirs?path=
  POST /api/projects/close      {"root": "<绝对目录>"}
  POST /api/projects/restart    {"root": "<绝对目录>"}

项目服务（BASE = project.url）
  GET  /api/health
  GET  /api/plugins
  GET  /api/project
  GET  /api/tree?path=
  GET  /api/file?path=
  GET  /api/stat?path=
  POST /api/file                {"path": "...", "text": "..."}
  POST /api/mkdir               {"path": "..."}
  POST /api/rename              {"path": "...", "new_name": "..."}
  POST /api/delete              {"path": "..."}
  POST /api/validate            {"workflow": {...}}
  POST /api/run                 {"workflow": {...}}
  POST /api/debug/start         {"workflow": {...}}
  POST /api/debug/stop          {"session": "..."}

调试 WebSocket
  ws://127.0.0.1:<port>/?token=<token>
  命令：state / inspect / run_node / continue / stop
  推送：ack / state / log / error / inspect
```
