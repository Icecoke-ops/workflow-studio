// 前端纯函数测试：直接 import frontend/src 下的 ESM 模块，不依赖 Vue 运行时。
// 运行：node tests/test_frontend.mjs

import { envToRows, rowsToEnv, envError, attachEnv } from '../frontend/src/workflow.js'
import { cloneDefault, defaultsFor, buildWorkflow } from '../frontend/src/model.js'

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

// ---------------------------------------------------------------------------
// workflow.js
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// model.js / cloneDefault
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// model.js / defaultsFor
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// model.js / buildWorkflow
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// 跑测
// ---------------------------------------------------------------------------

for (const [name, fn] of cases) {
  try {
    fn()
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
