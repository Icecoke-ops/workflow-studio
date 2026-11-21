// 前端纯函数测试：直接 import frontend/src 下的 ESM 模块，不依赖 Vue 运行时。
// 运行：node tests/test_frontend.mjs

import { envToRows, rowsToEnv, envError, attachEnv } from '../frontend/src/workflow.js'
import { cloneDefault, defaultsFor, buildWorkflow } from '../frontend/src/model.js'
import { readAddition } from '../frontend/src/addition.js'

let failed = 0

function check(condition, label) {
  if (!condition) throw new Error(label)
}

function assertDeepEqual(actual, expected, label) {
  const got = JSON.stringify(actual)
  const want = JSON.stringify(expected)
  if (got !== want) throw new Error(`${label}：期望 ${want}，实际 ${got}`)
}

const cases = []
function addCase(name, fn) {
  cases.push([name, fn])
}

function makeNode(id, plugin, component, config = {}) {
  return { id, data: { plugin, component, config } }
}

function makeArgs(overrides = {}) {
  return {
    name: 'demo',
    nodes: [makeNode('n1', 'fileio', 'LoadCSV')],
    edges: [],
    envRows: [],
    ...overrides,
  }
}

// ---- workflow.js ----

addCase('envToRows 对象转行', () => {
  assertDeepEqual(
    envToRows({ A: '1', B: 2 }),
    [
      { key: 'A', value: '1' },
      { key: 'B', value: '2' },
    ],
    'envToRows',
  )
})

addCase('envToRows 数组返回 null', () => {
  check(envToRows(['A']) === null, '数组应返回 null')
})

addCase('envToRows null 返回 null', () => {
  check(envToRows(null) === null, 'null 应返回 null')
})

addCase('rowsToEnv 跳过空 key、值转字符串', () => {
  const env = rowsToEnv([
    { key: 'A', value: 1 },
    { key: '', value: 'skip' },
    { key: 'B', value: null },
  ])
  assertDeepEqual(env, { A: '1', B: '' }, 'rowsToEnv')
})

addCase('envError 合法行返回空串', () => {
  check(envError([{ key: 'A', value: '1' }]) === '', '合法行应返回空串')
})

addCase('envError 非法名给出中文消息', () => {
  const message = envError([{ key: '1BAD', value: '1' }])
  check(message.includes('环境变量名不合法') && message.includes('1BAD'), `实际：${message}`)
})

addCase('envError 重复名给出中文消息', () => {
  const message = envError([
    { key: 'A', value: '1' },
    { key: 'A', value: '2' },
  ])
  check(message.includes('环境变量名重复') && message.includes('A'), `实际：${message}`)
})

addCase('attachEnv 空对象不加 env 字段', () => {
  const workflow = { name: 'x' }
  const result = attachEnv(workflow, {})
  check(!('env' in result), '空 env 不应写 env 字段')
})

addCase('attachEnv 非空时是拷贝', () => {
  const env = { A: '1' }
  const result = attachEnv({ name: 'x' }, env)
  assertDeepEqual(result.env, { A: '1' }, 'attachEnv 结果')
  result.env.A = '2'
  check(env.A === '1', '改结果不应影响入参 env')
})

// ---- model.js / cloneDefault ----

addCase('cloneDefault 普通对象返回新引用', () => {
  const value = { a: 1, b: [2] }
  const copy = cloneDefault(value)
  assertDeepEqual(copy, value, 'cloneDefault 对象')
  check(copy !== value, '应返回新引用')
})

addCase('cloneDefault Proxy 不抛 structuredClone 崩溃', () => {
  const proxy = new Proxy({ a: 1 }, {})
  const copy = cloneDefault(proxy)
  assertDeepEqual(copy, { a: 1 }, 'cloneDefault Proxy')
  check(copy !== proxy, '应返回新引用')
})

addCase('cloneDefault 嵌套数组返回新引用', () => {
  const value = [[1, 2], [3]]
  const copy = cloneDefault(value)
  assertDeepEqual(copy, value, 'cloneDefault 嵌套数组')
  check(copy !== value && copy[0] !== value[0], '数组及内层都应是新引用')
})

addCase('cloneDefault 标量原样返回', () => {
  check(cloneDefault(null) === null, 'null 应原样返回')
  check(cloneDefault('text') === 'text', '字符串应原样返回')
  check(cloneDefault(42) === 42, '数字应原样返回')
  check(cloneDefault(undefined) === undefined, 'undefined 应原样返回')
})

// ---- model.js / defaultsFor ----

addCase('defaultsFor 只取声明 default 的字段', () => {
  const schema = {
    a: { type: 'string' },
    b: { type: 'number', default: 1 },
    c: { default: 'x' },
  }
  assertDeepEqual(defaultsFor(schema), { b: 1, c: 'x' }, 'defaultsFor')
})

addCase('defaultsFor 数组默认值每次独立', () => {
  const schema = { list: { type: 'array', default: [] } }
  const first = defaultsFor(schema)
  const second = defaultsFor(schema)
  check(Array.isArray(first.list), '数组默认值应保持数组')
  check(first.list !== second.list, '两次调用应得到不同数组')
  first.list.push(1)
  check(second.list.length === 0, '改一个结果不应影响另一个')
  check(schema.list.default.length === 0, '也不应改到 schema 本身')
})

// ---- model.js / buildWorkflow ----

addCase('buildWorkflow name trim 与空名兜底', () => {
  check(buildWorkflow(makeArgs({ name: '  demo  ' })).name === 'demo', 'name 应 trim')
  check(buildWorkflow(makeArgs({ name: '' })).name === '未命名工作流', '空串应兜底')
  check(buildWorkflow(makeArgs({ name: '   ' })).name === '未命名工作流', '全空白应兜底')
})

addCase('buildWorkflow inputs 按 target/targetHandle 归并', () => {
  const result = buildWorkflow(
    makeArgs({
      nodes: [
        makeNode('n1', 'fileio', 'LoadCSV'),
        makeNode('n2', 'ml', 'LinearRegression', { target: 'y' }),
        makeNode('n3', 'table', 'SplitTable'),
      ],
      edges: [
        { source: 'n1', target: 'n2', sourceHandle: 'data', targetHandle: 'train' },
        { source: 'n3', target: 'n2', sourceHandle: 'model', targetHandle: 'model' },
      ],
    }),
  )
  const n2 = result.nodes.find((node) => node.id === 'n2')
  assertDeepEqual(
    n2.inputs,
    {
      train: { from: 'n1', port: 'data' },
      model: { from: 'n3', port: 'model' },
    },
    'inputs',
  )
})

addCase('buildWorkflow 缺 handle 的边被跳过', () => {
  const result = buildWorkflow(
    makeArgs({
      nodes: [makeNode('n1', 'fileio', 'LoadCSV'), makeNode('n2', 'ml', 'LinearRegression')],
      edges: [
        { source: 'n1', target: 'n2', targetHandle: 'data' },
        { source: 'n1', target: 'n2', sourceHandle: 'data' },
        { source: 'n1', target: 'n2', sourceHandle: '', targetHandle: 'data' },
      ],
    }),
  )
  assertDeepEqual(result.nodes[1].inputs, {}, '缺 handle 的边不应产生 inputs')
})

addCase('buildWorkflow 节点只输出五个字段', () => {
  const node = makeNode('n1', 'fileio', 'LoadCSV', { path: 'data.csv' })
  node.data.descOpen = true
  node.data.title = '不该输出'
  const result = buildWorkflow(makeArgs({ nodes: [node] }))
  assertDeepEqual(
    Object.keys(result.nodes[0]),
    ['id', 'plugin', 'component', 'config', 'inputs'],
    '节点字段',
  )
})

addCase('buildWorkflow config 是浅拷贝', () => {
  const node = makeNode('n1', 'fileio', 'LoadCSV', { path: 'data.csv' })
  const result = buildWorkflow(makeArgs({ nodes: [node] }))
  check(result.nodes[0].config !== node.data.config, 'config 不应是同一个对象')
  result.nodes[0].config.path = 'changed.csv'
  check(node.data.config.path === 'data.csv', '改结果不应影响入参节点的 config')
})

addCase('buildWorkflow envRows 为空时没有 env 键', () => {
  check(!('env' in buildWorkflow(makeArgs())), '空 envRows 不应写 env')
  check(
    !('env' in buildWorkflow(makeArgs({ envRows: [{ key: '', value: 'x' }] }))),
    '只有空 key 行时也不应写 env',
  )
})

addCase('buildWorkflow envRows 有值时 env 正确', () => {
  const result = buildWorkflow(makeArgs({ envRows: [{ key: 'A', value: 1 }] }))
  assertDeepEqual(result.env, { A: '1' }, 'env')
})

// ---- importWorkflow.js：导入 / 布局纯函数 ----

const TABLE = { type: 'std_1.0@table', type_label: '数据表' }
const MODEL = { type: 'std_1.0@model', type_label: '模型' }

let importModule = null

async function loadImport() {
  if (importModule === null) {
    importModule = await import('../frontend/src/importWorkflow.js')
  }
  return importModule
}

function componentEntry(plugin, component, { inputs = {}, outputs = {} } = {}) {
  return {
    plugin,
    pluginTitle: `${plugin} 插件`,
    name: component,
    title: `${component} 标题`,
    desc: '',
    config_schema: {},
    input_schema: inputs,
    output_schema: outputs,
  }
}

function loadCsvEntry() {
  return componentEntry('fileio', 'LoadCSV', { outputs: { table: TABLE } })
}

function predictEntry() {
  return componentEntry('core', 'PredictModel', {
    inputs: {
      model: { types: [MODEL.type], type_labels: [MODEL.type_label] },
      data: { types: [TABLE.type], type_labels: [TABLE.type_label] },
    },
    outputs: { predictions: TABLE },
  })
}

function selectEntry() {
  return componentEntry('table', 'SelectColumns', {
    inputs: { data: { types: [TABLE.type], type_labels: [TABLE.type_label] } },
    outputs: { table: TABLE },
  })
}

function layoutOptions(components) {
  const index = new Map(
    components.map((item) => [`${item.plugin}.${item.name}`, item]),
  )
  return {
    componentFor: (plugin, component) => index.get(`${plugin}.${component}`),
    typeDescs: {},
    typeColors: {},
  }
}

function sourceNodes() {
  return [
    {
      id: 'n1',
      plugin: 'fileio',
      component: 'LoadCSV',
      config: { path: 'data.csv' },
      inputs: {},
    },
    {
      id: 'n2',
      plugin: 'core',
      component: 'PredictModel',
      config: {},
      inputs: { model: { from: 'n1', port: 'table' } },
    },
  ]
}

addCase('normalizeWorkflow 根不是对象报错', async () => {
  const { normalizeWorkflow } = await loadImport()
  for (const raw of [null, 'text', 42]) {
    let message = ''
    try {
      normalizeWorkflow(raw)
    } catch (err) {
      message = err.message
    }
    check(
      message.includes('根节点必须是对象'),
      `应拒绝 ${JSON.stringify(raw)}：${message}`,
    )
  }
})

addCase('normalizeWorkflow 缺 nodes 数组报错', async () => {
  const { normalizeWorkflow } = await loadImport()
  let message = ''
  try {
    normalizeWorkflow({ name: 'x' })
  } catch (err) {
    message = err.message
  }
  check(message.includes('缺少 nodes 数组'), `实际：${message}`)
})

addCase('normalizeWorkflow 过滤坏节点并记录原因', async () => {
  const { normalizeWorkflow } = await loadImport()
  const { items, skipped } = normalizeWorkflow({
    nodes: [
      null,
      { plugin: 'fileio', component: 'LoadCSV' },
      { id: 'n1' },
      { id: 'n2', plugin: 'fileio', component: 'LoadCSV' },
      { id: 'n2', plugin: 'fileio', component: 'LoadCSV' },
    ],
  })
  check(
    items.length === 1 && items[0].id === 'n2',
    `只剩一个合法节点：${JSON.stringify(items)}`,
  )
  check(skipped.length === 4, `应记录 4 次跳过：${JSON.stringify(skipped)}`)
  check(
    skipped.some((item) => item.includes('n2')),
    `重复 id 应指出 n2：${JSON.stringify(skipped)}`,
  )
})

addCase('layoutPositions 按 inputs 分层且同层错开', async () => {
  const { layoutPositions } = await loadImport()
  const positions = layoutPositions([
    { id: 'a', inputs: {} },
    { id: 'b', inputs: { data: { from: 'a', port: 'table' } } },
    { id: 'c', inputs: { data: { from: 'b', port: 'table' } } },
    { id: 'd', inputs: {} },
  ])
  check(positions.get('a').x < positions.get('b').x, 'b 应在 a 右侧')
  check(positions.get('b').x < positions.get('c').x, 'c 应在 b 右侧')
  check(positions.get('a').x === positions.get('d').x, '同层 x 应一致')
  check(positions.get('a').y !== positions.get('d').y, '同层节点应错开 y')
})

addCase('layoutPositions 成环与自环不死循环', async () => {
  const { layoutPositions } = await loadImport()
  const cycle = layoutPositions([
    { id: 'a', inputs: { data: { from: 'b', port: 'table' } } },
    { id: 'b', inputs: { data: { from: 'a', port: 'table' } } },
  ])
  const selfLoop = layoutPositions([
    { id: 's', inputs: { data: { from: 's', port: 'table' } } },
  ])
  for (const [label, positions] of [
    ['环', cycle],
    ['自环', selfLoop],
  ]) {
    for (const [id, position] of positions) {
      check(
        Number.isFinite(position.x) && Number.isFinite(position.y),
        `${label} 节点 ${id} 应有有限坐标：${JSON.stringify(position)}`,
      )
    }
  }
})

addCase('planImport 正常 JSON', async () => {
  const { planImport } = await loadImport()
  const plan = planImport(
    { name: 'demo', nodes: sourceNodes() },
    layoutOptions([loadCsvEntry(), predictEntry()]),
  )
  check(plan.name === 'demo', `name 不对：${JSON.stringify(plan.name)}`)
  check(plan.nodes.length === 2, `节点数不对：${plan.nodes.length}`)
  check(plan.edges.length === 1, `边数不对：${plan.edges.length}`)
  const edge = plan.edges[0]
  check(
    edge.source === 'n1' &&
      edge.target === 'n2' &&
      edge.sourceHandle === 'table' &&
      edge.targetHandle === 'model',
    `边方向/端口不对：${JSON.stringify(edge)}`,
  )
  check(plan.missing.length === 0, `不应有缺失组件：${plan.missing}`)
  check(plan.skipped.length === 0, `不应有跳过项：${plan.skipped}`)

  const [first, second] = plan.nodes
  check(first.type === 'comp', `节点 type 不对：${first.type}`)
  check(
    first.data.plugin === 'fileio' &&
      first.data.component === 'LoadCSV' &&
      first.data.missing === false,
    `节点 data 不对：${JSON.stringify(first.data)}`,
  )
  assertDeepEqual(
    first.data.outPorts.map((port) => port.name),
    ['table'],
    '出端口',
  )
  assertDeepEqual(
    second.data.inPorts.map((port) => port.name),
    ['model', 'data'],
    '入端口',
  )
  check(first.data.config.path === 'data.csv', `config 丢了：${JSON.stringify(first.data.config)}`)
  for (const node of plan.nodes) {
    check(
      Number.isFinite(node.position?.x) && Number.isFinite(node.position?.y),
      `节点 ${node.id} 应有有限坐标：${JSON.stringify(node.position)}`,
    )
  }
})

addCase('planImport 缺组件时生成占位节点并进 missing', async () => {
  const { planImport } = await loadImport()
  const plan = planImport(
    {
      name: 'missing',
      nodes: [
        { id: 'n1', plugin: 'ghost', component: 'Nope', config: {}, inputs: {} },
      ],
    },
    layoutOptions([]),
  )
  check(plan.nodes.length === 1, `缺组件也应有占位节点：${plan.nodes.length}`)
  check(plan.nodes[0].data.missing === true, '占位节点应标 missing')
  check(
    plan.nodes[0].data.title === 'ghost.Nope',
    `占位标题不对：${plan.nodes[0].data.title}`,
  )
  assertDeepEqual(plan.missing, ['ghost.Nope'], 'missing')
  check(
    plan.skipped.length === 0,
    `合法节点不应记跳过：${JSON.stringify(plan.skipped)}`,
  )
})

addCase('planImport 坏边不生成连线', async () => {
  const { planImport } = await loadImport()
  const plan = planImport(
    {
      name: 'badedges',
      nodes: [
        { id: 'n1', plugin: 'fileio', component: 'LoadCSV', config: {}, inputs: {} },
        {
          id: 'n2',
          plugin: 'core',
          component: 'PredictModel',
          config: {},
          inputs: {
            model: { from: 'ghost', port: 'table' },
            data: { from: 'n1', port: 'nosuchport' },
            predictions: { from: 'n1', port: 'table' },
          },
        },
      ],
    },
    layoutOptions([loadCsvEntry(), predictEntry()]),
  )
  check(plan.nodes.length === 2, `节点应保留：${plan.nodes.length}`)
  check(plan.edges.length === 0, `坏边都应跳过：${JSON.stringify(plan.edges)}`)
})

addCase('planImport 成环不挂死且节点都有坐标', async () => {
  const { planImport } = await loadImport()
  const plan = planImport(
    {
      name: 'cycle',
      nodes: [
        {
          id: 'a',
          plugin: 'table',
          component: 'SelectColumns',
          config: { columns: ['x'] },
          inputs: { data: { from: 'b', port: 'table' } },
        },
        {
          id: 'b',
          plugin: 'table',
          component: 'SelectColumns',
          config: { columns: ['y'] },
          inputs: { data: { from: 'a', port: 'table' } },
        },
      ],
    },
    layoutOptions([selectEntry()]),
  )
  check(plan.nodes.length === 2, `成环也应保留两个节点：${plan.nodes.length}`)
  check(plan.edges.length === 2, `成环的两条边都应保留：${plan.edges.length}`)
  for (const node of plan.nodes) {
    check(
      Number.isFinite(node.position?.x) && Number.isFinite(node.position?.y),
      `节点 ${node.id} 应有有限坐标：${JSON.stringify(node.position)}`,
    )
  }
})

addCase('planImport 缺 name 时兜底', async () => {
  const { planImport } = await loadImport()
  check(
    planImport({ nodes: [] }, layoutOptions([])).name === '导入的工作流',
    '缺 name 应兜底',
  )
  check(
    planImport({ name: '', nodes: [] }, layoutOptions([])).name === '导入的工作流',
    '空 name 应兜底',
  )
})

// ---------------------------------------------------------------------------
// addition：编辑器私有区（坐标 / 分组 + 别人的块原样保留）
// ---------------------------------------------------------------------------

function studioAddition(positions, groups = []) {
  return { client: 'workflow-studio', version: 1, positions, groups }
}

function exportWorkflow(plan, addition) {
  return buildWorkflow({
    name: plan.name,
    nodes: plan.nodes,
    edges: plan.edges,
    envRows: [],
    addition,
  })
}

function positionsOf(plan) {
  return Object.fromEntries(plan.nodes.map((node) => [node.id, node.position]))
}

addCase('addition 导入：存档坐标优先于层级布局', async () => {
  const { planImport } = await loadImport()
  const saved = { n1: { x: 900, y: 700 }, n2: { x: 12, y: 34 } }
  const raw = {
    name: 'saved',
    nodes: sourceNodes(),
    addition: studioAddition(saved),
  }
  const plan = planImport(raw, layoutOptions([loadCsvEntry(), predictEntry()]))
  const actual = positionsOf(plan)
  for (const id of ['n1', 'n2']) {
    check(
      actual[id].x === saved[id].x && actual[id].y === saved[id].y,
      `节点 ${id} 应使用存档坐标 ${JSON.stringify(saved[id])}，实际 ${JSON.stringify(actual[id])}`,
    )
  }
})

addCase('addition 往返：positions 与 groups 与导入一致', async () => {
  const { planImport } = await loadImport()
  const groups = [{ id: 'g1', title: '组一', nodes: ['n1', 'n2'], color: '#123456' }]
  const raw = {
    name: 'roundtrip',
    nodes: sourceNodes(),
    addition: studioAddition({ n1: { x: 900, y: 700 }, n2: { x: 12, y: 34 } }, groups),
  }
  const addition = readAddition(raw)
  const plan = planImport(raw, layoutOptions([loadCsvEntry(), predictEntry()]))
  const workflow = exportWorkflow(plan, addition)
  assertDeepEqual(workflow.addition.positions, raw.addition.positions, '往返 positions')
  assertDeepEqual(workflow.addition.groups, groups, '往返 groups')
})

addCase('addition 导入：部分节点缺坐标走兜底', async () => {
  const { planImport } = await loadImport()
  const raw = {
    name: 'partial',
    nodes: sourceNodes(),
    addition: studioAddition({ n1: { x: 5, y: 6 } }),
  }
  const plan = planImport(raw, layoutOptions([loadCsvEntry(), predictEntry()]))
  const actual = positionsOf(plan)
  check(actual.n1.x === 5 && actual.n1.y === 6, `n1 应用存档坐标：${JSON.stringify(actual.n1)}`)
  check(
    Number.isFinite(actual.n2.x) && Number.isFinite(actual.n2.y),
    `n2 缺坐标应走兜底：${JSON.stringify(actual.n2)}`,
  )
  check(
    !(actual.n2.x === 0 && actual.n2.y === 0),
    `兜底坐标不应是 (0, 0)：${JSON.stringify(actual.n2)}`,
  )
  check(
    actual.n1.x !== actual.n2.x || actual.n1.y !== actual.n2.y,
    `两个节点不应重叠：${JSON.stringify(actual)}`,
  )
})

addCase('addition 导入：坏坐标走兜底且不出现 NaN', async () => {
  const { planImport } = await loadImport()
  const raw = {
    name: 'badpos',
    nodes: sourceNodes(),
    addition: studioAddition({
      n1: { x: 'abc', y: null },
      n2: { x: Infinity, y: 10 },
    }),
  }
  const plan = planImport(raw, layoutOptions([loadCsvEntry(), predictEntry()]))
  for (const node of plan.nodes) {
    check(
      Number.isFinite(node.position?.x) && Number.isFinite(node.position?.y),
      `节点 ${node.id} 坐标应有限：${JSON.stringify(node.position)}`,
    )
  }
})

addCase('addition 作者不是本客户端：忽略并原样保留', async () => {
  const { planImport } = await loadImport()
  const foreign = {
    client: 'other-editor',
    version: 7,
    positions: { n1: { x: 1, y: 2 } },
    extra: { b: 1, a: 2 },
  }
  const raw = { name: 'foreign', nodes: sourceNodes(), addition: foreign }
  const addition = readAddition(raw)
  check(addition.warning !== '', '别人的 addition 应给出 warning')
  const plan = planImport(raw, layoutOptions([loadCsvEntry(), predictEntry()]))
  check(
    !(plan.nodes[0].position.x === 1 && plan.nodes[0].position.y === 2),
    '别人的 positions 不应被采用',
  )
  const workflow = exportWorkflow(plan, addition)
  check(workflow.addition === foreign, '导出应保留同一引用')
  check(
    JSON.stringify(workflow.addition) === JSON.stringify(foreign),
    `导出应与导入的 JSON 逐字节一致：${JSON.stringify(workflow.addition)}`,
  )
})

addCase('addition 版本高于支持值：忽略并原样保留', async () => {
  const { planImport } = await loadImport()
  const future = {
    client: 'workflow-studio',
    version: 999,
    positions: { n1: { x: 1, y: 2 } },
  }
  const raw = { name: 'future', nodes: sourceNodes(), addition: future }
  const addition = readAddition(raw)
  check(addition.warning !== '', '高版本 addition 应给出 warning')
  const plan = planImport(raw, layoutOptions([loadCsvEntry(), predictEntry()]))
  check(
    !(plan.nodes[0].position.x === 1 && plan.nodes[0].position.y === 2),
    '高版本 addition 的 positions 不应被采用',
  )
  const workflow = exportWorkflow(plan, addition)
  check(workflow.addition === future, '导出应保留同一引用')
  check(
    JSON.stringify(workflow.addition) === JSON.stringify(future),
    `导出应与导入的 JSON 逐字节一致：${JSON.stringify(workflow.addition)}`,
  )
})

addCase('addition 不是对象：忽略且导出写入自己的块', async () => {
  const { planImport } = await loadImport()
  for (const value of ['text', 42, []]) {
    const raw = { name: 'notobj', nodes: sourceNodes(), addition: value }
    const addition = readAddition(raw)
    check(addition.warning === '', `非对象不应给 warning：${JSON.stringify(value)}`)
    const plan = planImport(raw, layoutOptions([loadCsvEntry(), predictEntry()]))
    const workflow = exportWorkflow(plan, addition)
    check(
      workflow.addition.client === 'workflow-studio' && workflow.addition.version === 1,
      `导出应写入自己的块：${JSON.stringify(workflow.addition)}`,
    )
    check(
      Boolean(workflow.addition.positions.n1) && Boolean(workflow.addition.positions.n2),
      `导出应带上自己的 positions：${JSON.stringify(workflow.addition.positions)}`,
    )
    check(workflow.addition !== value, '不应把非对象值原样写回')
  }
})

addCase('完全没有 addition：导出补上自己的 positions', async () => {
  const { planImport } = await loadImport()
  const raw = { name: 'plain', nodes: sourceNodes() }
  const addition = readAddition(raw)
  check(addition.warning === '', '没有 addition 不应给 warning')
  const plan = planImport(raw, layoutOptions([loadCsvEntry(), predictEntry()]))
  const workflow = exportWorkflow(plan, addition)
  check(workflow.addition.client === 'workflow-studio', '导出应写入自己的 client')
  check(workflow.addition.version === 1, '导出应写入支持的 version')
  for (const node of plan.nodes) {
    check(
      Boolean(workflow.addition.positions[node.id]),
      `导出应包含节点 ${node.id} 的坐标`,
    )
  }
})

// ---- 跑测 ----

async function main() {
  for (const [name, fn] of cases) {
    try {
      await fn()
      console.log(`ok   ${name}`)
    } catch (err) {
      console.log(`FAIL ${name}: ${err.message}`)
      failed += 1
    }
  }

  if (failed) {
    console.log(`\n[FAIL] frontend：${failed}/${cases.length} 个用例失败`)
    process.exit(1)
  }
  console.log(`\nOK  frontend：${cases.length} 个用例全部通过`)
  process.exit(0)
}

await main()
