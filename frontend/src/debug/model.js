/** 调试视图的纯函数：状态合并、日志追加、阶段/状态映射。
 *  协议见 docs/CONTRACT.md §9.6；这里不 import Vue，可被独立测。 */

const LOG_LIMIT = 5000

export const EMPTY_VIEW = Object.freeze({
  phase: 'idle',
  current: null,
  nodes: {},
})

const PHASES = ['idle', 'running', 'paused', 'ended', 'failed']

const PHASE_LABELS = {
  idle: '空闲',
  running: '运行中',
  paused: '已暂停',
  ended: '已结束',
  failed: '已失败',
}

const STATUS_LABELS = {
  unrun: '未运行',
  fresh: '已运行',
  stale: '已过期',
  failed: '失败',
}

export function phaseLabel(phase) {
  return PHASE_LABELS[phase] || '未知'
}

/** 节点状态 -> 面板里的中文标签；未知按未运行。 */
export function statusLabel(status) {
  return Object.hasOwn(STATUS_LABELS, status) ? STATUS_LABELS[status] : STATUS_LABELS.unrun
}

/** 有命令在执行；此时不接受新的 run_node / continue。 */
export function isBusy(phase) {
  return phase === 'running'
}

/** 节点状态 -> 卡片 class；非调试态（null）不挂 class，未知状态按 unrun 处理。 */
export function nodeStatusClass(status) {
  if (status === null || status === undefined || status === '') return ''
  return `status-${normalizeStatus(status)}`
}

function normalizeStatus(status) {
  return Object.hasOwn(STATUS_LABELS, status) ? status : 'unrun'
}

/** outputs 只收「端口名 -> 字符串预览」；非对象、数组、非字符串值一律丢掉。 */
function normalizeOutputs(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return Object.fromEntries(Object.entries(value).filter(([, text]) => typeof text === 'string'))
}

/** 节点四件套：状态必留，耗时/错误按类型收，输出留成可渲染的对象。 */
function normalizeNode(info) {
  return {
    status: normalizeStatus(info.status),
    duration_ms: Number.isFinite(info.duration_ms) ? info.duration_ms : null,
    error: typeof info.error === 'string' && info.error ? info.error : null,
    outputs: normalizeOutputs(info.outputs),
  }
}

/** 合并一份 state 快照：节点表整体替换，保留状态、耗时、错误和每个端口的输出预览。 */
export function applyState(view, state) {
  const previous = view && typeof view === 'object' ? view : EMPTY_VIEW
  if (!state || typeof state !== 'object') return previous

  const source = state.nodes && typeof state.nodes === 'object' ? state.nodes : {}
  // Object.fromEntries 定义自有属性：__proto__ 会被当成普通节点 id，而不是原型 setter
  const nodes = Object.fromEntries(
    Object.entries(source)
      .filter(([, info]) => info && typeof info === 'object' && !Array.isArray(info))
      .map(([id, info]) => [id, normalizeNode(info)]),
  )

  return {
    phase: PHASES.includes(state.phase) ? state.phase : previous.phase,
    current: typeof state.current === 'string' ? state.current : null,
    nodes,
  }
}

/** 追加一条日志；只留 node/stream/text，超过上限丢头部。 */
export function appendLog(lines, message) {
  const base = Array.isArray(lines) ? lines : []
  if (typeof message?.text !== 'string' || !message.text) return base
  const next = base.concat({
    node: typeof message.node === 'string' && message.node ? message.node : null,
    stream: message.stream === 'stderr' ? 'stderr' : 'stdout',
    text: message.text,
  })
  return next.length > LOG_LIMIT ? next.slice(-LOG_LIMIT) : next
}
