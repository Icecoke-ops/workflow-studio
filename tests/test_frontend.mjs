// 前端纯函数测试：直接 import frontend/src 下的 ESM 模块，不依赖 Vue 运行时。
// 运行：node tests/test_frontend.mjs

import { envToRows, rowsToEnv, envError, attachEnv } from '../frontend/src/workflow.js'
import { cloneDefault, defaultsFor, buildWorkflow } from '../frontend/src/model.js'
import { readAddition } from '../frontend/src/addition.js'
import {
  isComponentNode,
  parentOf,
  parseHandle,
  resolveConnection,
  connectionAllowed,
  projectEdges,
  projectGraph,
  frameItems,
  memberLeaves,
  selectionUnits,
  commonParent,
  canGroup,
  nextGroupId,
  createGroup,
  dissolveGroup,
  setCollapsed,
  renameGroup,
  pruneGroups,
  dropEdgesForNodes,
  nodeBoxes,
  unitBox,
  selectionBox,
  groupPositions,
  serializeGroups,
} from '../frontend/src/groups.js'
import { collectCopy, planPaste } from '../frontend/src/clipboard.js'
import {
  normalizePath,
  joinPath,
  parentPath,
  titleFromPath,
  isFlowPath,
  newFlowText,
} from '../frontend/src/documents.js'
import { normalizeProject } from '../frontend/src/project.js'
import {
  fetchHealth,
  fetchPlugins,
  runWorkflow,
  fetchProject,
  fetchTree,
  fetchFile,
  writeFile,
  makeDir,
  renamePath,
  deletePath,
} from '../frontend/src/api.js'

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
  check(
    plan.prunedGroups === 0 && plan.trimmedMembers === 0,
    `正常文件不应裁分组：pruned=${plan.prunedGroups} trimmed=${plan.trimmedMembers}`,
  )

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

addCase('planImport 分组：部分成员失效只裁成员', async () => {
  const { planImport } = await loadImport()
  const plan = planImport(
    {
      name: 'trim',
      nodes: [
        { id: 'n1', plugin: 'fileio', component: 'LoadCSV', config: {}, inputs: {} },
      ],
      addition: {
        client: 'workflow-studio',
        version: 1,
        groups: [{ id: 'g1', title: '局部失效', members: ['n1', 'n2'] }],
      },
    },
    layoutOptions([loadCsvEntry()]),
  )
  check(plan.prunedGroups === 0, `部分失效不应丢组，实际 ${plan.prunedGroups}`)
  check(plan.trimmedMembers === 1, `应裁掉 1 个不存在的成员，实际 ${plan.trimmedMembers}`)
  check(plan.groups.length === 1, `应保留 g1：${JSON.stringify(plan.groups)}`)
  check(plan.groups[0].id === 'g1', `保留的组 id 不对：${plan.groups[0].id}`)
  assertDeepEqual(plan.groups[0].members, ['n1'], 'g1 只应剩存在的 n1')
})

addCase('planImport 分组：整组失效被丢弃且不计入 trimmedMembers', async () => {
  const { planImport } = await loadImport()
  const plan = planImport(
    {
      name: 'prune',
      nodes: [
        { id: 'n1', plugin: 'fileio', component: 'LoadCSV', config: {}, inputs: {} },
      ],
      addition: {
        client: 'workflow-studio',
        version: 1,
        groups: [
          { id: 'g1', title: '仍有效', members: ['n1', 'n2'] },
          { id: 'g2', title: '整组失效', members: ['n9'] },
        ],
      },
    },
    layoutOptions([loadCsvEntry()]),
  )
  check(plan.prunedGroups === 1, `应丢 1 个整组，实际 ${plan.prunedGroups}`)
  check(
    plan.trimmedMembers === 1,
    `整组丢掉的成员不应算进 trimmedMembers，实际 ${plan.trimmedMembers}`,
  )
  assertDeepEqual(plan.groups.map((group) => group.id), ['g1'], '只剩仍有效的 g1')
})

addCase('planImport droppedGroups 与 prunedGroups 互不吞并', async () => {
  const { planImport } = await loadImport()
  const plan = planImport(
    {
      name: 'both',
      nodes: [
        { id: 'n1', plugin: 'fileio', component: 'LoadCSV', config: {}, inputs: {} },
      ],
      addition: {
        client: 'workflow-studio',
        version: 1,
        groups: [
          { id: 'n1', title: '撞节点 id', members: ['n9'] },
          { id: 'g1', title: '正常', members: ['n1'] },
          { id: 'g2', title: '整组失效', members: ['n9'] },
        ],
      },
    },
    layoutOptions([loadCsvEntry()]),
  )
  check(plan.droppedGroups === 1, `撞节点 id 的组应计入 droppedGroups，实际 ${plan.droppedGroups}`)
  check(plan.prunedGroups === 1, `只有 g2 应计入 prunedGroups，实际 ${plan.prunedGroups}`)
  check(
    plan.trimmedMembers === 0,
    `被 droppedGroups 丢掉的组里的成员不应再算 trimmedMembers，实际 ${plan.trimmedMembers}`,
  )
  assertDeepEqual(plan.groups.map((group) => group.id), ['g1'], '只剩 g1')
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
    [{ name: 'n1:out', type: 'std_1.0@table', color: '#111', label: 'n1.out', title: '' }],
    '同一端口的边只出现一次',
  )
  assertDeepEqual(
    byId.g1.data.inPorts,
    [{ name: 'n1:in', types: ['std_1.0@table'], color: '#222', label: 'n1.in', title: '' }],
    '入端口同样按新端口模型给出',
  )
})

addCase('projectGraph 新端口模型：空闲端口全集、内部占用与跨边界并集', () => {
  const make = (id, title, inPorts, outPorts) => {
    const node = compNode(id)
    node.data.title = title
    node.data.inPorts = inPorts
    node.data.outPorts = outPorts
    return node
  }
  const input = (name) => ({ name, types: ['T'], color: '#in' })
  const output = (name) => ({ name, type: 'T', color: '#out' })
  const a = make('a', 'A', [input('data')], [output('out'), output('out2')])
  const b = make('b', 'B', [input('data')], [output('out')])
  const x = make('x', 'X', [input('in')], [])
  const edges = [
    wireEdge('e1', 'a', 'out', 'b', 'data'),
    wireEdge('e2', 'a', 'out', 'x', 'in'),
  ]
  const result = projectGraph({
    nodes: [a, b, x],
    edges,
    groups: [grp('g', ['a', 'b'], { collapsed: true })],
  })
  const card = result.nodes.find((node) => node.id === 'g')
  assertDeepEqual(
    card.data.inPorts.map((port) => port.name),
    ['a:data'],
    '被内部边喂过的 b:data 不出现，空闲的 a:data 出现',
  )
  assertDeepEqual(
    card.data.outPorts.map((port) => port.name),
    ['a:out2', 'b:out', 'a:out'],
    '空闲输出 + 跨边界输出取并集，a:out 虽喂内部仍保留',
  )
  check(card.data.outPorts[2].label === 'A.out', '端口标签用组件标题.端口名')
  check(
    card.data.outPorts[2].type === 'T',
    '端口类型沿用真实端口',
  )
  const boundary = result.edges[0]
  check(
    boundary.source === 'g' && boundary.sourceHandle === 'a:out' && boundary.target === 'x',
    '跨边界边仍投影成卡片端口到外部节点',
  )

  const c = make('c', 'C', [input('data')], [output('out')])
  const d = make('d', 'D', [input('data')], [output('out')])
  const disconnected = projectGraph({
    nodes: [c, d],
    edges: [],
    groups: [grp('g2', ['c', 'd'], { collapsed: true })],
  }).nodes.find((node) => node.id === 'g2')
  assertDeepEqual(
    disconnected.data.inPorts.map((port) => port.name),
    ['c:data', 'd:data'],
    '互不相连的成员也露出全部输入端口',
  )
  assertDeepEqual(
    disconnected.data.outPorts.map((port) => port.name),
    ['c:out', 'd:out'],
    '互不相连的成员也露出全部输出端口',
  )

  const e = make('e', 'E', [], [output('out')])
  const f = make('f', 'F', [input('data')], [])
  const internal = projectGraph({
    nodes: [e, f],
    edges: [wireEdge('e3', 'e', 'out', 'f', 'data')],
    groups: [grp('g3', ['e', 'f'], { collapsed: true })],
  }).nodes.find((node) => node.id === 'g3')
  assertDeepEqual(internal.data.inPorts, [], '内部边喂住的输入端口不上卡片')
  assertDeepEqual(internal.data.outPorts, [], '只喂内部的输出端口不上卡片')
})

addCase('projectGraph 嵌套组端口穿透到内层组件', () => {
  const node = compNode('n1')
  node.data.title = '叶子'
  node.data.inPorts = [{ name: 'data', types: ['T'], color: '#1' }]
  node.data.outPorts = [{ name: 'out', type: 'T', color: '#2' }]
  const collapsed = projectGraph({
    nodes: [node],
    edges: [],
    groups: [
      grp('outer', ['inner'], { collapsed: true }),
      grp('inner', ['n1'], { collapsed: true }),
    ],
  })
  const outer = collapsed.nodes.find((item) => item.id === 'outer')
  const inner = collapsed.nodes.find((item) => item.id === 'inner')
  assertDeepEqual(
    outer.data.inPorts.map((port) => port.label),
    ['叶子.data'],
    '外层端口穿透到内层组件',
  )
  assertDeepEqual(
    inner.data.inPorts.map((port) => port.label),
    ['叶子.data'],
    '内层卡片按自己的叶子集合计算端口',
  )
  check(inner.hidden === true, '外层折叠时内层卡片隐藏')

  const expanded = projectGraph({
    nodes: [node],
    edges: [],
    groups: [grp('outer', ['inner']), grp('inner', ['n1'], { collapsed: true })],
  }).nodes.find((item) => item.id === 'inner')
  check(expanded.hidden === false, '外层展开时内层卡片可见')
  assertDeepEqual(
    expanded.data.outPorts.map((port) => port.label),
    ['叶子.out'],
    '内层卡片仍按自己的叶子集合计算端口',
  )
})

addCase('connectionAllowed 返回解析后的连接，不兼容时为 null', () => {
  const a = compNode('a')
  a.data.inPorts = [{ name: 'data', types: ['table'], color: '#1' }]
  a.data.outPorts = [{ name: 'out', type: 'table', color: '#2' }]
  const x = compNode('x')
  x.data.inPorts = [{ name: 'in', types: ['table'], color: '#3' }]
  x.data.outPorts = [{ name: 'out', type: 'model', color: '#4' }]
  const nodes = [a, x]
  const groups = [grp('g', ['a'])]
  assertDeepEqual(
    connectionAllowed(nodes, groups, {
      source: 'a', sourceHandle: 'out', target: 'x', targetHandle: 'in',
    }),
    { source: 'a', sourceHandle: 'out', target: 'x', targetHandle: 'in' },
    '组内 -> 组外应返回解析后的连接',
  )
  check(
    connectionAllowed(nodes, groups, {
      source: 'x', sourceHandle: 'out', target: 'a', targetHandle: 'data',
    }) === null,
    'model -> table 类型不兼容应返回 null',
  )
  check(
    connectionAllowed(nodes, groups, {
      source: 'a', sourceHandle: 'out', target: 'a', targetHandle: 'data',
    }) === null,
    '自己连自己应返回 null',
  )
  const collapsed = [grp('g', ['a'], { collapsed: true })]
  assertDeepEqual(
    connectionAllowed(nodes, collapsed, {
      source: 'g', sourceHandle: 'a:out', target: 'x', targetHandle: 'in',
    }),
    { source: 'a', sourceHandle: 'out', target: 'x', targetHandle: 'in' },
    '组卡片端口应解析回真实节点后返回',
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
  // 两个字段缺一不可：显式 0×0 覆盖 Object.assign 复用节点残留的旧尺寸，并让 fitView 跳过
  check(
    frame.dimensions?.width === 0 && frame.dimensions?.height === 0,
    `frame 必须显式 0×0：既让 fitView 跳过，又覆盖复用节点残留的旧尺寸：${JSON.stringify(frame.dimensions)}`,
  )
  // 0×0 会被 Vue Flow 写成 visibility:hidden，可见性靠 style 覆盖
  check(
    frame.style?.visibility === 'visible',
    `frame 必须用 style.visibility 覆盖可见性，否则 0×0 的框会被隐藏：${JSON.stringify(frame.style)}`,
  )
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

addCase('commonParent / canGroup 判定', () => {
  const groups = [grp('g1', ['n1', 'n2', 'g2', 'g3']), grp('g2', ['n5']), grp('g3', ['n6'])]
  check(commonParent(groups, ['n1', 'n2']) === 'g1', '同父应返回该父组')
  check(commonParent(groups, ['n7', 'n8']) === null, 'root 层同父返回 null')
  check(commonParent(groups, ['n1', 'n7']) === undefined, '不同父应返回 undefined')
  check(canGroup(groups, ['n7', 'n8']) === true, '同父两个单元可以建组')
  check(canGroup(groups, ['g2', 'g3']) === true, '同父的两个子组可以再建组')
  check(canGroup(groups, ['n7']) === false, '单个单元不能建组')
  check(canGroup(groups, ['g2', 'n1']) === false, '不同父不能建组')
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

addCase('renameGroup 只改目标组标题并返回新数组', () => {
  const groups = [
    grp('g1', ['n1'], { title: '旧名', position: { x: 1, y: 2 } }),
    grp('g2', ['n2']),
  ]
  const snapshot = JSON.parse(JSON.stringify(groups))
  const next = renameGroup(groups, 'g1', '  回归 模型  ')
  check(next !== groups, '应返回新数组')
  assertDeepEqual(
    next[0],
    { id: 'g1', title: '回归 模型', collapsed: false, members: ['n1'], position: { x: 1, y: 2 } },
    '目标组只换标题（trim 后保留中间空格），其它字段原样',
  )
  check(next[1] === groups[1], '其它组应是原对象')
  assertDeepEqual(groups, snapshot, '入参数组不能被修改')
})

addCase('renameGroup 空标题返回原数组', () => {
  const groups = [grp('g1', ['n1']), grp('g2', ['n2'])]
  check(renameGroup(groups, 'g1', '') === groups, '空串应返回原数组引用')
  check(renameGroup(groups, 'g1', '   ') === groups, '全空白应返回原数组引用')
  assertDeepEqual(groups.map((group) => group.title), ['g1', 'g2'], '标题不应变化')
})

addCase('renameGroup 目标不存在时原样返回', () => {
  const groups = [grp('g1', ['n1']), grp('g2', ['n2'])]
  const next = renameGroup(groups, 'g9', '新名')
  // 实际行为：走 map，所以是新数组；元素与输入同一批对象，没有组被改名。
  assertDeepEqual(next.map((group) => group.title), ['g1', 'g2'], '没有组被改名')
  check(next.length === groups.length, `长度不变：${next.length}`)
  check(next.every((group, index) => group === groups[index]), '元素应是原对象')
  check(next !== groups, '实际返回新数组（map 语义）')
})

addCase('renameGroup 往返：导出后 addition 标题是新名且版本仍为 1', () => {
  const groups = [grp('g1', ['n1', 'n2'], { title: '旧名' }), grp('g2', ['n3'])]
  const renamed = renameGroup(groups, 'g1', '  回归 模型  ')
  const nodes = [
    compNode('n1', { x: 1, y: 2 }),
    compNode('n2', { x: 3, y: 4 }),
    compNode('n3', { x: 5, y: 6 }),
  ]
  const workflow = buildWorkflow({
    name: 'rename-roundtrip',
    nodes,
    edges: [],
    envRows: [],
    addition: null,
    groups: serializeGroups(renamed),
  })
  const addition = readAddition(workflow)
  assertDeepEqual(
    addition.groups.map((group) => group.title),
    ['回归 模型', 'g2'],
    '读回的 groups 标题应是新名',
  )
  check(workflow.addition.version === 1, `导出 addition 版本应仍为 1：${workflow.addition.version}`)
  check(workflow.addition.client === 'workflow-studio', '导出 addition 客户端不变')
})

addCase('renameGroup 标题截断 40 字且先 trim', () => {
  const groups = [grp('g1', ['n1'])]
  const sixty = '回'.repeat(60)
  const next = renameGroup(groups, 'g1', sixty)
  check(next[0].title.length === 40, `应截成 40 个字，实际 ${next[0].title.length}`)
  check(next[0].title === sixty.slice(0, 40), '应是前 40 个字符')
  check(
    Buffer.byteLength(next[0].title, 'utf8') === 120,
    `按字符截断：40 个汉字应是 120 字节，实际 ${Buffer.byteLength(next[0].title, 'utf8')}`,
  )

  const padded = `  ${'编'.repeat(45)}  `
  const trimmed = renameGroup(groups, 'g1', padded)
  check(trimmed[0].title === '编'.repeat(40), '首尾空白不占 40 个字额度')
  check(trimmed[0].title === trimmed[0].title.trim(), '结果本身没有首尾空白')

  check(renameGroup(groups, 'g1', '') === groups, '空串仍返回原数组引用')
  check(renameGroup(groups, 'g1', '   ') === groups, '全空白仍返回原数组引用')
})

addCase('renameGroup 按码点截断，不劈开代理对', () => {
  const loneSurrogate =
    /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/
  const rename = (title) => renameGroup([grp('g1', ['n1'])], 'g1', title)[0].title
  const roundtrip = (value) => JSON.parse(JSON.stringify({ value })).value

  // 自检判据本身：被劈开的 emoji 必须能检出孤立高代理项。
  check(loneSurrogate.test('x' + '😀'.slice(0, 1)), '自检：孤立高代理项应被检出')

  const fits = rename('a'.repeat(39) + '😀')
  check(Array.from(fits).length === 40, `应是 40 个码点，实际 ${Array.from(fits).length}`)
  check(fits.length === 41, `UTF-16 长度应为 41，实际 ${fits.length}`)
  check(fits.endsWith('😀'), '第 40 个码点的 emoji 应完整保留')
  check(!loneSurrogate.test(fits), '不应出现孤立代理项')
  check(roundtrip(fits) === fits, 'JSON 往返后仍是同一个字符')

  const cut = rename('a'.repeat(40) + '😀')
  check(Array.from(cut).length === 40, `应是 40 个码点，实际 ${Array.from(cut).length}`)
  check(cut === 'a'.repeat(40), `第 41 个码点（emoji）应整个被砍掉，实际 ${JSON.stringify(cut)}`)
  check(!loneSurrogate.test(cut), '不应出现孤立代理项')

  const emojis = rename('😀'.repeat(45))
  check(Array.from(emojis).length === 40, `应截成 40 个码点，实际 ${Array.from(emojis).length}`)
  check(emojis === '😀'.repeat(40), '应是 40 个完整 emoji，不是 20 个')
  check(emojis.length === 80, `UTF-16 长度应为 80，实际 ${emojis.length}`)
  check(!loneSurrogate.test(emojis), '不应出现孤立代理项')
  check(roundtrip(emojis) === emojis, 'JSON 往返后仍是同一串')
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

addCase('删除子图组合：叶子 + 删边 + prune', () => {
  const groups = [grp('A', ['nA', 'B']), grp('B', ['nB', 'C']), grp('C', ['nC'])]
  const nodes = [compNode('nA'), compNode('nB'), compNode('nC'), compNode('n8'), compNode('n9')]
  const edges = [
    wireEdge('e1', 'nC', 'out', 'n9', 'in'), // 跨 A 边界
    wireEdge('e2', 'nA', 'out', 'nC', 'in'), // A 内部
    wireEdge('e3', 'n9', 'out', 'n8', 'in'), // 完全在 A 外
  ]
  const remaining = (leaves) => nodes.filter((node) => !leaves.includes(node.id))

  // 删 A：A/B/C 三组一起走
  const leavesA = memberLeaves(groups, 'A').map((leaf) => leaf.nodeId).sort()
  assertDeepEqual(leavesA, ['nA', 'nB', 'nC'], 'A 的叶子是 A/B/C 里的全部组件')
  assertDeepEqual(
    dropEdgesForNodes(edges, leavesA).map((edge) => edge.id),
    ['e3'],
    '只剩 A 外那条边',
  )
  assertDeepEqual(pruneGroups(groups, remaining(leavesA)), [], '组件删空后 groups 为空')

  // 删中间层 B：C 一起走；A 的 members 里 B 被清掉，A 还有 nA 所以留下
  const leavesB = memberLeaves(groups, 'B').map((leaf) => leaf.nodeId).sort()
  assertDeepEqual(leavesB, ['nB', 'nC'], 'B 的叶子含 C 里的组件')
  const prunedB = pruneGroups(groups, remaining(leavesB))
  check(prunedB.length === 1 && prunedB[0].id === 'A', `A 应保留：${JSON.stringify(prunedB)}`)
  assertDeepEqual(prunedB[0].members, ['nA'], 'A 的 members 里 B 被清掉且 A 没变空')
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

addCase('addition 严格校验：空 id、重复 id、撞节点 id 计入 droppedGroups', () => {
  const nodes = [{ id: 'n1' }, { id: 'n2' }]
  const nodeSnapshot = JSON.parse(JSON.stringify(nodes))
  const raw = {
    nodes,
    addition: {
      client: 'workflow-studio',
      version: 1,
      positions: {},
      groups: [
        { id: '', title: '空 id' },
        { id: '   ', title: '全空白 id' },
        { id: 'g1', title: '甲' },
        { id: 'g1', title: '重复的 g1' },
        { id: 'n1', title: '撞节点 id' },
        { id: 'g2', title: '乙' },
      ],
    },
  }
  const result = readAddition(raw)
  assertDeepEqual(
    result.groups.map((group) => group.id),
    ['g1', 'g2'],
    '合法组按原顺序保留，重复 id 首条胜出',
  )
  assertDeepEqual(
    result.groups.map((group) => group.title),
    ['甲', '乙'],
    '保留的应是首条那两条',
  )
  check(result.droppedGroups === 4, `应丢弃 4 条，实际 ${result.droppedGroups}`)
  check(result.warning === '', `合法 addition 不应有 warning：${result.warning}`)
  assertDeepEqual(nodes, nodeSnapshot, '节点列表不受分组校验影响')

  const clean = readAddition({
    nodes,
    addition: { client: 'workflow-studio', version: 1, groups: [{ id: 'g1', title: '甲' }] },
  })
  check(clean.droppedGroups === 0, `全部合法时计数应为 0，实际 ${clean.droppedGroups}`)
})

addCase('addition 严格校验：title 规范化、坏 position 只删字段', () => {
  const raw = {
    addition: {
      client: 'workflow-studio',
      version: 1,
      groups: [
        { id: 5, title: '数字 id' },
        { id: 'g1', title: 5 },
        { id: 'g2', title: null },
        { id: 'g3', title: '  有空格  ', position: 'nope' },
        { id: 'g4', title: '缺 y', position: { x: 1 } },
        { id: 'g5', title: '好坐标', position: { x: 1, y: 2 } },
      ],
    },
  }
  const result = readAddition(raw)
  assertDeepEqual(
    result.groups.map((group) => group.id),
    ['g1', 'g2', 'g3', 'g4', 'g5'],
    '坏 position 不整条丢，数字 id 整条丢',
  )
  check(result.droppedGroups === 1, `只有数字 id 计入丢弃，实际 ${result.droppedGroups}`)
  check(
    typeof result.groups[0].title === 'string' && result.groups[0].title === '5',
    `数字 title 应字符串化：${JSON.stringify(result.groups[0].title)}`,
  )
  check(result.groups[0].title.trim() === '5', 'title 之后可直接 trim 不抛')
  check(
    result.groups[1].title === '',
    `null title 应归一成空串：${JSON.stringify(result.groups[1].title)}`,
  )
  check(!('position' in result.groups[2]), '非对象 position 只删字段')
  check(
    result.groups[2].title === '有空格',
    `title 应 trim：${JSON.stringify(result.groups[2].title)}`,
  )
  check(!('position' in result.groups[3]), '缺 y 的 position 只删字段')
  assertDeepEqual(result.groups[4].position, { x: 1, y: 2 }, '好坐标保留')
  check(result.groups[4].title === '好坐标', '正常组原样')
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
  assertDeepEqual(
    gCard.data.inPorts.map((port) => port.name),
    ['n1:in'],
    'G 卡片应带叶子组件未被内部占用的入端口',
  )

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

// ---- documents.js（项目内相对路径 + 新建流程图文本） ----

addCase('documents normalizePath 统一分隔符并折叠重复 /', () => {
  check(
    normalizePath('docs\\sub//a.flow') === 'docs/sub/a.flow',
    `反斜杠与重复 / 应归一：${normalizePath('docs\\sub//a.flow')}`,
  )
  check(
    normalizePath('  /docs//sub/  ') === 'docs/sub',
    `首尾空白与分隔符应去掉：${normalizePath('  /docs//sub/  ')}`,
  )
})

addCase('documents normalizePath 空值与空串返回空串', () => {
  for (const value of ['', null, undefined]) {
    check(normalizePath(value) === '', `normalizePath(${String(value)}) 应为空串：${normalizePath(value)}`)
  }
})

addCase('documents normalizePath 不消解 ./ 与 ..（越界由后端拒绝）', () => {
  // 盘上实现只做分隔符归一，./ 与 .. 原样保留；这不是越界放行：
  // studio/project.py 的 _rel_parts 会丢掉 "." 段、拒绝 ".." 段。
  check(
    normalizePath('./docs/a.flow') === './docs/a.flow',
    `当前实现不删 ./：${normalizePath('./docs/a.flow')}`,
  )
  check(normalizePath('./') === '.', `当前实现把 ./ 归一成 .：${normalizePath('./')}`)
  check(normalizePath('../evil') === '../evil', `.. 原样保留：${normalizePath('../evil')}`)
  check(
    normalizePath('docs\\..\\a.flow') === 'docs/../a.flow',
    `中间的 .. 原样保留：${normalizePath('docs\\..\\a.flow')}`,
  )
})

addCase('documents joinPath 目录与名字拼接', () => {
  check(joinPath('', 'a.flow') === 'a.flow', `空目录应直接给名字：${joinPath('', 'a.flow')}`)
  check(joinPath('docs', 'a.flow') === 'docs/a.flow', `实际：${joinPath('docs', 'a.flow')}`)
  check(joinPath('docs/', 'a.flow') === 'docs/a.flow', `带尾 / 的目录：${joinPath('docs/', 'a.flow')}`)
  check(joinPath('docs', 'sub/a.flow') === 'docs/sub/a.flow', `实际：${joinPath('docs', 'sub/a.flow')}`)
  check(joinPath('docs', '/a.flow') === 'docs/a.flow', `子名开头的 / 应去掉：${joinPath('docs', '/a.flow')}`)
  check(joinPath('docs\\', 'a.flow') === 'docs/a.flow', `base 的反斜杠应归一：${joinPath('docs\\', 'a.flow')}`)
})

addCase('documents parentPath 根/单层/多层/空串', () => {
  check(parentPath('a.flow') === '', `根层文件应回空串：${parentPath('a.flow')}`)
  check(parentPath('docs/a.flow') === 'docs', `单层：${parentPath('docs/a.flow')}`)
  check(parentPath('docs/sub/a.flow') === 'docs/sub', `多层：${parentPath('docs/sub/a.flow')}`)
  check(parentPath('') === '', `空串：${parentPath('')}`)
  check(parentPath('docs\\sub\\a.flow') === 'docs/sub', `反斜杠应先归一：${parentPath('docs\\sub\\a.flow')}`)
})

addCase('documents titleFromPath 兼容 / 与 \\', () => {
  check(titleFromPath('a.flow') === 'a.flow', `根层：${titleFromPath('a.flow')}`)
  check(titleFromPath('docs/a.flow') === 'a.flow', `正斜杠：${titleFromPath('docs/a.flow')}`)
  check(titleFromPath('docs\\a.flow') === 'a.flow', `反斜杠：${titleFromPath('docs\\a.flow')}`)
  check(titleFromPath('docs/a.flow/') === 'a.flow', `末尾分隔符应忽略：${titleFromPath('docs/a.flow/')}`)
})

addCase('documents isFlowPath 大小写不敏感、只认结尾 .flow', () => {
  check(isFlowPath('a.flow') === true, '.flow 应识别')
  check(isFlowPath('docs/A.FLOW') === true, '大写 .FLOW 应识别')
  check(isFlowPath('a.json') === false, '.json 不应识别')
  check(isFlowPath('aflow') === false, '无后缀不应识别')
  check(isFlowPath('a.flow.bak') === false, '只有以 .flow 结尾才算')
})

addCase('documents newFlowText 合法 JSON、nodes 为空、name 原样', () => {
  const parsed = JSON.parse(newFlowText('demo'))
  assertDeepEqual(parsed, { name: 'demo', nodes: [] }, 'newFlowText 解析结果')
  check(parsed.nodes.length === 0, `nodes 应是空数组：${JSON.stringify(parsed.nodes)}`)
  assertDeepEqual(
    JSON.parse(newFlowText('  spaced  ')),
    { name: '  spaced  ', nodes: [] },
    'name 应原样保留（不 trim）',
  )
  check(newFlowText('').includes('未命名工作流'), '缺省名字应是「未命名工作流」')
})

addCase('documents newFlowText 使用 2 空格缩进', () => {
  const text = newFlowText('x')
  check(text.includes('\n  "name": "x"'), `应是 2 空格缩进：${JSON.stringify(text)}`)
  check(!text.includes('\n    "name"'), '不能是 4 空格缩进')
})

// ---- project.js（/api/project 载荷 -> 工作台项目状态） ----

addCase('project normalizeProject 正常载荷原样转换', () => {
  const state = normalizeProject({
    ok: true,
    root: 'C:\\proj',
    name: 'proj',
    launcher: 'http://127.0.0.1:8765',
  })
  assertDeepEqual(
    state,
    {
      project: { root: 'C:\\proj', name: 'proj', launcher: 'http://127.0.0.1:8765' },
      degraded: false,
      errors: [],
    },
    '正常载荷',
  )
})

addCase('project normalizeProject 同名冲突降级但项目仍可用', () => {
  const state = normalizeProject({
    ok: false,
    root: 'C:\\proj',
    name: 'proj',
    launcher: null,
    errors: ['插件名重复：core（C:\\a\\core.zip 与 C:\\b\\core.zip）'],
  })
  check(state !== null, '冲突载荷有合法 root，不能当成没有项目')
  assertDeepEqual(
    state.project,
    { root: 'C:\\proj', name: 'proj', launcher: null },
    '降级时 project 仍须合法',
  )
  check(state.degraded === true, `ok:false 必须 degraded:true，实际 ${state.degraded}`)
  assertDeepEqual(state.errors, ['插件名重复：core（C:\\a\\core.zip 与 C:\\b\\core.zip）'], 'errors 应保留')
})

addCase('project normalizeProject 非对象载荷返回 null', () => {
  for (const payload of [null, undefined, 0, 'proj', true, []]) {
    check(normalizeProject(payload) === null, `${JSON.stringify(payload)} 应返回 null`)
  }
})

addCase('project normalizeProject root 缺失/空串/非字符串返回 null', () => {
  for (const payload of [{}, { root: '' }, { root: null }, { root: 42 }, { ok: true, name: 'p' }]) {
    check(normalizeProject(payload) === null, `${JSON.stringify(payload)} 应返回 null`)
  }
})

addCase('project normalizeProject name 回落 root、launcher 回落 null', () => {
  const base = { ok: true, root: 'C:\\proj' }
  for (const name of [undefined, '', null, 42]) {
    const state = normalizeProject({ ...base, name })
    check(
      state.project.name === 'C:\\proj',
      `name=${JSON.stringify(name)} 应回落 root，实际 ${JSON.stringify(state.project.name)}`,
    )
  }
  for (const launcher of [undefined, '', null, 42]) {
    const state = normalizeProject({ ...base, launcher })
    check(
      state.project.launcher === null,
      `launcher=${JSON.stringify(launcher)} 应回落 null，实际 ${JSON.stringify(state.project.launcher)}`,
    )
  }
})

addCase('project normalizeProject errors 只留非空字符串、ok 非 false 不降级', () => {
  for (const errors of [undefined, {}, 'boom', 42]) {
    assertDeepEqual(
      normalizeProject({ root: 'r', errors }).errors,
      [],
      `errors=${JSON.stringify(errors)} 应清洗成空数组`,
    )
  }
  assertDeepEqual(
    normalizeProject({ root: 'r', errors: ['a', '', 3, null, 'b'] }).errors,
    ['a', 'b'],
    '只留非空字符串',
  )
  for (const ok of [undefined, true, 0, 'false', null]) {
    check(
      normalizeProject({ root: 'r', ok }).degraded === false,
      `ok=${JSON.stringify(ok)} 不应降级`,
    )
  }
  check(normalizeProject({ root: 'r', ok: false }).degraded === true, 'ok:false 必须降级')
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

/** 记录每次 fetch 的 (url, options)，再回固定响应。 */
function recordingFetch(status, payload) {
  const calls = []
  const stub = async (url, options = {}) => {
    calls.push({ url, options })
    return jsonResponse(status, payload)
  }
  return { calls, stub }
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

// ---- api.js 批 4：项目/文件接口封装（断言 URL / Method / Body） ----

addCase('api.js fetchProject 走 GET /api/project', async () => {
  const { calls, stub } = recordingFetch(200, { ok: true, root: 'C:\\p', name: 'p' })
  const data = await withFetchStub(stub, () => fetchProject())
  check(calls.length === 1, `应只请求一次：${calls.length}`)
  check(calls[0].url === '/api/project', `URL 不对：${calls[0].url}`)
  check(calls[0].options.method === undefined, `应是 GET（不带 method）：${calls[0].options.method}`)
  check(calls[0].options.body === undefined, 'GET 不应带 body')
  check(data.root === 'C:\\p', `响应应原样返回：${JSON.stringify(data)}`)
})

addCase('api.js fetchTree 对 path 做 encodeURIComponent', async () => {
  const { calls, stub } = recordingFetch(200, { ok: true, path: '', entries: [] })
  await withFetchStub(stub, () => fetchTree(''))
  await withFetchStub(stub, () => fetchTree('docs/sub dir/中文.flow'))
  await withFetchStub(stub, () => fetchTree())
  check(calls[0].url === '/api/tree?path=', `空 path 应显式带 path=：${calls[0].url}`)
  check(
    calls[1].url === '/api/tree?path=docs%2Fsub%20dir%2F%E4%B8%AD%E6%96%87.flow',
    `空格/中文/斜杠都必须编码：${calls[1].url}`,
  )
  check(calls[2].url === '/api/tree?path=', `默认参数就是空 path：${calls[2].url}`)
  check(
    calls.every((call) => call.options.method === undefined),
    'fetchTree 应是 GET',
  )
})

addCase('api.js fetchFile 对 path 做 encodeURIComponent', async () => {
  const { calls, stub } = recordingFetch(200, { ok: true, kind: 'text', text: '' })
  await withFetchStub(stub, () => fetchFile('docs/a b.flow'))
  check(calls[0].url === '/api/file?path=docs%2Fa%20b.flow', `URL 不对：${calls[0].url}`)
  check(calls[0].options.method === undefined, 'fetchFile 应是 GET')
})

addCase('api.js writeFile POST JSON {path,text}', async () => {
  const { calls, stub } = recordingFetch(200, { ok: true, path: 'docs/a.flow', size: 7 })
  const text = 'héllo\n世界'
  await withFetchStub(stub, () => writeFile('docs/a.flow', text))
  check(calls[0].url === '/api/file', `URL 不对：${calls[0].url}`)
  check(calls[0].options.method === 'POST', `method 不对：${calls[0].options.method}`)
  check(
    calls[0].options.headers['Content-Type'] === 'application/json',
    `应带 JSON Content-Type：${JSON.stringify(calls[0].options.headers)}`,
  )
  assertDeepEqual(JSON.parse(calls[0].options.body), { path: 'docs/a.flow', text }, 'writeFile body')
})

addCase('api.js makeDir/renamePath/deletePath 字段与后端契约一致', async () => {
  const { calls, stub } = recordingFetch(200, { ok: true, path: 'docs', errors: [] })
  await withFetchStub(stub, () => makeDir('docs/new dir'))
  await withFetchStub(stub, () => renamePath('docs/a.flow', 'b.flow'))
  await withFetchStub(stub, () => deletePath('docs/a.flow'))
  check(calls[0].url === '/api/mkdir', `mkdir URL 不对：${calls[0].url}`)
  check(calls[0].options.method === 'POST', 'mkdir 应是 POST')
  assertDeepEqual(JSON.parse(calls[0].options.body), { path: 'docs/new dir' }, 'makeDir body')
  check(calls[1].url === '/api/rename', `rename URL 不对：${calls[1].url}`)
  check(calls[1].options.method === 'POST', 'rename 应是 POST')
  assertDeepEqual(
    JSON.parse(calls[1].options.body),
    { path: 'docs/a.flow', new_name: 'b.flow' },
    'rename body 必须用 new_name',
  )
  check(calls[2].url === '/api/delete', `delete URL 不对：${calls[2].url}`)
  check(calls[2].options.method === 'POST', 'delete 应是 POST')
  assertDeepEqual(JSON.parse(calls[2].options.body), { path: 'docs/a.flow' }, 'delete body')
})

addCase('api.js 项目接口 500 时 reject 且消息来自后端', async () => {
  const errors = ["路径不能包含 ..：'../x'", '项目未运行']
  const stub = async () => jsonResponse(500, { ok: false, errors })
  let message = ''
  try {
    await withFetchStub(stub, () => fetchTree('../x'))
  } catch (err) {
    message = err.message
  }
  check(message === errors.join('；'), `reject 消息应是后端 errors 用「；」连接：${message}`)
})

addCase('api.js 200 的 ok:false 原样 resolve 给调用方', async () => {
  const payload = { ok: false, errors: ['目录不存在或不是目录：docs'] }
  const data = await withFetchStub(async () => jsonResponse(200, payload), () => fetchTree('docs'))
  assertDeepEqual(data, payload, 'ok:false 的 200 响应应原样 resolve')
})

// ---------------------------------------------------------------------------
// debug 调试模块（frontend/src/debug）
// 按冻结接口写，不照 WIP 实现写；模块缺失时整组跳过并打印 skip。
// ---------------------------------------------------------------------------

const DEBUG_PHASES = ['idle', 'running', 'paused', 'ended', 'failed']

async function importDebugModule(specifier) {
  try {
    return await import(specifier)
  } catch (err) {
    if (err && err.code === 'ERR_MODULE_NOT_FOUND') {
      console.log(`skip  ${specifier}：模块未落地`)
      return null
    }
    throw err
  }
}

class FakeWebSocket {
  static instances = []
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3

  constructor(url) {
    this.url = url
    this.readyState = FakeWebSocket.CONNECTING
    this.sent = []
    this.listeners = { open: [], message: [], error: [], close: [] }
    FakeWebSocket.instances.push(this)
  }

  addEventListener(type, callback) {
    if (!this.listeners[type]) this.listeners[type] = []
    this.listeners[type].push(callback)
  }

  removeEventListener(type, callback) {
    const list = this.listeners[type] || []
    const index = list.indexOf(callback)
    if (index >= 0) list.splice(index, 1)
  }

  _fire(type, event) {
    const handler = this[`on${type}`]
    if (typeof handler === 'function') handler(event)
    for (const callback of this.listeners[type] || []) callback(event)
  }

  open() {
    this.readyState = FakeWebSocket.OPEN
    this._fire('open', {})
  }

  fail() {
    this._fire('error', {})
  }

  emit(payload) {
    this._fire('message', {
      data: typeof payload === 'string' ? payload : JSON.stringify(payload),
    })
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED
    this._fire('close', { code: 1000, reason: 'closed' })
  }

  send(text) {
    this.sent.push(text)
  }
}

// 客户端在 connect() 里 new WebSocket(...)，导入前先把全局替身装好。
globalThis.WebSocket = FakeWebSocket

const debugModel = await importDebugModule('../frontend/src/debug/model.js')
const debugClient = await importDebugModule('../frontend/src/debug/client.js')

function lastDebugSocket() {
  const socket = FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
  check(socket !== undefined, 'DebugClient.connect() 应创建 WebSocket')
  return socket
}

async function connectDebugClient(client) {
  let promise
  try {
    promise = client.connect()
  } catch (err) {
    throw new Error(`冻结接口要求 connect() 无参并返回 Promise：${err.message}`)
  }
  const socket = lastDebugSocket()
  socket.open()
  await promise
  return socket
}


if (debugModel) {
  const { applyState, appendLog, nodeStatusClass, isBusy, phaseLabel } = debugModel

  addCase('debug.applyState 五种 phase 原样保留', () => {
    for (const phase of DEBUG_PHASES) {
      const view = applyState(
        { phase: 'idle', current: null, nodes: {} },
        {
          phase,
          current: 'n2',
          order: ['n1', 'n2'],
          nodes: {
            n1: {
              status: 'fresh',
              duration_ms: 3.5,
              error: null,
              outputs: { table: 'DataFrame 60 行 × 2 列' },
            },
          },
        },
      )
      check(view.phase === phase, `phase 应为 ${phase}，实际 ${view.phase}`)
      check(view.current === 'n2', `current 应保留：${view.current}`)
      check(
        view.nodes && view.nodes.n1 && view.nodes.n1.status === 'fresh',
        `nodes 应保留：${JSON.stringify(view.nodes)}`,
      )
      assertDeepEqual(
        Object.keys(view.nodes.n1).sort(),
        ['duration_ms', 'error', 'outputs', 'status'],
        '节点固定四件套 status / duration_ms / error / outputs',
      )
      check(
        view.nodes.n1.duration_ms === 3.5,
        `有限 duration_ms 应保留：${view.nodes.n1.duration_ms}`,
      )
      check(view.nodes.n1.error === null, `error 应为 null：${JSON.stringify(view.nodes.n1.error)}`)
      assertDeepEqual(
        view.nodes.n1.outputs,
        { table: 'DataFrame 60 行 × 2 列' },
        'outputs 应按端口保留预览',
      )
    }
  })

  addCase('debug.applyState state 为 null 或空对象不抛且字段齐全', () => {
    const previous = { phase: 'paused', current: 'n1', nodes: {} }
    for (const view0 of [null, previous]) {
      for (const state of [null, {}]) {
        const view = applyState(view0, state)
        for (const key of ['phase', 'current', 'nodes']) {
          check(key in view, `applyState 结果应含 ${key}：${JSON.stringify(view)}`)
        }
        check(typeof view.phase === 'string', `phase 应是字符串：${view.phase}`)
        check(
          view.nodes && typeof view.nodes === 'object' && !Array.isArray(view.nodes),
          `nodes 应是对象：${JSON.stringify(view.nodes)}`,
        )
      }
    }
  })

  addCase('debug.applyState 坏形状归一：未知 status、坏 outputs、坏 duration/error', () => {
    const view = applyState(null, {
      phase: 'running',
      current: 'n1',
      order: ['n1', 'n2'],
      nodes: {
        n1: {
          status: 'weird',
          duration_ms: 'abc',
          error: 42,
          outputs: ['not', 'an', 'object'],
        },
        n2: {
          status: 'fresh',
          duration_ms: 1,
          error: '',
          outputs: { table: 'ok', count: 3, flag: true },
        },
      },
    })
    check(view.nodes.n1 && typeof view.nodes.n1 === 'object', '坏形状不应崩')
    check(view.nodes.n1.status === 'unrun', `未知 status 应归 unrun：${view.nodes.n1.status}`)
    check(view.nodes.n1.duration_ms === null, `duration_ms 非数字应归 null：${view.nodes.n1.duration_ms}`)
    check(view.nodes.n1.error === null, `非字符串 error 应归 null：${JSON.stringify(view.nodes.n1.error)}`)
    assertDeepEqual(view.nodes.n1.outputs, {}, 'outputs 是数组时应归一成空对象')
    assertDeepEqual(
      view.nodes.n2.outputs,
      { table: 'ok' },
      'outputs 里的非字符串值应逐条丢弃',
    )
    check(
      view.nodes.n2.error === null,
      `空串 error 应归 null：${JSON.stringify(view.nodes.n2.error)}`,
    )
  })

  addCase('debug.applyState state 带 outputs 时逐端口保留', () => {
    const tablePreview = "DataFrame 60 行 × 2 列 ['x','y'] ..."
    const first = applyState(null, {
      phase: 'paused',
      current: 'n1',
      nodes: {
        n1: {
          status: 'fresh',
          duration_ms: 12,
          error: null,
          outputs: { table: tablePreview, model: '模型预览' },
        },
      },
    })
    check(first.nodes.n1.status === 'fresh', `冻结节点应是 fresh：${first.nodes.n1.status}`)
    check(
      first.nodes.n1.outputs.table === tablePreview,
      `outputs.table 应原样保留：${JSON.stringify(first.nodes.n1.outputs)}`,
    )
    check(
      first.nodes.n1.outputs.model === '模型预览',
      `同帧的其它端口也应保留：${JSON.stringify(first.nodes.n1.outputs)}`,
    )

    const second = applyState(first, {
      phase: 'ended',
      current: null,
      nodes: {
        n1: {
          status: 'fresh',
          duration_ms: 20,
          error: null,
          outputs: { table: 'new preview' },
        },
      },
    })
    assertDeepEqual(
      second.nodes.n1.outputs,
      { table: 'new preview' },
      '后续帧应整体覆盖端口预览而不是累加旧端口',
    )
    check(
      second.nodes.n1.duration_ms === 20,
      `后续帧的 duration_ms 也应更新：${second.nodes.n1.duration_ms}`,
    )
  })

  addCase('debug.appendLog 单对象形态', () => {
    const one = appendLog([], { node: 'n1', stream: 'stdout', text: 'hello' })
    check(Array.isArray(one) && one.length === 1, `单对象应追加一行：${one.length}`)
    assertDeepEqual(
      one[0],
      { node: 'n1', stream: 'stdout', text: 'hello' },
      '单对象应原样追加为一条日志',
    )

    const two = appendLog(one, { node: 'n2', stream: 'stderr', text: 'beta' })
    check(two.length === 2, `逐条追加应累加：${two.length}`)
    check(
      two[0].text === 'hello' && two[1].text === 'beta',
      `顺序不能乱：${JSON.stringify(two)}`,
    )
    check(two[1].stream === 'stderr', `stderr 应保留：${two[1].stream}`)
  })

  addCase('debug.appendLog 形状、stream 归一与坏条目丢弃', () => {
    const item = appendLog([], {
      node: 'n1',
      stream: 'stdout',
      text: 'x',
      extra: 1,
      text2: 'y',
    })[0]
    assertDeepEqual(
      Object.keys(item).sort(),
      ['node', 'stream', 'text'],
      '每条日志恰好 {node, stream, text} 三个键',
    )
    assertDeepEqual(
      item,
      { node: 'n1', stream: 'stdout', text: 'x' },
      '多余字段应被丢掉',
    )

    check(
      appendLog([], { node: 'n1', stream: 'stderr', text: 'err' })[0].stream ===
        'stderr',
      'stderr 应保留',
    )
    check(
      appendLog([], { node: 'n2', stream: 'weird', text: 'out' })[0].stream ===
        'stdout',
      'stream 非 stderr 应归一成 stdout',
    )
    check(
      appendLog([], { node: 'n3', text: 'no-stream' })[0].stream === 'stdout',
      '缺 stream 应归一成 stdout',
    )

    const lines = [{ node: null, stream: 'stdout', text: 'keep' }]
    const snapshot = JSON.parse(JSON.stringify(lines))
    for (const bad of [
      { node: 'n1', stream: 'stdout', text: '' },
      { node: 'n2', stream: 'stdout', text: 42 },
      { node: 'n3', stream: 'stdout' },
    ]) {
      const result = appendLog(lines, bad)
      check(
        result === lines,
        `text 为空/非字符串/缺失时应返回原数组引用：${JSON.stringify(bad)}`,
      )
    }
    assertDeepEqual(lines, snapshot, '入参数组不能被修改')
  })

  addCase('debug.appendLog 超上限丢头不丢尾', () => {
    let lines = []
    for (let index = 0; index < 5001; index += 1) {
      lines = appendLog(lines, { node: null, stream: 'stdout', text: `L${index}` })
    }
    check(lines.length === 5000, `上限应是 5000，实际 ${lines.length}`)
    check(lines[0].text === 'L1', `应丢头：第一行 ${lines[0].text}`)
    check(lines[1].text === 'L2', `顺序不能乱：${lines[1].text}`)
    check(
      lines[lines.length - 1].text === 'L5000',
      `应保留最后一行：${lines[lines.length - 1].text}`,
    )
    const contiguous = lines.every((line, index) => line.text === `L${index + 1}`)
    check(contiguous, '超上限时应保留尾部连续段，中间不能有洞')
  })

  addCase('debug.appendLog 非法 message 不改变原数组', () => {
    const lines = [{ node: 'n1', stream: 'stdout', text: 'keep-1' }]
    const snapshot = JSON.parse(JSON.stringify(lines))
    for (const bad of [[], null, undefined, 'text']) {
      const result = appendLog(lines, bad)
      check(result === lines, `非法 message 应返回原数组引用：${JSON.stringify(bad)}`)
    }
    assertDeepEqual(lines, snapshot, '入参数组不能被修改')
  })

  addCase('debug.nodeStatusClass 四种状态的确切 class、null 空串', () => {
    assertDeepEqual(
      ['unrun', 'fresh', 'stale', 'failed'].map((status) => nodeStatusClass(status)),
      ['status-unrun', 'status-fresh', 'status-stale', 'status-failed'],
      '四种状态应映射到确切的 class 名',
    )
    check(nodeStatusClass(null) === '', `null 不应挂 class：${nodeStatusClass(null)}`)
    let unknown
    try {
      unknown = nodeStatusClass('weird')
    } catch (err) {
      throw new Error(`未知状态不应抛异常：${err.message}`)
    }
    check(typeof unknown === 'string', `未知状态应返回字符串：${typeof unknown}`)
  })

  addCase('debug.isBusy 真值表：可点 = !isBusy(phase)', () => {
    check(isBusy('running') === true, 'running 是忙')
    for (const phase of ['idle', 'paused', 'ended', 'failed']) {
      check(isBusy(phase) === false, `isBusy(${phase}) 应为 false`)
    }
    // 单节点可点与否只由 isBusy 推导，不再有 canRunNode。
    check(!isBusy('running') === false, 'running 时不可点')
    for (const phase of ['idle', 'paused', 'ended', 'failed']) {
      check(!isBusy(phase) === true, `${phase} 时可点`)
    }
  })

  addCase('debug.phaseLabel 五种 phase 的确切文案', () => {
    assertDeepEqual(
      DEBUG_PHASES.map((phase) => phaseLabel(phase)),
      ['空闲', '运行中', '已暂停', '已结束', '已失败'],
      '五种 phase 的文案应与契约一致',
    )
  })
}

if (debugClient) {
  addCase('debug.client 四种报文分别派发且参数形状正确', async () => {
    const calls = []
    const handlers = {
      onState: (payload) => calls.push(['state', payload]),
      onLog: (payload) => calls.push(['log', payload]),
      onAck: (payload) => calls.push(['ack', payload]),
      onError: (payload) => calls.push(['error', payload]),
    }
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({ port: 8801, token: 'tok', handlers })
    const socket = await connectDebugClient(client)

    const state = { phase: 'running', current: 'n1', order: ['n1'], nodes: {} }
    const log = { type: 'log', node: 'n1', stream: 'stdout', text: 'hello' }
    const ack = { type: 'ack', cmd: 'run_node' }
    const error = { type: 'error', message: 'boom' }
    socket.emit({ type: 'state', data: state })
    socket.emit(log)
    socket.emit(ack)
    socket.emit(error)

    const names = calls.map(([name]) => name)
    check(
      names.join(',') === 'state,log,ack,error',
      `四种报文应分别派发，实际：${JSON.stringify(names)}`,
    )
    assertDeepEqual(calls[0][1], state, 'onState 应只收到 message.data')
    assertDeepEqual(calls[1][1], log, 'onLog 应收到整条消息')
    assertDeepEqual(calls[2][1], ack, 'onAck 应收到整条消息')
    assertDeepEqual(calls[3][1], error, 'onError 应收到整条消息')
  })

  addCase('debug.client 派发 inspect 报文', async () => {
    const calls = []
    const handlers = {
      onState: (payload) => calls.push(['state', payload]),
      onInspect: (payload) => calls.push(['inspect', payload]),
      onLog: (payload) => calls.push(['log', payload]),
      onAck: (payload) => calls.push(['ack', payload]),
      onError: (payload) => calls.push(['error', payload]),
      onClose: (payload) => calls.push(['close', payload]),
    }
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({ port: 8801, token: 'tok', handlers })
    const socket = await connectDebugClient(client)

    const data = {
      node: 'n1',
      inputs: { data: 'x' },
      outputs: { table: 'y' },
    }
    socket.emit({ type: 'inspect', data })
    check(
      calls.length === 1,
      `inspect 只应触发 onInspect，其它回调不能误触发：${JSON.stringify(calls)}`,
    )
    check(calls[0][0] === 'inspect', `应触发 onInspect，实际 ${calls[0][0]}`)
    assertDeepEqual(calls[0][1], data, 'onInspect 应收到完整 message.data')

    socket.emit({ type: 'nope', data: { node: 'n2' } })
    check(calls.length === 1, `未知 type 仍应忽略：${JSON.stringify(calls)}`)
  })

  addCase('debug.client 未知 type / 非 JSON / 非字符串都忽略', async () => {
    const calls = []
    const handlers = {
      onState: () => calls.push('state'),
      onLog: () => calls.push('log'),
      onAck: () => calls.push('ack'),
      onError: () => calls.push('error'),
      onClose: () => calls.push('close'),
    }
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({ port: 8801, token: 'tok', handlers })
    const socket = await connectDebugClient(client)
    socket.emit({ type: 'nope', whatever: 1 })
    socket.emit('not json at all')
    socket._fire('message', { data: 42 })
    socket._fire('message', { data: { type: 'state', data: { phase: 'running' } } })
    check(calls.length === 0, `坏报文应全部忽略：${JSON.stringify(calls)}`)
  })

  addCase('debug.client event 报文不再派发（注册 onEvent 也收不到）', async () => {
    const calls = []
    const handlers = {
      onState: () => calls.push('state'),
      onEvent: () => calls.push('event'),
      onLog: () => calls.push('log'),
      onAck: () => calls.push('ack'),
      onError: () => calls.push('error'),
      onClose: () => calls.push('close'),
    }
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({ port: 8801, token: 'tok', handlers })
    const socket = await connectDebugClient(client)
    socket.emit({ type: 'event', event: 'node_end', data: { node: 'n1' } })
    check(
      calls.length === 0,
      `协议已删掉 event 推送，注册了 onEvent 也不该被调用：${JSON.stringify(calls)}`,
    )
  })

  addCase('debug.client 建连前被关闭 → reject', async () => {
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({ port: 8801, token: 'tok', handlers: {} })
    const promise = client.connect()
    const socket = lastDebugSocket()
    socket.close() // 还没 open 就被服务端关掉
    let error = null
    try {
      await promise
    } catch (err) {
      error = err
    }
    check(error instanceof Error, `建连前被关闭应 reject，实际 ${error}`)
    check(
      String(error.message).includes('关闭'),
      `错误信息应说明连接在建立前被关闭：${error.message}`,
    )
  })

  addCase('debug.client onerror → reject', async () => {
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({ port: 8801, token: 'tok', handlers: {} })
    const promise = client.connect()
    const socket = lastDebugSocket()
    socket.fail()
    let error = null
    try {
      await promise
    } catch (err) {
      error = err
    }
    check(error instanceof Error, `onerror 应 reject，实际 ${error}`)
    check(String(error.message).includes('8801'), `错误信息应带端口：${error.message}`)
  })

  addCase('debug.client 主动 close 不触发 onClose', async () => {
    const closes = []
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({
      port: 8801,
      token: 'tok',
      handlers: { onClose: (event) => closes.push(event) },
    })
    await connectDebugClient(client)
    client.close()
    check(closes.length === 0, `主动 close 不应触发 onClose，实际 ${closes.length}`)
  })

  addCase('debug.client 服务端断开只触发一次且带 code/reason', async () => {
    const closes = []
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({
      port: 8801,
      token: 'tok',
      handlers: { onClose: (event) => closes.push(event) },
    })
    const socket = await connectDebugClient(client)
    socket.close()
    socket.close()
    check(closes.length === 1, `onClose 应只触发一次，实际 ${closes.length}`)
    assertDeepEqual(
      closes[0],
      { code: 1000, reason: 'closed' },
      'onClose 应带 {code, reason}',
    )
  })

  addCase('debug.client 未连接时 send 返回 false 且不抛', () => {
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({ port: 8801, token: 'tok', handlers: {} })
    let error = null
    let result
    try {
      result = client.send({ cmd: 'state' })
    } catch (err) {
      error = err
    }
    check(error === null, `未连接时 send 不能抛异常：${error && error.message}`)
    check(result === false, `未连接时 send 应返回 false，实际 ${result}`)
  })

  addCase('debug.client 连上后 send 发出 JSON.stringify 后的命令', async () => {
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({ port: 8801, token: 'tok', handlers: {} })
    const socket = await connectDebugClient(client)
    const command = { cmd: 'run_node', id: 'n1' }
    check(client.send(command) === true, '已连接时 send 应返回 true')
    check(socket.sent.length === 1, `应发送一条命令：${socket.sent.length}`)
    check(
      socket.sent[0] === JSON.stringify(command),
      `发送内容应是 JSON.stringify(cmd)：${socket.sent[0]}`,
    )
  })

  addCase('debug.client connect 使用构造参数里的 port/token', async () => {
    FakeWebSocket.instances.length = 0
    const client = new debugClient.DebugClient({ port: 8801, token: 'tok', handlers: {} })
    const socket = await connectDebugClient(client)
    check(
      socket.url.includes('127.0.0.1:8801'),
      `WebSocket 地址应含端口：${socket.url}`,
    )
    check(socket.url.includes('tok'), `WebSocket 地址应含 token：${socket.url}`)
  })
}

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
