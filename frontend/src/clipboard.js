/** 子图/节点的内存剪贴板：快照只存可重建的数据，粘贴全部换新 id。纯函数，不读 ref。 */

import { cloneDefault } from './model.js'
import {
  findGroup,
  groupPositions,
  isComponentNode,
  membersOf,
  selectionUnits,
  serializeGroups,
} from './groups.js'

const OFFSET = 40

/**
 * 选区 -> 剪贴板快照。
 * 选区归一到最外层单元（与「组合」同一个函数），组被选中就带上其全部成员（含嵌套组）。
 */
export function collectCopy({ nodes, edges, groups, selectedIds }) {
  const nodeIds = new Set()
  const groupIds = new Set()

  const addGroup = (groupId) => {
    if (groupIds.has(groupId)) return
    const group = findGroup(groups, groupId)
    if (!group) return
    groupIds.add(groupId)
    for (const unitId of membersOf(group)) {
      const child = findGroup(groups, unitId)
      if (child) addGroup(child.id)
      else nodeIds.add(unitId)
    }
  }

  for (const unitId of selectionUnits(groups, selectedIds)) {
    const group = findGroup(groups, unitId)
    if (group) addGroup(group.id)
    else nodeIds.add(unitId)
  }

  const nodeById = new Map(nodes.filter(isComponentNode).map((node) => [node.id, node]))
  const snapshotNodes = []
  for (const id of nodeIds) {
    const node = nodeById.get(id)
    if (!node) continue
    snapshotNodes.push({
      id,
      position: { x: node.position.x, y: node.position.y },
      plugin: node.data.plugin,
      component: node.data.component,
      config: cloneDefault(node.data.config),
    })
  }

  const snapshotGroups = serializeGroups(
    [...groupIds].map((id) => findGroup(groups, id)).filter(Boolean),
    groupPositions(nodes),
  )

  const copied = new Set(snapshotNodes.map((node) => node.id))
  const snapshotEdges = edges
    .filter((edge) => copied.has(edge.source) && copied.has(edge.target))
    .map((edge) => ({
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
    }))

  return { nodes: snapshotNodes, groups: snapshotGroups, edges: snapshotEdges }
}

/** 从现有 id 往后分配，跳过已用；返回的数量等于 count。 */
function nextIds(prefix, used, count) {
  const ids = []
  let max = 0
  for (const id of used) {
    if (typeof id !== 'string' || !id.startsWith(prefix)) continue
    const value = Number(id.slice(prefix.length))
    if (Number.isInteger(value) && value > max) max = value
  }
  let index = max + 1
  while (ids.length < count) {
    const id = `${prefix}${index}`
    index += 1
    if (used.has(id)) continue
    used.add(id)
    ids.push(id)
  }
  return ids
}

/**
 * 剪贴板快照 -> 可写回画布的普通对象（新 id、坐标偏移、config 深拷贝、members 重映射）。
 * 粘贴出来的一律落在 root 层；返回的 groups 直接追加到现有 groups 即可。
 */
export function planPaste(snapshot, { nodes, groups }) {
  const used = new Set([
    ...nodes.map((node) => node.id),
    ...groups.map((group) => group.id),
  ])
  const nodeIds = nextIds('n', used, snapshot.nodes.length)
  const groupIds = nextIds('g', used, snapshot.groups.length)
  const nodeMap = new Map(snapshot.nodes.map((node, index) => [node.id, nodeIds[index]]))
  const groupMap = new Map(snapshot.groups.map((group, index) => [group.id, groupIds[index]]))

  const pastedNodes = snapshot.nodes.map((node) => ({
    id: nodeMap.get(node.id),
    position: { x: node.position.x + OFFSET, y: node.position.y + OFFSET },
    plugin: node.plugin,
    component: node.component,
    config: cloneDefault(node.config),
  }))

  const pastedGroups = snapshot.groups.map((group) => {
    const entry = {
      id: groupMap.get(group.id),
      title: group.title,
      collapsed: Boolean(group.collapsed),
      members: group.members
        .map((unitId) => nodeMap.get(unitId) || groupMap.get(unitId))
        .filter(Boolean),
    }
    if (group.position) {
      entry.position = { x: group.position.x + OFFSET, y: group.position.y + OFFSET }
    }
    return entry
  })

  const pastedEdges = snapshot.edges
    .map((edge) => {
      const source = nodeMap.get(edge.source)
      const target = nodeMap.get(edge.target)
      if (!source || !target) return null
      return {
        id: `e-${target}-${edge.targetHandle}`,
        type: 'workflow',
        source,
        target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
      }
    })
    .filter(Boolean)

  return { nodes: pastedNodes, groups: pastedGroups, edges: pastedEdges }
}
