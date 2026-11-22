/** 子图的全部判断：树的成员关系、选区归一、投影（节点/边/端口）、prune。
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

/** 由近到远的祖先组；带环保护，畸形数据不会死循环。 */
function ancestorGroups(groups, unitId) {
  const found = []
  const visited = new Set()
  let parent = parentOf(groups, unitId)
  while (parent && !visited.has(parent)) {
    visited.add(parent)
    found.push(findGroup(groups, parent))
    parent = parentOf(groups, parent)
  }
  return found
}

/** 最外层的折叠祖先组；没有返回 null。投影时可见实体是最外层折叠组。 */
function outermostCollapsedAncestor(groups, unitId) {
  return ancestorGroups(groups, unitId).filter((group) => group.collapsed).at(-1)?.id || null
}

export function parseHandle(handle) {
  if (typeof handle !== 'string') return null
  const index = handle.lastIndexOf(':')
  if (index <= 0 || index === handle.length - 1) return null
  return { nodeId: handle.slice(0, index), port: handle.slice(index + 1) }
}

/** 组卡片 handle 名：`${节点id}:${端口名}`。投影与端口清单共用这一处定义。 */
function portHandle(nodeId, port) {
  return `${nodeId}:${port}`
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

/** 新连线是否允许：两端是不同可见实体，且解析回真实端口后类型兼容。
 *  跨子图边界的连线放行——折叠组的边界边正由此产生。
 *  允许时返回解析后的真实连接，不允许返回 null。 */
export function connectionAllowed(nodes, groups, connection) {
  const { source, target } = connection || {}
  if (!source || !target || source === target) return null
  const real = resolveConnection(groups, connection)
  if (!real || real.source === real.target) return null
  const sourceNode = nodes.find((node) => node.id === real.source)
  const targetNode = nodes.find((node) => node.id === real.target)
  if (!sourceNode || !targetNode) return null
  const output = (sourceNode.data?.outPorts || []).find((port) => port.name === real.sourceHandle)
  const input = (targetNode.data?.inPorts || []).find((port) => port.name === real.targetHandle)
  return output && input && input.types.includes(output.type) ? real : null
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
        ? portHandle(edge.source, edge.sourceHandle)
        : edge.sourceHandle,
      target: targetGroup || edge.target,
      targetHandle: targetGroup
        ? portHandle(edge.target, edge.targetHandle)
        : edge.targetHandle,
    })
  }
  return projected
}

/** 组端口 = 叶子组件里所有「没有被内部边占用」的端口，并上跨组边界边用到的端口。
 *  叶子递归穿透子组；内部边指两端都在叶子集合里的边。
 *  输出端口取并集是必须的：一个输出可以同时喂内部和外部，只算「空闲」会吞掉跨边界那条边。 */
function collectGroupPorts(groups, edges, nodeById) {
  const ports = new Map()
  const pointKey = (nodeId, port) => `${nodeId}\u0000${port}`

  const entryFor = (node, port, side) => ({
    name: portHandle(node.id, port.name),
    ...(side === 'in' ? { types: port.types } : { type: port.type }),
    color: port.color,
    label: `${node.data?.title || node.id}.${port.name}`,
    title: port.full || '',
  })

  const boundaryEntry = (nodeId, portName, side) => {
    const node = nodeById.get(nodeId)
    const list = side === 'in' ? node?.data?.inPorts : node?.data?.outPorts
    const port = (list || []).find((item) => item.name === portName)
    return port ? entryFor(node, port, side) : null
  }

  for (const group of groups) {
    const leafIds = memberLeaves(groups, group.id).map((leaf) => leaf.nodeId)
    const leafSet = new Set(leafIds)
    const usedInputs = new Set()
    const usedOutputs = new Set()
    const crossingIn = []
    const crossingOut = []

    for (const edge of edges) {
      if (!edge.source || !edge.target) continue
      const sourceIn = leafSet.has(edge.source)
      const targetIn = leafSet.has(edge.target)
      if (!sourceIn && !targetIn) continue
      if (sourceIn && targetIn) {
        usedOutputs.add(pointKey(edge.source, edge.sourceHandle))
        usedInputs.add(pointKey(edge.target, edge.targetHandle))
      } else if (sourceIn) {
        crossingOut.push({ nodeId: edge.source, port: edge.sourceHandle })
      } else {
        crossingIn.push({ nodeId: edge.target, port: edge.targetHandle })
      }
    }

    const inPorts = new Map()
    const outPorts = new Map()

    for (const nodeId of leafIds) {
      const node = nodeById.get(nodeId)
      if (!node) continue
      for (const port of node.data?.inPorts || []) {
        if (usedInputs.has(pointKey(nodeId, port.name))) continue
        const entry = entryFor(node, port, 'in')
        inPorts.set(entry.name, entry)
      }
      for (const port of node.data?.outPorts || []) {
        if (usedOutputs.has(pointKey(nodeId, port.name))) continue
        const entry = entryFor(node, port, 'out')
        outPorts.set(entry.name, entry)
      }
    }
    for (const { nodeId, port } of crossingIn) {
      const entry = port && boundaryEntry(nodeId, port, 'in')
      if (!entry) continue
      inPorts.set(entry.name, entry)
    }
    for (const { nodeId, port } of crossingOut) {
      const entry = port && boundaryEntry(nodeId, port, 'out')
      if (!entry) continue
      outPorts.set(entry.name, entry)
    }

    ports.set(group.id, { inPorts: [...inPorts.values()], outPorts: [...outPorts.values()] })
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
  const ports = collectGroupPorts(groups, edges, nodeById)
  const previous = new Map(nodes.map((node) => [node.id, node]))

  const result = componentNodes.map((node) => ({
    ...node,
    hidden: Boolean(outermostCollapsedAncestor(groups, node.id)),
  }))

  for (const group of groups) {
    const hidden = Boolean(outermostCollapsedAncestor(groups, group.id))
    const previousNode = previous.get(group.id)
    // frame 与组卡片共用 group.id；Vue Flow 的 parseNode 用 Object.assign 复用同 id 节点，
    // 某个形态没声明的交互字段会沿用上一个形态的值。
    // card 分支刻意不写 selected：靠这次复用保留选中，重命名/重投影时选中不会丢；
    // 改这两个分支的交互字段时要成对检查。
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
        draggable: true,
        connectable: true,
        zIndex: 0,
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
        selected: false,
        zIndex: -1,
        data: {
          groupId: group.id,
          title: group.title,
          count: membersOf(group).length,
          groups,
        },
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

/** 祖孙关系；带环保护。 */
function isAncestor(groups, ancestorId, unitId) {
  return ancestorGroups(groups, unitId).some((group) => group.id === ancestorId)
}

function outermostUnit(groups, unitId) {
  return findGroup(groups, unitId)
    ? unitId
    : ancestorGroups(groups, unitId).at(-1)?.id || unitId
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

export function nextGroupId(groups, nodes = []) {  const used = new Set([
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

/**
 * 给一层子图改名：只改目标组的 title；trim 后为空不接受，返回原数组。
 * 40 码点是数据约束，按码点切（`slice` 切的是 UTF-16 码元，会把代理对截成半个）。
 */
export function renameGroup(groups, groupId, title) {
  const value = Array.from(String(title ?? '').trim()).slice(0, 40).join('')
  if (!value) return groups
  return groups.map((group) => (group.id === groupId ? { ...group, title: value } : group))
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
