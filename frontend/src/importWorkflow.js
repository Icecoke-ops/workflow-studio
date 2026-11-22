/** 导入工作流的纯逻辑：归一化、层级布局、节点与连线构造，可脱离 Vue 直接跑。 */

import { readAddition } from './addition.js'
import { defaultsFor } from './model.js'

const FALLBACK_COLOR = '#909399'

function portDisplay(types, labels, typeDescs) {
  const short = labels.length > 1 ? `${labels[0]} +${labels.length - 1}` : labels[0]
  const full = types
    .map((id, index) => `${labels[index]}${typeDescs[id] ? ` — ${typeDescs[id]}` : ''}`)
    .join('\n')
  return { short, full }
}

/** 后端组件条目 -> 画布节点的 data。 */
export function buildNodeData(component, config, { typeDescs = {}, typeColors = {} } = {}) {
  const typeColor = (typeId) => typeColors[typeId] || FALLBACK_COLOR
  return {
    plugin: component.plugin,
    component: component.name,
    title: component.title,
    desc: component.desc,
    config: { ...defaultsFor(component.config_schema), ...(config || {}) },
    config_schema: component.config_schema,
    descOpen: false,
    paramsOpen: true,
    inPorts: Object.entries(component.input_schema || {}).map(([name, spec]) => {
      const display = portDisplay(spec.types, spec.type_labels, typeDescs)
      return {
        name,
        types: spec.types || [],
        color: typeColor((spec.types || [])[0]),
        short: display.short,
        full: display.full,
      }
    }),
    outPorts: Object.entries(component.output_schema || {}).map(([name, spec]) => {
      const display = portDisplay([spec.type], [spec.type_label], typeDescs)
      return {
        name,
        type: spec.type,
        color: typeColor(spec.type),
        short: display.short,
        full: display.full,
      }
    }),
    missing: false,
    failed: false,
  }
}

/** 插件里缺失组件的占位节点 data。 */
export function missingNodeData(plugin, component) {
  return {
    plugin,
    component,
    title: `${plugin}.${component}`,
    desc: '当前插件集合里没有这个组件',
    config: {},
    config_schema: {},
    descOpen: false,
    paramsOpen: true,
    inPorts: [],
    outPorts: [],
    missing: true,
    failed: false,
  }
}

/** 过滤不合法节点；根结构不对时抛错。 */
export function normalizeWorkflow(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('JSON 根节点必须是对象')
  if (!Array.isArray(raw.nodes)) throw new Error('缺少 nodes 数组')

  const items = []
  const seen = new Set()
  const skipped = []
  for (const item of raw.nodes) {
    if (!item || typeof item !== 'object') {
      skipped.push('存在非对象节点')
      continue
    }
    if (typeof item.id !== 'string' || !item.id) {
      skipped.push('节点缺少 id')
      continue
    }
    if (seen.has(item.id)) {
      skipped.push(`id 重复：${item.id}`)
      continue
    }
    if (typeof item.plugin !== 'string' || typeof item.component !== 'string') {
      skipped.push(`${item.id} 缺少 plugin/component`)
      continue
    }
    seen.add(item.id)
    items.push(item)
  }
  return { items, skipped }
}

/** 按 inputs 依赖定层级与行号：id -> { x, y }。环和自环按 0 层处理。 */
export function layoutPositions(items) {
  const byId = new Map(items.map((item) => [item.id, item]))
  const memo = new Map()
  const visiting = new Set()

  function depthOf(id) {
    if (memo.has(id)) return memo.get(id)
    if (visiting.has(id)) return 0
    visiting.add(id)
    const item = byId.get(id)
    let depth = 0
    if (item && item.inputs && typeof item.inputs === 'object') {
      for (const link of Object.values(item.inputs)) {
        if (
          link &&
          typeof link === 'object' &&
          typeof link.from === 'string' &&
          byId.has(link.from)
        ) {
          depth = Math.max(depth, depthOf(link.from) + 1)
        }
      }
    }
    visiting.delete(id)
    memo.set(id, depth)
    return depth
  }

  const rows = new Map()
  const positions = new Map()
  for (const item of items) {
    const depth = depthOf(item.id)
    const row = rows.get(depth) || 0
    rows.set(depth, row + 1)
    positions.set(item.id, { x: 80 + depth * 340, y: 60 + row * 440 })
  }
  return positions
}

/** 存档坐标必须是有限数值，否则返回 null 交给自动布局。 */
function savedPosition(value) {
  if (!value || typeof value !== 'object') return null
  if (!Number.isFinite(value.x) || !Number.isFinite(value.y)) return null
  return { x: value.x, y: value.y }
}

/** 导入计划：节点、连线、跳过的坏节点、缺失组件。 */
export function planImport(raw, { componentFor, typeDescs = {}, typeColors = {} } = {}) {
  const { items, skipped } = normalizeWorkflow(raw)
  const fallbackPositions = layoutPositions(items)
  const additionInfo = readAddition(raw)
  const savedPositions = additionInfo.positions
  const groups = additionInfo.groups
  const created = []
  const missing = []

  for (const item of items) {
    const position = savedPosition(savedPositions[item.id]) || fallbackPositions.get(item.id)
    const entry = componentFor(item.plugin, item.component)
    if (!entry) {
      missing.push(`${item.plugin}.${item.component}`)
      created.push({
        id: item.id,
        type: 'comp',
        position,
        data: missingNodeData(item.plugin, item.component),
      })
      continue
    }
    const config = item.config && typeof item.config === 'object' ? item.config : {}
    created.push({
      id: item.id,
      type: 'comp',
      position,
      data: buildNodeData(entry, config, { typeDescs, typeColors }),
    })
  }

  const nodeById = new Map(created.map((node) => [node.id, node]))
  const inputsTaken = new Set()
  const edges = []
  for (const item of items) {
    const targetNode = nodeById.get(item.id)
    if (!targetNode || !item.inputs || typeof item.inputs !== 'object') continue
    for (const [port, link] of Object.entries(item.inputs)) {
      if (!link || typeof link !== 'object') continue
      if (typeof link.from !== 'string' || typeof link.port !== 'string') continue
      const sourceNode = nodeById.get(link.from)
      if (!sourceNode) {
        skipped.push(`${item.id}.${port}: 来源节点 ${link.from} 不存在`)
        continue
      }
      if (!targetNode.data.inPorts.some((entry) => entry.name === port)) {
        skipped.push(`${item.id}.${port}: 组件没有输入端口 ${port}`)
        continue
      }
      if (!sourceNode.data.outPorts.some((entry) => entry.name === link.port)) {
        skipped.push(`${item.id}.${port}: 来源 ${link.from} 没有输出端口 ${link.port}`)
        continue
      }
      const key = `${item.id}.${port}`
      if (inputsTaken.has(key)) continue
      inputsTaken.add(key)
      edges.push({
        id: `e-${item.id}-${port}`,
        type: 'workflow',
        source: link.from,
        target: item.id,
        sourceHandle: link.port,
        targetHandle: port,
      })
    }
  }

  return {
    name: typeof raw.name === 'string' && raw.name ? raw.name : '导入的工作流',
    nodes: created,
    edges,
    groups,
    droppedGroups: additionInfo.droppedGroups,
    skipped,
    missing,
  }
}
