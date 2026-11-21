/** 顶层 addition（编辑器私有数据）的读写。这个格式的全部知识都放在本文件。 */

export const ADDITION_CLIENT = 'workflow-studio'
export const ADDITION_VERSION = 1

const WARNING_FOREIGN = '此文件的附加信息由其他客户端生成'
const WARNING_VERSION = '此文件的附加信息版本无法识别或高于当前编辑器，已忽略'

function emptyResult() {
  return { positions: {}, groups: [], warning: '', preserved: null }
}

/**
 * 读工作流根对象里的 addition。
 * 只认识本客户端且版本不高于当前的文件；读不懂的整块放进 preserved，保存时原样写回。
 * 返回结果同时也是 buildAddition 的输入——调用方只搬运，不解释字段。
 */
export function readAddition(raw) {
  const addition = raw && typeof raw === 'object' ? raw.addition : null
  if (!addition || typeof addition !== 'object' || Array.isArray(addition)) return emptyResult()
  if (addition.client !== ADDITION_CLIENT) {
    return { positions: {}, groups: [], warning: WARNING_FOREIGN, preserved: addition }
  }
  const version = Number(addition.version)
  if (!Number.isFinite(version) || version > ADDITION_VERSION) {
    return { positions: {}, groups: [], warning: WARNING_VERSION, preserved: addition }
  }
  return {
    positions:
      addition.positions && typeof addition.positions === 'object' && !Array.isArray(addition.positions)
        ? addition.positions
        : {},
    groups: Array.isArray(addition.groups) ? addition.groups : [],
    warning: '',
    preserved: null,
  }
}

/**
 * 从编辑器状态生成 addition。
 * addition 是 readAddition 的结果（或 null）；读不懂时原样返回 preserved（引用与键序都不动）。
 */
export function buildAddition({ nodes, addition }) {
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
    groups: addition ? addition.groups : [],
  }
}
