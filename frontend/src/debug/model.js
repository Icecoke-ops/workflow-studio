/** 调试视图的纯函数：状态合并、日志追加、阶段/状态映射。
 *  协议见 docs/CONTRACT.md §9.6；这里不 import Vue，可被独立测。 */

const LOG_LIMIT = 5000

export const EMPTY_VIEW = Object.freeze({
  phase: 'idle',
  current: null,
  nodes: {},
})

const PHASES = ['idle', 'running', 'paused', 'ended', 'failed']
const STATUSES = ['unrun', 'fresh', 'stale', 'failed']

const PHASE_LABELS = {
  idle: '空闲',
  running: '运行中',
  paused: '已暂停',
  ended: '已结束',
  failed: '已失败',
}

export function phaseLabel(phase) {
  return PHASE_LABELS[phase] || '未知'
}

/** 有命令在执行；此时不接受新的 run_node / continue。 */
export function isBusy(phase) {
  return phase === 'running'
}

/** 节点状态 -> 卡片 class；非调试态（null）不挂 class，未知状态按 unrun 处理。 */
export function nodeStatusClass(status) {
  if (status === null || status === undefined || status === '') return ''
  return `status-${STATUSES.includes(status) ? status : 'unrun'}`
}

function normalizeStatus(status) {
  return STATUSES.includes(status) ? status : 'unrun'
}

/** 合并一份 state 快照：节点表整体替换，只留节点状态（其余字段界面不读）。 */
export function applyState(view, state) {
  const previous = view && typeof view === 'object' ? view : EMPTY_VIEW
  if (!state || typeof state !== 'object') return previous

  const source = state.nodes && typeof state.nodes === 'object' ? state.nodes : {}
  const nodes = {}
  for (const [id, info] of Object.entries(source)) {
    if (!info || typeof info !== 'object') continue
    nodes[id] = { status: normalizeStatus(info.status) }
  }

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
