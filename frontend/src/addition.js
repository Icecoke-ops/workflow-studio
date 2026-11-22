/** 顶层 addition（编辑器私有数据）的读写。这个格式的全部知识都放在本文件。 */

export const ADDITION_CLIENT = 'workflow-studio'
export const ADDITION_VERSION = 1

const WARNING_FOREIGN = '此文件的附加信息由其他客户端生成'
const WARNING_VERSION = '此文件的附加信息版本无法识别或高于当前编辑器，已忽略'

/** groups 数组的导入校验：id 必须是非空字符串、去重、避开节点 id；title 字符串化、位置必须有限。 */
function normalizeGroups(value, nodeIds = new Set()) {
  if (!Array.isArray(value)) return { groups: [], dropped: 0 }
  const groups = []
  const seen = new Set()
  let dropped = 0
  for (const entry of value) {
    if (!entry || typeof entry !== 'object') {
      dropped += 1
      continue
    }
    const id = typeof entry.id === 'string' ? entry.id.trim() : ''
    if (!id || seen.has(id) || nodeIds.has(id)) {
      dropped += 1
      continue
    }
    seen.add(id)
    const next = {
      ...entry,
      id,
      title: entry.title === undefined || entry.title === null ? '' : String(entry.title).trim(),
    }
    if ('position' in next) {
      const x = next.position?.x
      const y = next.position?.y
      if (Number.isFinite(x) && Number.isFinite(y)) next.position = { x, y }
      else delete next.position
    }
    groups.push(next)
  }
  return { groups, dropped }
}

/** 根对象里声明过的节点 id：组 id 撞节点 id 时整组丢掉，避免画布出现两个同 id 节点。 */
function nodeIdsOf(raw) {
  const ids = new Set()
  const nodes = Array.isArray(raw?.nodes) ? raw.nodes : []
  for (const node of nodes) {
    if (node && typeof node.id === 'string' && node.id) ids.add(node.id)
  }
  return ids
}

/**
 * 读工作流根对象里的 addition。
 * 只认识本客户端且版本不高于当前的文件；读不懂的整块放进 preserved，保存时原样写回。
 * 返回结果同时也是 buildAddition 的输入——调用方只搬运，不解释字段。
 * droppedGroups 是被丢掉的非法分组数，调用方提示给用户，不静默吞。
 */
export function readAddition(raw) {
  const addition = raw && typeof raw === 'object' ? raw.addition : null
  if (!addition || typeof addition !== 'object' || Array.isArray(addition)) {
    return { positions: {}, groups: [], droppedGroups: 0, warning: '', preserved: null }
  }
  if (addition.client !== ADDITION_CLIENT) {
    return {
      positions: {},
      groups: [],
      droppedGroups: 0,
      warning: WARNING_FOREIGN,
      preserved: addition,
    }
  }
  const version = Number(addition.version)
  if (!Number.isFinite(version) || version > ADDITION_VERSION) {
    return {
      positions: {},
      groups: [],
      droppedGroups: 0,
      warning: WARNING_VERSION,
      preserved: addition,
    }
  }
  const normalized = normalizeGroups(addition.groups, nodeIdsOf(raw))
  return {
    positions:
      addition.positions && typeof addition.positions === 'object' && !Array.isArray(addition.positions)
        ? addition.positions
        : {},
    groups: normalized.groups,
    droppedGroups: normalized.dropped,
    warning: '',
    preserved: null,
  }
}

/**
 * 从编辑器状态生成 addition。
 * addition 是 readAddition 的结果（或 null）；读不懂时原样返回 preserved（引用与键序都不动）。
 * groups 是 groups.js 序列化后的条目；不传时沿用导入时读到的那份（保证往返不变）。
 */
export function buildAddition({ nodes, addition, groups }) {
  if (addition && addition.preserved) return addition.preserved
  const positions = {}
  for (const node of nodes) {
    const x = node.position?.x
    const y = node.position?.y
    if (Number.isFinite(x) && Number.isFinite(y)) positions[node.id] = { x, y }
  }
  return {
    client: ADDITION_CLIENT,
    version: ADDITION_VERSION,
    positions,
    groups: normalizeGroups(groups !== undefined ? groups : addition ? addition.groups : []).groups,
  }
}
