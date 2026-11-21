// 前端纯函数测试：直接 import frontend/src 下的 ESM 模块，不依赖 Vue 运行时。
// 运行：node tests/test_frontend.mjs

import { envToRows, rowsToEnv, envError, attachEnv } from '../frontend/src/workflow.js'
import { cloneDefault, defaultsFor, buildWorkflow } from '../frontend/src/model.js'
import { readAddition } from '../frontend/src/addition.js'
import {
  isComponentNode,
  parentOf,
  collapsedAncestor,
  canConnect,
  parseHandle,
  resolveConnection,
  projectEdges,
  projectGraph,
  frameItems,
  memberLeaves,
  selectionUnits,
  commonParent,
  canGroup,
  canDissolve,
  nextGroupId,
  createGroup,
  dissolveGroup,
  setCollapsed,
  pruneGroups,
  dropEdgesForNodes,
  nodeBoxes,
  unitBox,
  selectionBox,
  groupPositions,
  serializeGroups,
} from '../frontend/src/groups.js'
import { collectCopy, planPaste } from '../frontend/src/clipboard.js'
import { fetchHealth, fetchPlugins, runWorkflow } from '../frontend/src/api.js'

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

// ---------------------------------------------------------------------------
// groups.js：子图树、投影、包围盒与序列化
// ---------------------------------------------------------------------------

function grp(id, members, extra = {}) {
  return { id, title: id, collapsed: false, members, ...extra }
}

function compNode(id, position = { x: 0, y: 0 }, config = {}) {
  return {
    id,
    type: 'comp',
    position,
    data: {
      plugin: 'fileio',
      component: 'LoadCSV',
      config,
      inPorts: [],
      outPorts: [],
    },
  }
}

function cardNode(id, position) {
  return { id, type: 'group', position }
}

function frameNode(id, position = { x: 0, y: 0 }) {
  return { id, type: 'frame', position }
}

function wireEdge(id, source, sourceHandle, target, targetHandle) {
  return { id, type: 'workflow', source, sourceHandle, target, targetHandle }
}

addCase('isComponentNode 只把非组节点当组件', () => {
  check(isComponentNode({ type: 'group' }) === false, 'group 不是组件节点')
  check(isComponentNode({ type: 'frame' }) === false, 'frame 不是组件节点')
  check(isComponentNode({ type: 'comp' }) === true, 'comp 是组件节点')
  check(isComponentNode({}) === true, '未标 type 按组件处理')
})

addCase('collapsedAncestor 取最近折叠祖先且环上有界', () => {
  const chain = [
    grp('outer', ['inner'], { collapsed: true }),
    grp('inner', ['n1'], { collapsed: true }),
  ]
  check(collapsedAncestor(chain, 'n1') === 'inner', '应取最近的折叠祖先 inner')
  check(collapsedAncestor(chain, 'inner') === 'outer', 'inner 自身的折叠祖先是 outer')
  const onlyOuter = [grp('outer', ['inner'], { collapsed: true }), grp('inner', ['n1'])]
  check(collapsedAncestor(onlyOuter, 'n1') === 'outer', 'inner 未折叠时应继续向上找')

  const cycle = [
    grp('A', ['B'], { collapsed: true }),
    grp('B', ['A']),
  ]
  const result = collapsedAncestor(cycle, 'A')
  check(result === 'A', `畸形环应返回有界结果（实际 ${JSON.stringify(result)}）`)
})

addCase('canConnect 只放行同层且非自身', () => {
  const groups = [grp('g1', ['n1'], { collapsed: true })]
  check(canConnect(groups, 'n3', 'n4') === true, 'root 层两个节点应允许')
  check(canConnect(groups, 'n1', 'n2') === false, '折叠组内节点与组外节点不能连')
  check(canConnect(groups, 'n1', 'n1') === false, '同一个 id 不能连')
  check(canConnect(groups, 'g1', 'n2') === true, '组卡片按父层参与连线')
  check(canConnect(groups, 'n1', 'g1') === false, '组内节点与组卡片不同层')
})

addCase('parseHandle 解析与非法输入', () => {
  assertDeepEqual(parseHandle('n1:data'), { nodeId: 'n1', port: 'data' }, 'parseHandle 正常')
  for (const bad of ['n1', ':x', 'n1:', 123, null, undefined]) {
    check(parseHandle(bad) === null, `非法 handle 应返回 null：${JSON.stringify(bad)}`)
  }
})

addCase('resolveConnection 组卡片端点解析回真实节点', () => {
  const groups = [grp('g1', ['n1', 'n2'])]
  assertDeepEqual(
    resolveConnection(groups, {
      source: 'g1',
      sourceHandle: 'n1:out',
      target: 'n2',
      targetHandle: 'in',
    }),
    { source: 'n1', sourceHandle: 'out', target: 'n2', targetHandle: 'in' },
    '组卡片作为源',
  )
  assertDeepEqual(
    resolveConnection(groups, {
      source: 'n3',
      sourceHandle: 'out',
      target: 'g1',
      targetHandle: 'n2:in',
    }),
    { source: 'n3', sourceHandle: 'out', target: 'n2', targetHandle: 'in' },
    '组卡片作为目标',
  )
  check(
    resolveConnection(groups, { source: 'n1', target: 'n2', targetHandle: 'in' }) === null,
    '缺 handle 应返回 null',
  )
  check(resolveConnection(groups, null) === null, 'null 连接应返回 null')
})

addCase('projectEdges 组内边不画、跨组边换组卡片', () => {
  const groups = [grp('g1', ['n1', 'n2'], { collapsed: true })]
  const edges = [
    wireEdge('e1', 'n1', 'out', 'n2', 'in'),
    wireEdge('e2', 'n1', 'out', 'n3', 'in'),
    wireEdge('e3', 'n4', 'out', 'n2', 'in'),
  ]
  const projected = projectEdges(edges, groups)
  check(projected.length === 2, `组内边不应画出：${projected.length}`)
  assertDeepEqual(
    projected[0],
    wireEdge('e2', 'g1', 'n1:out', 'n3', 'in'),
    '源的组内端应换成组卡片',
  )
  assertDeepEqual(
    projected[1],
    wireEdge('e3', 'n4', 'out', 'g1', 'n2:in'),
    '目标的组内端应换成组卡片',
  )
  check(projected[0].id === 'e2' && projected[1].id === 'e3', '边 id 必须沿用真实边 id')
})

addCase('projectGraph 折叠组：隐藏成员、组卡片端口去重', () => {
  const n1 = compNode('n1', { x: 10, y: 10 })
  n1.data.outPorts = [{ name: 'out', type: 'std_1.0@table', color: '#111' }]
  n1.data.inPorts = [{ name: 'in', types: ['std_1.0@table'], color: '#222' }]
  const n3 = compNode('n3', { x: 400, y: 10 })
  const n4 = compNode('n4', { x: 400, y: 300 })
  const edges = [
    wireEdge('e1', 'n1', 'out', 'n3', 'in'),
    wireEdge('e2', 'n1', 'out', 'n4', 'in'),
    wireEdge('e3', 'n3', 'out', 'n1', 'in'),
  ]
  const result = projectGraph({
    nodes: [n1, n3, n4],
    edges,
    groups: [grp('g1', ['n1'], { collapsed: true, position: { x: 200, y: 300 } })],
  })
  const byId = Object.fromEntries(result.nodes.map((node) => [node.id, node]))
  check(byId.n1.hidden === true, '折叠组里的组件节点应 hidden')
  check(byId.n3.hidden === false, '组外节点不应 hidden')
  check(byId.g1.type === 'group', '折叠组应出 group 卡片')
  assertDeepEqual(byId.g1.position, { x: 200, y: 300 }, '卡片位置用组记录的 position')
  check(byId.g1.data.count === 1, '卡片应带成员数')
  assertDeepEqual(
    byId.g1.data.outPorts,
    [{ name: 'n1:out', type: 'std_1.0@table', color: '#111' }],
    '同一端口的边只出现一次',
  )
  assertDeepEqual(
    byId.g1.data.inPorts,
    [{ name: 'n1:in', types: ['std_1.0@table'], color: '#222' }],
    '入端口同样按边界边推导',
  )
})

addCase('projectGraph 展开组：frame 固定在原点且不可交互', () => {
  const result = projectGraph({
    nodes: [compNode('n1', { x: 10, y: 10 })],
    edges: [],
    groups: [grp('g1', ['n1'])],
  })
  const frame = result.nodes.find((node) => node.id === 'g1')
  check(frame.type === 'frame', '展开组应出 frame')
  assertDeepEqual(frame.position, { x: 0, y: 0 }, 'frame 固定在 (0,0)')
  check(frame.zIndex === -1, 'frame 应在底层')
  check(
    frame.selectable === false && frame.draggable === false && frame.connectable === false,
    'frame 不可选、不可拖、不可连',
  )
  check(
    result.nodes.find((node) => node.id === 'n1').hidden === false,
    '展开组里的组件节点不应 hidden',
  )
})

addCase('projectGraph 上一帧 frame 的坐标不能当组卡片位置', () => {
  const result = projectGraph({
    nodes: [compNode('n1', { x: 10, y: 10 }), frameNode('g1')],
    edges: [],
    groups: [grp('g1', ['n1'], { collapsed: true, position: { x: 150, y: 250 } })],
  })
  const card = result.nodes.find((node) => node.id === 'g1')
  check(card.type === 'group', '上一帧是 frame，这一帧折叠后应是 group 卡片')
  assertDeepEqual(card.position, { x: 150, y: 250 }, '不能用 frame 的 (0,0) 当卡片位置')

  const reused = projectGraph({
    nodes: [compNode('n1', { x: 10, y: 10 }), cardNode('g1', { x: 7, y: 8 })],
    edges: [],
    groups: [grp('g1', ['n1'], { collapsed: true })],
  })
  assertDeepEqual(
    reused.nodes.find((node) => node.id === 'g1').position,
    { x: 7, y: 8 },
    '上一帧也是组卡片时应复用画布位置',
  )
})

addCase('projectGraph 外层折叠时内层组也隐藏', () => {
  const result = projectGraph({
    nodes: [compNode('n1', { x: 10, y: 10 })],
    edges: [],
    groups: [
      grp('outer', ['inner'], { collapsed: true }),
      grp('inner', ['n1']),
    ],
  })
  const byId = Object.fromEntries(result.nodes.map((node) => [node.id, node]))
  check(byId.n1.hidden === true, '外层折叠时内层节点应隐藏')
  check(byId.inner.hidden === true, '外层折叠时内层组卡片/框也隐藏')
  check(byId.outer.hidden === false, '外层自身的卡片不应隐藏')
})

addCase('frameItems 展开子组递归、折叠子组算一项', () => {
  const groups = [
    grp('g1', ['n1', 'g2', 'g3']),
    grp('g2', ['n2']),
    grp('g3', ['n3'], { collapsed: true }),
  ]
  assertDeepEqual(frameItems(groups, 'g1'), ['n1', 'n2', 'g3'], 'frameItems 递归与折叠')
})

addCase('memberLeaves 面包屑与叶子 nodeId', () => {
  const groups = [
    grp('g1', ['n1', 'g2']),
    { ...grp('g2', ['n2', 'g3']), title: '内层' },
    { ...grp('g3', ['n3']), title: '更深' },
  ]
  assertDeepEqual(
    memberLeaves(groups, 'g1'),
    [
      { nodeId: 'n1', trail: [] },
      { nodeId: 'n2', trail: ['内层'] },
      { nodeId: 'n3', trail: ['内层', '更深'] },
    ],
    'memberLeaves',
  )
})

addCase('selectionUnits 节点归一到最外层组并去重', () => {
  const groups = [grp('g1', ['n1', 'g2']), grp('g2', ['n2'])]
  assertDeepEqual(selectionUnits(groups, ['n2']), ['g1'], '节点应归一到最外层祖先组')
  assertDeepEqual(selectionUnits(groups, ['g1', 'n2', 'g1']), ['g1'], '已在选中的组不重复')
  check(selectionUnits(groups, ['n3'])[0] === 'n3', 'root 层节点保持自身')
  assertDeepEqual(selectionUnits(groups, ['g2']), ['g2'], '选中的组保持自身（不被提升）')
})

addCase('selectionUnits 选中内层组和其成员只保留最外层组', () => {
  const groups = [grp('g1', ['n1', 'g2']), grp('g2', ['n2'])]
  assertDeepEqual(
    selectionUnits(groups, ['g2', 'n2']),
    ['g1'],
    '内层组应被它所属的最外层组吸收',
  )
})

addCase('selectionUnits 祖先组和后代节点只保留祖先', () => {
  const groups = [grp('g1', ['n1', 'g2']), grp('g2', ['n2'])]
  assertDeepEqual(
    selectionUnits(groups, ['g1', 'n2']),
    ['g1'],
    '后代节点归一后应被已选中的祖先组吸收',
  )
})

addCase('selectionUnits 互不包含的组原样保留', () => {
  const groups = [
    grp('g1', ['n1', 'g2', 'g3']),
    grp('g2', ['n2']),
    grp('g3', ['n3']),
  ]
  assertDeepEqual(
    selectionUnits(groups, ['g2', 'g3']),
    ['g2', 'g3'],
    '互不包含的两个组不应被误删',
  )
})

addCase('selectionUnits 畸形环有界返回', () => {
  const groups = [grp('gA', ['gB']), grp('gB', ['gA'])]
  const units = selectionUnits(groups, ['gA', 'gB'])
  check(Array.isArray(units), `应返回数组：${JSON.stringify(units)}`)
  check(units.length <= 2, `返回数量应有界：${JSON.stringify(units)}`)
})

addCase('commonParent / canGroup / canDissolve 判定', () => {
  const groups = [grp('g1', ['n1', 'n2', 'g2', 'g3']), grp('g2', ['n5']), grp('g3', ['n6'])]
  check(commonParent(groups, ['n1', 'n2']) === 'g1', '同父应返回该父组')
  check(commonParent(groups, ['n7', 'n8']) === null, 'root 层同父返回 null')
  check(commonParent(groups, ['n1', 'n7']) === undefined, '不同父应返回 undefined')
  check(canGroup(groups, ['n7', 'n8']) === true, '同父两个单元可以建组')
  check(canGroup(groups, ['g2', 'g3']) === true, '同父的两个子组可以再建组')
  check(canGroup(groups, ['n7']) === false, '单个单元不能建组')
  check(canGroup(groups, ['g2', 'n1']) === false, '不同父不能建组')
  check(canDissolve(groups, ['g1']) === true, '恰好选一个组可以解散')
  check(canDissolve(groups, ['n7']) === false, '选节点不能解散')
  check(canDissolve(groups, ['g1', 'g2']) === false, '选多个组不能解散')
})

addCase('nextGroupId 跳过已用编号', () => {
  check(nextGroupId([]) === 'g1', '空表从 g1 开始')
  check(nextGroupId([grp('g1', []), grp('g3', [])]) === 'g2', '应跳过已用的 g1/g3')
  check(nextGroupId([grp('g1', []), grp('g2', [])]) === 'g3', '连续编号不跳空')
})

addCase('createGroup 默认折叠并替换父组成员', () => {
  const groups = [grp('g1', ['n1', 'n2', 'n3', 'n4'])]
  const next = createGroup(groups, {
    id: 'g9',
    title: '新组',
    units: ['n2', 'n4'],
    parent: 'g1',
    position: { x: 10, y: 20 },
  })
  const created = next.find((group) => group.id === 'g9')
  assertDeepEqual(
    created,
    { id: 'g9', title: '新组', collapsed: true, members: ['n2', 'n4'], position: { x: 10, y: 20 } },
    '新组默认折叠、成员与位置',
  )
  assertDeepEqual(
    next.find((group) => group.id === 'g1').members,
    ['n1', 'g9', 'n3'],
    '新组应插在第一个被移走成员的原位置',
  )

  const noPosition = createGroup([], { id: 'g1', title: 'x', units: ['n1'], position: { x: NaN, y: 5 } })
  check(!('position' in noPosition[0]), 'position 非有限值时不写')
})

addCase('dissolveGroup 只拆一层并提升成员', () => {
  const groups = [
    grp('g1', ['n1', 'g2']),
    grp('g2', ['n2', 'n3']),
    grp('g3', ['n4']),
  ]
  const nested = dissolveGroup(groups, 'g2')
  check(!nested.some((group) => group.id === 'g2'), 'g2 应消失')
  assertDeepEqual(
    nested.find((group) => group.id === 'g1').members,
    ['n1', 'n2', 'n3'],
    '成员应提升到父组原位置',
  )
  assertDeepEqual(
    nested.find((group) => group.id === 'g3').members,
    ['n4'],
    '其它组不应被动到',
  )

  const top = dissolveGroup(groups, 'g1')
  check(!top.some((group) => group.id === 'g1'), '顶层组应直接消失')
  assertDeepEqual(
    top.find((group) => group.id === 'g2').members,
    ['n2', 'n3'],
    '拆顶层组不应影响子组',
  )
})

addCase('setCollapsed 只改目标组', () => {
  const groups = [grp('g1', ['n1']), grp('g2', ['n2'])]
  const next = setCollapsed(groups, 'g1', true, { x: 5, y: 6 })
  assertDeepEqual(
    next.find((group) => group.id === 'g1'),
    { id: 'g1', title: 'g1', collapsed: true, members: ['n1'], position: { x: 5, y: 6 } },
    '目标组应折叠并写位置',
  )
  assertDeepEqual(next.find((group) => group.id === 'g2'), groups[1], '其它组不应变化')

  const bad = setCollapsed([grp('g1', ['n1'])], 'g1', true, { x: 'a', y: 1 })
  check(!('position' in bad[0]), 'position 非有限值时不写')
})

addCase('pruneGroups 删除后收敛且畸形环不死循环', () => {
  const nodes = [compNode('n1'), compNode('n2')]
  const one = pruneGroups([grp('g1', ['n1', 'n2'])], [nodes[0]])
  assertDeepEqual(one[0].members, ['n1'], '删一个成员只少一个')

  const gone = pruneGroups([grp('g1', ['g2']), grp('g2', ['n1'])], [])
  check(gone.length === 0, `删空后组应逐层解散：${JSON.stringify(gone)}`)

  const cycle = [grp('A', ['B']), grp('B', ['A'])]
  const bounded = pruneGroups(cycle, [])
  check(
    Array.isArray(bounded) && bounded.length === 2,
    `畸形环应终止（实际 ${JSON.stringify(bounded.map((group) => group.id))}）`,
  )
})

addCase('dropEdgesForNodes 命中源或目标就删', () => {
  const edges = [
    wireEdge('e1', 'n1', 'out', 'n2', 'in'),
    wireEdge('e2', 'n2', 'out', 'n3', 'in'),
    wireEdge('e3', 'n3', 'out', 'n4', 'in'),
  ]
  const kept = dropEdgesForNodes(edges, ['n2'])
  assertDeepEqual(kept.map((edge) => edge.id), ['e3'], '命中源或目标的边都应删除')
})

addCase('nodeBoxes / unitBox / selectionBox 尺寸与递归合并', () => {
  const sized = compNode('n1', { x: 10, y: 20 })
  sized.dimensions = { width: 300, height: 150 }
  const nodes = [
    sized,
    compNode('n2', { x: 100, y: 200 }),
    cardNode('g3', { x: 0, y: 0 }),
    { id: 'n9', type: 'comp' },
  ]
  const boxes = nodeBoxes(nodes)
  assertDeepEqual(boxes.get('n1'), { x: 10, y: 20, width: 300, height: 150 }, '用真实尺寸')
  assertDeepEqual(boxes.get('n2'), { x: 100, y: 200, width: 280, height: 200 }, '组件兜底尺寸')
  assertDeepEqual(boxes.get('g3'), { x: 0, y: 0, width: 240, height: 140 }, '组卡片兜底尺寸')
  check(!boxes.has('n9'), '没有 position 的节点不进尺寸表')

  const groups = [grp('g2', ['n1', 'n2']), grp('g3', ['n1'], { collapsed: true })]
  assertDeepEqual(
    unitBox('g2', groups, boxes),
    { x: 10, y: 20, width: 370, height: 380 },
    '展开组应递归合并成员包围盒',
  )
  assertDeepEqual(unitBox('g3', groups, boxes), boxes.get('g3'), '折叠组直接用卡片框')
  assertDeepEqual(
    selectionBox(['g2'], groups, boxes),
    { x: 10, y: 20, width: 370, height: 380 },
    'selectionBox 复用 unitBox',
  )
})

addCase('groupPositions / serializeGroups 只写认识的字段', () => {
  const positions = groupPositions([
    cardNode('g1', { x: 1, y: 2 }),
    frameNode('g2'),
    { id: 'g3', type: 'group' },
  ])
  assertDeepEqual(positions, { g1: { x: 1, y: 2 } }, 'groupPositions 只收组卡片')

  const groups = [
    {
      id: 'g1',
      title: '',
      collapsed: true,
      members: ['n1'],
      position: { x: 1, y: 2 },
      foo: 'bar',
    },
    { id: 'g2', title: 'X', members: ['n2'], extra: 1 },
  ]
  assertDeepEqual(
    serializeGroups(groups, { g1: { x: 7, y: 8 } }),
    [
      { id: 'g1', title: '', collapsed: true, members: ['n1'], position: { x: 7, y: 8 } },
      { id: 'g2', title: 'X', collapsed: false, members: ['n2'] },
    ],
    'serializeGroups 只写认识字段并优先用画布位置',
  )
  const badPosition = serializeGroups([grp('g1', ['n1'], { position: { x: 'a', y: 1 } })])
  check(!('position' in badPosition[0]), 'position 非有限值时不写')
})

// ---------------------------------------------------------------------------
// clipboard.js：复制快照与粘贴计划
// ---------------------------------------------------------------------------

function copyFixture() {
  const nodes = [
    compNode('n1', { x: 10, y: 20 }, { deep: { v: 1 } }),
    compNode('n2', { x: 30, y: 40 }),
    compNode('n3', { x: 50, y: 60 }),
    cardNode('g1', { x: 100, y: 200 }),
  ]
  const groups = [
    grp('g1', ['n1', 'g2'], { collapsed: true }),
    grp('g2', ['n2']),
  ]
  const edges = [
    wireEdge('e1', 'n1', 'table', 'n2', 'data'),
    wireEdge('e2', 'n2', 'table', 'n3', 'data'),
  ]
  return { nodes, edges, groups }
}

addCase('collectCopy 折叠组整组复制且字段最小化', () => {
  const fixture = copyFixture()
  const snapshot = collectCopy({ ...fixture, selectedIds: ['g1'] })
  assertDeepEqual(snapshot.nodes.map((node) => node.id), ['n1', 'n2'], '应复制组内全部节点')
  assertDeepEqual(snapshot.groups.map((group) => group.id), ['g1', 'g2'], '应带上嵌套组')
  assertDeepEqual(snapshot.edges.map((edge) => edge.source), ['n1'], '只收两端都在拷贝集合里的边')
  for (const node of snapshot.nodes) {
    assertDeepEqual(
      Object.keys(node),
      ['id', 'position', 'plugin', 'component', 'config'],
      '节点快照字段必须最小',
    )
  }
  for (const edge of snapshot.edges) {
    assertDeepEqual(
      Object.keys(edge),
      ['source', 'target', 'sourceHandle', 'targetHandle'],
      '边快照字段必须最小',
    )
  }
  assertDeepEqual(
    Object.keys(snapshot.groups[0]),
    ['id', 'title', 'collapsed', 'members', 'position'],
    '组快照字段必须最小（有卡片位置时才带 position）',
  )
  check(
    !('position' in snapshot.groups[1]),
    '没有卡片位置的组不应带 position',
  )

  const inner = collectCopy({ ...fixture, selectedIds: ['n1'] })
  assertDeepEqual(inner.nodes.map((node) => node.id), ['n1', 'n2'], '只选组内节点也复制整个组')
  assertDeepEqual(inner.groups.map((group) => group.id), ['g1', 'g2'], '吸附复制应有的组')
})

addCase('planPaste 新 id、偏移与深层 config 独立', () => {
  const fixture = copyFixture()
  const snapshot = collectCopy({ ...fixture, selectedIds: ['g1'] })
  const plan = planPaste(snapshot, {
    nodes: [compNode('n5', { x: 0, y: 0 })],
    groups: [grp('g5', ['n5'])],
  })
  assertDeepEqual(plan.nodes.map((node) => node.id), ['n6', 'n7'], '节点 id 应全新')
  assertDeepEqual(plan.groups.map((group) => group.id), ['g6', 'g7'], '组 id 应全新')
  assertDeepEqual(plan.nodes[0].position, { x: 50, y: 60 }, '坐标整体偏移 40,40')
  assertDeepEqual(plan.nodes[1].position, { x: 70, y: 80 }, '第二个节点同样偏移')

  check(plan.nodes[0].config !== snapshot.nodes[0].config, 'config 不应共享引用')
  plan.nodes[0].config.deep.v = 99
  check(snapshot.nodes[0].config.deep.v === 1, '改副本不应影响源快照')
  snapshot.nodes[0].config.deep.v = 2
  check(plan.nodes[0].config.deep.v === 99, '改源也不应影响已粘贴的副本')

  assertDeepEqual(
    plan.groups.find((group) => group.id === 'g6').members,
    ['n6', 'g7'],
    '外层组 members 应重映射到新内层组',
  )
  assertDeepEqual(
    plan.groups.find((group) => group.id === 'g7').members,
    ['n7'],
    '内层组 members 应重映射到新节点',
  )
  check(plan.groups.find((group) => group.id === 'g6').collapsed === true, '折叠态应原样保留')
  check(plan.groups.find((group) => group.id === 'g7').collapsed === false, '展开态应原样保留')

  const existingGroups = fixture.groups
  for (const group of plan.groups) {
    check(
      parentOf(existingGroups, group.id) === null,
      `粘贴出的组不应挂在现有组下：${group.id}`,
    )
  }
  const combined = [...existingGroups, ...plan.groups]
  check(parentOf(combined, 'g6') === null, '粘贴出的最外层组应落在 root')

  assertDeepEqual(plan.edges.map((edge) => edge.id), ['e-n7-data'], '边 id 应按新 target 重算')
  const pastedEdge = plan.edges[0]
  check(
    pastedEdge.source === 'n6' &&
      pastedEdge.sourceHandle === 'table' &&
      pastedEdge.target === 'n7' &&
      pastedEdge.targetHandle === 'data',
    `边端点应换成新节点 id：${JSON.stringify(pastedEdge)}`,
  )
})

addCase('planPaste 连续粘贴两批 id 不重叠', () => {
  const fixture = copyFixture()
  const snapshot = collectCopy({ ...fixture, selectedIds: ['g1'] })
  const first = planPaste(snapshot, {
    nodes: [compNode('n5', { x: 0, y: 0 })],
    groups: [grp('g5', ['n5'])],
  })
  const second = planPaste(snapshot, {
    nodes: [...fixture.nodes, ...first.nodes],
    groups: [...fixture.groups, ...first.groups],
  })
  const firstIds = new Set([
    ...first.nodes.map((node) => node.id),
    ...first.groups.map((group) => group.id),
  ])
  for (const id of [...second.nodes.map((node) => node.id), ...second.groups.map((group) => group.id)]) {
    check(!firstIds.has(id), `第二批 id 与第一批重叠：${id}`)
  }
})

addCase('addition groups 非数组与坏条目被忽略', () => {
  const notArray = readAddition({
    addition: { client: 'workflow-studio', version: 1, groups: 'nope' },
  })
  assertDeepEqual(notArray.groups, [], 'groups 不是数组时读成空数组')

  const mixed = readAddition({
    addition: {
      client: 'workflow-studio',
      version: 1,
      groups: [
        { title: '缺 id' },
        { id: 5, title: 'id 不是字符串' },
        { id: 'g1', title: '坐标坏', position: { x: 'a', y: null } },
        { id: 'g2', title: '正常', collapsed: true, members: ['n1'] },
      ],
    },
  })
  assertDeepEqual(mixed.groups.map((group) => group.id), ['g1', 'g2'], '缺字符串 id 的条目应被丢弃')
  check(!('position' in mixed.groups[0]), '坏坐标应被去掉而不是整条丢弃')
  assertDeepEqual(mixed.groups[1].members, ['n1'], '正常条目原样保留')
})

addCase('buildWorkflow 过滤 group/frame 卡片节点', () => {
  const nodes = [
    compNode('n1', { x: 1, y: 2 }, { path: 'data.csv' }),
    compNode('n2', { x: 3, y: 4 }),
    cardNode('g1', { x: 0, y: 0 }),
    frameNode('g2'),
  ]
  const workflow = buildWorkflow({
    name: 'groups',
    nodes,
    edges: [wireEdge('e1', 'n1', 'table', 'n2', 'model')],
    envRows: [],
    addition: null,
  })
  assertDeepEqual(workflow.nodes.map((node) => node.id), ['n1', 'n2'], '导出的 nodes 不应含组卡片/框')
  assertDeepEqual(
    workflow.nodes[1].inputs,
    { model: { from: 'n1', port: 'table' } },
    'inputs 只指向真实组件节点',
  )
  assertDeepEqual(
    Object.keys(workflow.addition.positions),
    ['n1', 'n2'],
    'addition.positions 也不应含组卡片/框',
  )
})

// ---------------------------------------------------------------------------
// Reviewer 回归：嵌套折叠投影、导入丢边、id 契约、畸形环、api 错误
// ---------------------------------------------------------------------------

addCase('projectGraph 嵌套折叠：外层组吸收内层端点', () => {
  const n1 = compNode('n1', { x: 10, y: 10 })
  n1.data.outPorts = [{ name: 'out', type: 'std_1.0@table', color: '#111' }]
  n1.data.inPorts = [{ name: 'in', types: ['std_1.0@table'], color: '#222' }]
  const n2 = compNode('n2', { x: 20, y: 20 })
  n2.data.inPorts = [{ name: 'in', types: ['std_1.0@table'], color: '#222' }]
  const n9 = compNode('n9', { x: 900, y: 10 })
  n9.data.inPorts = [{ name: 'in', types: ['std_1.0@table'], color: '#222' }]
  const nodes = [n1, n2, n9]
  const edges = [
    wireEdge('e1', 'n1', 'out', 'n9', 'in'),
    wireEdge('e2', 'n1', 'out', 'n2', 'in'),
  ]

  const collapsed = projectGraph({
    nodes,
    edges,
    groups: [
      grp('G', ['H', 'n2'], { collapsed: true }),
      grp('H', ['n1'], { collapsed: true }),
    ],
  })
  check(
    collapsed.edges.length === 1,
    `组内边应被丢弃、只留跨出 G 的边：${JSON.stringify(collapsed.edges)}`,
  )
  const edge = collapsed.edges[0]
  check(
    edge.source === 'G' && edge.sourceHandle === 'n1:out' && edge.target === 'n9',
    `端点应换成最外层折叠组 G：${JSON.stringify(edge)}`,
  )
  const gCard = collapsed.nodes.find((node) => node.id === 'G')
  assertDeepEqual(
    gCard.data.outPorts.map((port) => port.name),
    ['n1:out'],
    'G 卡片应带边界输出端口',
  )
  assertDeepEqual(gCard.data.inPorts, [], 'G 卡片不应有幽灵入端口')

  const onlyInner = projectGraph({
    nodes,
    edges,
    groups: [grp('G', ['H', 'n2']), grp('H', ['n1'], { collapsed: true })],
  })
  check(
    onlyInner.edges[0].source === 'H' && onlyInner.edges[0].sourceHandle === 'n1:out',
    `只折叠 H 时端点应是 H：${JSON.stringify(onlyInner.edges[0])}`,
  )
})

addCase('planImport 丢边写入 skipped 并定位到节点端口', async () => {
  const { planImport } = await loadImport()
  const options = layoutOptions([loadCsvEntry(), predictEntry()])
  const base = {
    name: 'skip',
    nodes: [
      { id: 'n1', plugin: 'fileio', component: 'LoadCSV', config: { path: 'd.csv' }, inputs: {} },
      { id: 'n2', plugin: 'core', component: 'PredictModel', config: {}, inputs: {} },
    ],
  }
  const scenarios = [
    ['n2.model', { model: { from: 'ghost', port: 'table' } }, '来源节点 ghost 不存在'],
    ['n2.bogus', { bogus: { from: 'n1', port: 'table' } }, '组件没有输入端口 bogus'],
    ['n2.data', { data: { from: 'n1', port: 'nope' } }, '没有输出端口 nope'],
  ]
  for (const [where, inputs, reason] of scenarios) {
    const raw = JSON.parse(JSON.stringify(base))
    raw.nodes[1].inputs = inputs
    const plan = planImport(raw, options)
    check(
      plan.skipped.length === 1,
      `${where} 应只跳过一条：${JSON.stringify(plan.skipped)}`,
    )
    check(
      plan.skipped[0].startsWith(where),
      `${where} 应定位到 节点id.端口：${plan.skipped[0]}`,
    )
    check(plan.skipped[0].includes(reason), `${where} 消息缺少原因：${plan.skipped[0]}`)
  }
})

addCase('parseHandle 支持带冒号的节点 id', () => {
  assertDeepEqual(
    parseHandle('a:b:out'),
    { nodeId: 'a:b', port: 'out' },
    '应按最后一个冒号切分',
  )
  check(parseHandle('a:b:') === null, '尾部冒号应返回 null')
  check(parseHandle(':x') === null, '开头冒号应返回 null')
})

addCase('nextGroupId 同时避开节点 id', () => {
  check(nextGroupId([], [{ id: 'g1' }]) === 'g2', '应避开节点里已用的 g1')
  check(nextGroupId([{ id: 'g1' }]) === 'g2', '只传 groups 时保持旧行为')
})

addCase('畸形环 frameItems / memberLeaves 有界返回', () => {
  const groups = [grp('A', ['B']), grp('B', ['A'])]
  const items = frameItems(groups, 'A')
  check(Array.isArray(items), `frameItems 应返回数组：${JSON.stringify(items)}`)
  const leaves = memberLeaves(groups, 'A')
  check(Array.isArray(leaves), `memberLeaves 应返回数组：${JSON.stringify(leaves)}`)
})

function jsonResponse(status, payload) {
  return { ok: status < 400, status, text: async () => JSON.stringify(payload) }
}

async function withFetchStub(stub, fn) {
  const original = globalThis.fetch
  globalThis.fetch = stub
  try {
    return await fn()
  } finally {
    globalThis.fetch = original
  }
}

addCase('api.js 500 错误响应都 reject 且带后端消息', async () => {
  const stub = async () => jsonResponse(500, { ok: false, errors: ['boom'] })
  const calls = [
    ['fetchHealth', () => fetchHealth()],
    ['fetchPlugins', () => fetchPlugins()],
    ['runWorkflow', () => runWorkflow({ nodes: [] })],
  ]
  for (const [name, call] of calls) {
    let message = ''
    try {
      await withFetchStub(stub, call)
    } catch (err) {
      message = err.message
    }
    check(message.includes('boom'), `${name} 应 reject 且消息含 boom：${message}`)
  }
})

addCase('api.js 200 合法响应正常 resolve', async () => {
  const health = await withFetchStub(
    async () => jsonResponse(200, { ok: true, engine: '1.0', plugins: 1, components: 2 }),
    () => fetchHealth(),
  )
  check(health.ok === true && health.components === 2, `health 应正常返回：${JSON.stringify(health)}`)

  const plugins = await withFetchStub(
    async () =>
      jsonResponse(200, {
        plugins: [{ name: 'core', version: '1.0', title: '基础', types: [], components: [] }],
      }),
    () => fetchPlugins(),
  )
  check(
    plugins.plugins.length === 1 && plugins.plugins[0].name === 'core',
    `plugins 应正常返回：${JSON.stringify(plugins.plugins)}`,
  )

  const run = await withFetchStub(
    async () =>
      jsonResponse(200, {
        ok: true,
        errors: [],
        warnings: [],
        order: ['n1'],
        nodes: [{ id: 'n1', component: 'fileio.LoadCSV', ms: 1, outputs: { table: 't' }, error: null }],
      }),
    () => runWorkflow({ nodes: [] }),
  )
  check(run.failedIds.length === 0, 'runWorkflow 应标记无失败节点')
  check(
    run.nodes[0].failed === false && run.nodes[0].outputs[0].port === 'table',
    `runWorkflow 应转换 nodes：${JSON.stringify(run.nodes)}`,
  )
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
