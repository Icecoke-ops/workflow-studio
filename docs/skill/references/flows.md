# flow 字段规则与接线

> **读这份文件的时机**：要新建或修改 `.flow`、需要从 `/api/plugins` 的 schema 造 `config` 或接 `inputs`、或者手里有一条校验错误不知道改哪个字段时。

`.flow` 只是后缀，内容是 JSON。本文就是这份 skill 包里字段规则的完整说明（包里不带仓库契约文档）；如果哪条与 `/api/validate` 的真实报错冲突，以报错为准并反馈给维护者。

---

## 1. 顶层对象

只允许四个字段，多一个就报错：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `name` | 否 | string | 显示名，缺省 `""` |
| `env` | 否 | object | 环境变量，值必须是字符串 |
| `nodes` | **是** | array | 非空；节点定义 |
| `addition` | 否 | 任意 | 编辑器私有块，引擎不解释（见第 5 节） |

```json
{
  "name": "两节点：读取 CSV 后选列",
  "env": {"INPUT": "data.csv"},
  "nodes": []
}
```

未知字段的真实报错：

```json
{"ok": false, "errors": ["工作流存在未知字段 ['foo']"], "warnings": [], "order": []}
```

---

## 2. 节点

只允许五个字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | **是** | 非空字符串，全局唯一；连线用 `from` 引用它 |
| `plugin` | **是** | 插件**短名**，取 `/api/plugins` 的 `plugins[].name`，不带版本 |
| `component` | **是** | 组件名，取同插件下 `components[].name` |
| `config` | 否 | 参数对象，按 `config_schema` 填；省略即全部用默认值 |
| `inputs` | 否 | 入端口连线，`{端口名: {"from": 节点id, "port": 上游输出端口}}` |

```json
{
  "id": "select",
  "plugin": "table",
  "component": "SelectColumns",
  "config": {"columns": ["a"], "strict": true},
  "inputs": {"data": {"from": "load", "port": "table"}}
}
```

`plugin` 写错（例如带版本 `fileio_1.0`）会得到 `组件 xxx.yyy 不存在`；先回 `/api/plugins` 抄名字。

**批内例外**：某个节点自身解析失败（`id` 缺失或重复）时，校验器会跳过它的组件/参数/端口检查，所以这些错误不会和「id 重复」同一批报出。看到 `id 重复` 时，改完 id 要**再验一次**，别以为只剩这一条。同理，节点数量对不上时，后面的连线/排序检查也会整体跳过。

节点里放编辑器字段（例如 `position`）会被拒：

```json
{"ok": false, "errors": ["nodes[0]: 未知字段 ['position']"], "warnings": [], "order": []}
```

---

## 3. `config`：照着 `config_schema` 造

`config_schema` 的每一项是一个参数描述，`type` 只有七种：

| type | 合法 JSON 值 | 示例 | 额外约束 |
|---|---|---|---|
| `string` | 字符串 | `"data.csv"` | 可带 `pattern`（正则，`re.search` 语义） |
| `integer` | 整数（不能是布尔） | `5` | `min` / `max` |
| `number` | 数值 | `0.5` | `min` / `max` |
| `boolean` | `true` / `false` | `true` | — |
| `enum` | `choices[].value` 之一 | `"utf-8"` | 值必须在候选项里 |
| `json` | 对象或数组 | `{"a": "b"}` | — |
| `array` | 数组 | `["a", "b"]` | `min` / `max` 限制**元素个数** |

造值规则：

1. `required: true` 且**没有** `default` 的参数必须写；否则：
   ```json
   {"ok": false, "errors": ["nodes[0]（load）.config.path: 缺少必填参数（文件路径）"]}
   ```
2. 有 `default` 的参数**可以不写**：引擎在校验后自动补默认值（补在内存里，不会回写文件）。
3. 不知道能写什么值时，先不发请求，用默认值；需要改再照 `type` + `choices` / `min` / `max` 改。
4. `step` 只给界面做步进提示，不影响校验。
5. 多写未知参数会被拒：
   ```json
   {"ok": false, "errors": ["nodes[0]（load）.config: 未知参数 ['bogus']"]}
   ```
6. 类型写错（例如把 `header` 写成字符串 `"yes"`）报 `需要布尔值，实际 str`。

字符串参数里可以用 `${NAME}` 引用环境变量，但**不是引擎统一展开**：只有 `config_schema` 描述里写了"支持 ${变量}"的组件才会展开（例如 `fileio` 的 `path`、`ml` 的模型路径）。其它组件里写 `${X}` 只会当字面量。

---

## 4. `inputs`：接线

形状固定为 `{入端口名: {"from": 来源节点 id, "port": 来源节点的输出端口}}`。没有边就是空对象或省略。

接线四步：

1. 在 `/api/plugins` 找到目标组件，看 `input_schema`：端口名 → `types`（接受的完整类型标识）与 `required`。
2. 找上游组件的 `output_schema`：端口名 → `type`。
3. **类型必须完全相等**：上游 `type` 必须是下游 `types` 里的某一项。`std@table` 这类短名只用于显示，不能拿来判断。
4. `required: true` 的输入端口必须接；`required: false` 可以不接。

错误对照（全部为真跑文案）：

缺少必填输入：

```json
{"ok": false, "errors": ["nodes（select）.inputs.data: 缺少必填输入（需要 std@table）"]}
```

类型不匹配：

```json
{"ok": false, "errors": ["nodes（save）.inputs.data: 类型不匹配，来源输出 std@model，本端口需要 std@table"]}
```

端口不存在：

```json
{"ok": false, "errors": ["nodes[0]（z）.inputs.nope: 组件没有这个输入端口（可用：无）"]}
```

来源节点不存在 / 上游没有这个输出端口，分别报 `来源节点 xxx 不存在` 与 `来源节点 xxx 没有输出端口 y（可用：[...]）`。

图规则：

- 必须无环，否则 `工作流存在环，这些节点无法排序：['a', 'b']`。
- 执行顺序由引擎拓扑排序得出，`validate` / `run` 的 `order` 就是它；不要自己猜。
- 既没有输入也没有下游的节点只是**警告**，不算失败：
  ```json
  {"ok": true, "errors": [], "warnings": ["节点 load 是孤立节点（既没有输入也没有下游）"], "order": ["load"]}
  ```

---

## 5. `env` 与 `${NAME}`

```json
{"env": {"INPUT": "data.csv", "N": "10"}}
```

- 变量名必须匹配 `^[A-Za-z_][A-Za-z0-9_]*$`；写错报 `env 变量名不合法：'1X'`。
- 值**必须是字符串**（`"10"` 不是 `10`）。
- 生效范围：只在本次 `run` / 调试执行期间注入进程环境变量，执行完恢复；`validate` 不执行、不注入。
- 覆盖顺序：工作流 `env` < 命令行 `-e KEY=VALUE`（命令行最后覆盖）。
- 组件用 `${NAME}` 取值；引用了未定义变量会抛错，不会静默保留原文。

---

## 6. `addition`：编辑器私有块

**引擎只承认它存在，不解释、不校验、不修改**；放对象、字符串、数字都不影响校验与执行。

```json
"addition": {
  "client": "workflow-studio",
  "version": 1,
  "positions": {"load": {"x": 80, "y": 120}, "select": {"x": 420, "y": 120}},
  "groups": [
    {"id": "g1", "title": "读取与选列", "collapsed": false, "members": ["load", "select"]}
  ]
}
```

约定（只对 `workflow-studio` 编辑器有意义）：

- `client` 必须是 `workflow-studio`，`version` 是整数格式版本；别人写的或高版本会被编辑器整块忽略并提示，**不会拒绝加载**。
- `positions`：`{节点 id: {x, y}}`。
- `groups`：`{id, title, collapsed, members, position?}`；`members` 可放节点 id，也可放另一个组 id（子图为嵌套）。
- 智能体不需要生成它；要保留用户布局时**原样读回再原样写回**，不要重新算坐标。

---

## 7. 从 `/api/plugins` 造一条 flow 的标准动作

1. `GET /api/plugins`，拿到 `plugins[]`。
2. 按 `title` / `desc` 选组件，记下 `plugins[].name` 与 `components[].name`。
3. 从 `config_schema` 取：`required` 无 `default` 的参数必须给值；有 `default` 的可以先省略。
4. 从 `input_schema` / `output_schema` 决定谁接谁：上游输出 `type` ∈ 下游输入 `types`。
5. `POST /api/validate`；按 `errors` 逐条改，直到 `ok:true`。
6. `POST /api/run`；看每个节点的 `outputs` 预览确认结果。
7. 要落盘就在流程末尾加 `SaveCSV` / `SaveExcel` / `SaveModel`，再用 `GET /api/file` 读结果。

第 3、4 步不要凭记忆写：组件会随插件版本变化，`/api/plugins` 才是当前真相。

---

## 8. 三个样例文件

| 文件 | 演示什么 | 校验结果（真跑） |
|---|---|---|
| `flows/minimal.flow` | 单节点、只有必填 `config` | `ok:true` + 孤立节点警告 |
| `flows/two_nodes.flow` | `env` + `${INPUT}` + 一条连线 + 默认值省略 | `ok:true`，`order: ["load","select"]` |
| `flows/with_addition.flow` | 同上 + `addition` 块 | `ok:true`，`order` 不变 |

这三个文件直接可当模板：换掉 `data.csv` 与组件名即可。注意 `minimal.flow` 是单节点，`validate` 会给孤立节点警告，这是正常的。
