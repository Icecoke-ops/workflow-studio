/** 子图的全部判断：树的成员关系、选区归一、投影（节点/边/端口）、层级约束、prune。
 *  纯函数，不 import Vue、不读 ref；App 与组件只搬运结果。 */

const GROUP = 'group'
const FRAME = 'frame'

/** 画布上除 comp/group/frame 外没有别的节点类型；未标 type 的按组件处理。 */
export function isComponentNode(node) {
  return node.type !== GROUP && node.type !== FRAME
}

export function findGroup(groups, id) {
  return groups.find((group) => group.id === id) || null
}

export function membersOf(group) {
  return Array.isArray(group.members) ? group.members : []
}

/** 单元直接被哪个组包含；root 层返回 null。 */
export function parentOf(groups, unitId) {
  for (const group of groups) {
    if (membersOf(group).includes(unitId)) return group.id
  }
  return null
}

/** 由近到远的祖先 id；带环保护，畸形数据不会死循环。 */
function ancestorIds(groups, unitId) {
  const ids = []
  let parent = parentOf(groups, unitId)
  const visited = new Set()
  while (parent && !visited.has(parent)) {
    visited.add(parent)
    ids.push(parent)
    parent = parentOf(groups, parent)
  }
  return ids
}

/** 最近的、处于折叠态的直接或间接祖先组；没有返回 null。 */
export function collapsedAncestor(groups, unitId) {
  for (const id of ancestorIds(groups, unitId)) {
    const group = findGroup(groups, id)
    if (!group) return null
    if (group.collapsed) return group.id
  }
  return null
}

/** 最外层的折叠祖先组；没有返回 null。投影时可见实体是最外层折叠组。 */
function outermostCollapsedAncestor(groups, unitId) {
  let found = null
  for (const id of ancestorIds(groups, unitId)) {
    const group = findGroup(groups, id)
    if (!group) break
    if (group.collapsed) found = group.id
  }
  return found
}

/** 连线层级约束：两端必须处于同一层；组卡片代表它所在的那一层。 */
export function canConnect(groups, sourceId, targetId) {
  if (!sourceId || !targetId || sourceId === targetId) return false
  return parentOf(groups, sourceId) === parentOf(groups, targetId)
}

export function parseHandle(handle) {
  if (typeof handle !== 'string') return null
  const index = handle.lastIndexOf(':')
  if (index <= 0 || index === handle.length - 1) return null
  return { nodeId: handle.slice(0, index), port: handle.slice(index + 1) }
}

/** 画布上的连接尝试 -> 真实节点/端口的连接。 */
export function resolveConnection(groups, connection) {
  if (!connection) return null
  const source = resolveEndpoint(groups, connection.source, connection.sourceHandle)
  const target = resolveEndpoint(groups, connection.target, connection.targetHandle)
  if (!source || !target) return null
  return {
    source: source.nodeId,
    sourceHandle: source.port,
    target: target.nodeId,
    targetHandle: target.port,
  }
}

function resolveEndpoint(groups, id, handle) {
  if (!id || !handle) return null
  if (findGroup(groups, id)) return parseHandle(handle)
  return { nodeId: id, port: handle }
}

/** 真实边 -> 画布边：折叠组内的端点换成组卡片，组内边不画；id 沿用真实边 id。 */
export function projectEdges(edges, groups) {
  const projected = []
  for (const edge of edges) {
    const sourceGroup = outermostCollapsedAncestor(groups, edge.source)
    const targetGroup = outermostCollapsedAncestor(groups, edge.target)
    if (sourceGroup && sourceGroup === targetGroup) continue
    projected.push({
      ...edge,
      source: sourceGroup || edge.source,
      sourceHandle: sourceGroup
        ? `${edge.source}:${edge.sourceHandle}`
        : edge.sourceHandle,
      target: targetGroup || edge.target,
      targetHandle: targetGroup
        ? `${edge.target}:${edge.targetHandle}`
        : edge.targetHandle,
    })
  }
  return projected
}

/** 折叠组卡片两端的端口：从投影后的边界边实时推导，不存端口清单。 */
function collectGroupPorts(groups, projectedEdges, nodeById) {
  const ports = new Map()
  for (const edge of projectedEdges) {
    for (const [id, handleId, listKey, typeKey] of [
      [edge.source, edge.sourceHandle, 'outPorts', 'type'],
      [edge.target, edge.targetHandle, 'inPorts', 'types'],
    ]) {
      if (!findGroup(groups, id)) continue
      const handle = parseHandle(handleId)
      const port = handle
        ? (nodeById.get(handle.nodeId)?.data[listKey] || []).find(
            (item) => item.name === handle.port,
          )
        : null
      if (!ports.has(id)) ports.set(id, { inPorts: [], outPorts: [] })
      const list = ports.get(id)[listKey]
      if (!list.some((item) => item.name === handleId)) {
        list.push({ name: handleId, [typeKey]: port?.[typeKey], color: port?.color })
      }
    }
  }
  return ports
}

/**
 * 编辑器状态 -> 画布节点。真实组件节点始终保留（折叠组里的 hidden），
 * 每个组按状态给出组卡片（折叠）或框（展开）；框固定在 (0,0)，包围盒由组件实时算。
 */
export function projectGraph({ nodes, edges, groups }) {
  const componentNodes = nodes.filter(isComponentNode)
  const nodeById = new Map(componentNodes.map((node) => [node.id, node]))
  const projectedEdges = projectEdges(edges, groups)
  const ports = collectGroupPorts(groups, projectedEdges, nodeById)
  const previous = new Map(nodes.map((node) => [node.id, node]))

  const result = componentNodes.map((node) => ({
    ...node,
    hidden: Boolean(collapsedAncestor(groups, node.id)),
  }))

  for (const group of groups) {
    const hidden = Boolean(collapsedAncestor(groups, group.id))
    const previousNode = previous.get(group.id)
    if (group.collapsed) {
      const portData = ports.get(group.id) || { inPorts: [], outPorts: [] }
      // 只有上一帧也是组卡片时才复用位置；frame 固定在 (0,0)，不能拿来当卡片位置
      const previousPosition = previousNode?.type === GROUP ? previousNode.position : null
      result.push({
        id: group.id,
        type: GROUP,
        position: previousPosition || group.position || { x: 80, y: 60 },
        hidden,
        selectable: true,
        data: {
          groupId: group.id,
          title: group.title,
          count: membersOf(group).length,
          groups,
          inPorts: portData.inPorts,
          outPorts: portData.outPorts,
        },
      })
    } else {
      result.push({
        id: group.id,
        type: FRAME,
        position: { x: 0, y: 0 },
        hidden,
        selectable: false,
        draggable: false,
        connectable: false,
        zIndex: -1,
        data: { groupId: group.id, title: group.title, groups },
      })
    }
  }
  return { nodes: result, edges: projectedEdges }
}

/** 展开的框需要包住的单元：组件节点，或折叠的子组卡片（展开的子组递归展开）。 */
export function frameItems(groups, groupId, seen = new Set()) {
  if (seen.has(groupId)) return []
  seen.add(groupId)
  const group = findGroup(groups, groupId)
  if (!group) return []
  const items = []
  for (const unitId of membersOf(group)) {
    const child = findGroup(groups, unitId)
    if (!child) {
      items.push(unitId)
    } else if (child.collapsed) {
      items.push(child.id)
    } else {
      items.push(...frameItems(groups, child.id, seen))
    }
  }
  return items
}

/** 折叠组卡片里按成员列参数：递归展开到叶子组件，带组标题面包屑。 */
export function memberLeaves(groups, groupId, trail = [], seen = new Set()) {
  if (seen.has(groupId)) return []
  seen.add(groupId)
  const group = findGroup(groups, groupId)
  if (!group) return []
  const leaves = []
  for (const unitId of membersOf(group)) {
    const child = findGroup(groups, unitId)
    if (child) {
      leaves.push(...memberLeaves(groups, child.id, [...trail, child.title], seen))
    } else {
      leaves.push({ nodeId: unitId, trail })
    }
  }
  return leaves
}

/** 选区归一：组件节点换成最外层祖先组（没有就是自己），组保持自身；去重。 */
export function selectionUnits(groups, selectedIds) {
  const units = []
  const seen = new Set()
  for (const id of selectedIds) {
    const unit = outermostUnit(groups, id)
    if (!unit || seen.has(unit)) continue
    seen.add(unit)
    units.push(unit)
  }
  // 单元集合必须互不包含：祖先也在选中集合里时，只保留祖先那个单元。
  return units.filter(
    (unit) => !units.some((other) => other !== unit && isAncestor(groups, other, unit)),
  )
}

/** 祖孙关系：沿 parentOf 往上找；带环保护，畸形数据不会死循环。 */
function isAncestor(groups, ancestorId, unitId) {
  let parent = parentOf(groups, unitId)
  const visited = new Set()
  while (parent && !visited.has(parent)) {
    if (parent === ancestorId) return true
    visited.add(parent)
    parent = parentOf(groups, parent)
  }
  return false
}

function outermostUnit(groups, unitId) {
  if (findGroup(groups, unitId)) return unitId
  return ancestorIds(groups, unitId).at(-1) || unitId
}

/** 单元们的共同父组；不同父组返回 undefined（root 为 null）。 */
export function commonParent(groups, units) {
  if (!units.length) return undefined
  const parents = units.map((unitId) => parentOf(groups, unitId))
  return parents.every((parent) => parent === parents[0]) ? parents[0] : undefined
}

export function canGroup(groups, selectedIds) {
  const units = selectionUnits(groups, selectedIds)
  return units.length >= 2 && commonParent(groups, units) !== undefined
}

export function canDissolve(groups, selectedIds) {
  return selectedIds.length === 1 && Boolean(findGroup(groups, selectedIds[0]))
}

export function nextGroupId(groups, nodes = []) {
  const used = new Set([
    ...groups.map((group) => group.id),
    ...nodes.map((node) => node.id),
  ])
  let index = 1
  while (used.has(`g${index}`)) index += 1
  return `g${index}`
}

/** 建组：成员从父组拿走，父组对应位置换成新组 id；新组默认折叠。 */
export function createGroup(groups, { id, title, units, parent, position }) {
  const entry = { id, title, collapsed: true, members: [...units] }
  if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
    entry.position = { x: position.x, y: position.y }
  }
  let next = [...groups, entry]
  if (parent) {
    const moving = new Set(units)
    next = next.map((group) => {
      if (group.id !== parent) return group
      const members = []
      let inserted = false
      for (const unitId of membersOf(group)) {
        if (moving.has(unitId)) {
          if (!inserted) {
            members.push(id)
            inserted = true
          }
          continue
        }
        members.push(unitId)
      }
      if (!inserted) members.push(id)
      return { ...group, members }
    })
  }
  return next
}

/** 解散一层：成员提升到父层，其它一切不动。 */
export function dissolveGroup(groups, groupId) {
  const target = findGroup(groups, groupId)
  if (!target) return groups
  const parent = parentOf(groups, groupId)
  return groups
    .filter((group) => group.id !== groupId)
    .map((group) => {
      if (group.id !== parent) return group
      const members = []
      for (const unitId of membersOf(group)) {
        if (unitId === groupId) members.push(...membersOf(target))
        else members.push(unitId)
      }
      return { ...group, members }
    })
}

/** 折叠/展开一层；折叠时带上包围盒中心作为卡片位置。 */
export function setCollapsed(groups, groupId, collapsed, position) {
  return groups.map((group) => {
    if (group.id !== groupId) return group
    const next = { ...group, collapsed }
    if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
      next.position = { x: position.x, y: position.y }
    }
    return next
  })
}

/** 节点删除后的收拾：members 去掉不存在的单元，空组解散（逐层收敛）。 */
export function pruneGroups(groups, nodes) {
  const nodeIds = new Set(nodes.filter(isComponentNode).map((node) => node.id))
  let current = groups.map((group) => ({ ...group, members: [...membersOf(group)] }))
  let changed = true
  while (changed) {
    changed = false
    const alive = new Set(current.map((group) => group.id))
    const next = []
    for (const group of current) {
      const members = membersOf(group).filter(
        (unitId) => nodeIds.has(unitId) || alive.has(unitId),
      )
      if (!members.length) {
        changed = true
        continue
      }
      if (members.length !== membersOf(group).length) changed = true
      next.push(members.length === membersOf(group).length ? group : { ...group, members })
    }
    current = next
  }
  return current
}

export function dropEdgesForNodes(edges, nodeIds) {
  const removed = new Set(nodeIds)
  return edges.filter((edge) => !removed.has(edge.source) && !removed.has(edge.target))
}

/** 画布节点尺寸表（组件卡 280 宽，组卡片固定宽）；未测量的用兜底值。 */
export function nodeBoxes(nodes) {
  const boxes = new Map()
  for (const node of nodes) {
    if (!node.position) continue
    const width = node.dimensions?.width || (node.type === GROUP ? 240 : 280)
    const height = node.dimensions?.height || (node.type === GROUP ? 140 : 200)
    boxes.set(node.id, {
      x: node.position.x,
      y: node.position.y,
      width,
      height,
    })
  }
  return boxes
}

export function unionBox(boxes) {
  if (!boxes.length) return null
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const box of boxes) {
    minX = Math.min(minX, box.x)
    minY = Math.min(minY, box.y)
    maxX = Math.max(maxX, box.x + box.width)
    maxY = Math.max(maxY, box.y + box.height)
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}

/** 一个单元的包围盒：组件/折叠组直接用节点框，展开组递归合并成员。 */
export function unitBox(unitId, groups, boxes) {
  const group = findGroup(groups, unitId)
  if (!group) return boxes.get(unitId) || null
  if (group.collapsed) return boxes.get(unitId) || null
  return unionBox(frameItems(groups, group.id).map((id) => boxes.get(id)).filter(Boolean))
}

/** 选区包围盒（建组/折叠时取中心用）。 */
export function selectionBox(units, groups, boxes) {
  return unionBox(units.map((unitId) => unitBox(unitId, groups, boxes)).filter(Boolean))
}

/** 折叠组卡片的位置表（画布节点里 type === group 的那些）。 */
export function groupPositions(nodes) {
  return Object.fromEntries(
    nodes
      .filter((node) => node.type === GROUP && node.position)
      .map((node) => [node.id, node.position]),
  )
}

/** groups -> addition.groups：只写编辑器认识的字段，position 仅在有限时写。 */
export function serializeGroups(groups, positions = {}) {
  return groups.map((group) => {
    const entry = {
      id: group.id,
      title: group.title,
      collapsed: Boolean(group.collapsed),
      members: [...membersOf(group)],
    }
    const position = positions[group.id] || group.position
    if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
      entry.position = { x: position.x, y: position.y }
    }
    return entry
  })
}
