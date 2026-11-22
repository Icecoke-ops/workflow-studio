<script setup>
import { ref, watch } from 'vue'
import { phaseLabel, isBusy } from '../debug/model.js'

const props = defineProps({
  view: { type: Object, required: true },
  logs: { type: Array, default: () => [] },
  error: { type: String, default: '' },
})

const emit = defineEmits(['continue', 'stop'])

const box = ref(null)
// 贴底才自动滚；用户往上翻了就由用户自己控制
let stick = true

function onScroll() {
  const el = box.value
  if (!el) return
  stick = el.scrollHeight - el.scrollTop - el.clientHeight <= 24
}

// 日志换了新数组就滚：贴底才跟，用户往上翻了就不抢；清空（新会话）时恢复贴底
watch(
  () => props.logs,
  () => {
    if (!props.logs.length) {
      stick = true
      return
    }
    if (!stick) return
    const el = box.value
    if (el) el.scrollTop = el.scrollHeight
  },
  { flush: 'post' },
)
</script>

<template>
  <section class="debug-panel">
    <div class="debug-head">
      <span class="debug-phase" :class="`phase-${view.phase}`">
        {{ phaseLabel(view.phase) }}
      </span>
      <span v-if="view.current" class="debug-current">当前 {{ view.current }}</span>
      <span class="debug-spacer"></span>
      <el-button
        size="small"
        :disabled="isBusy(view.phase)"
        @click="emit('continue')"
      >
        继续
      </el-button>
      <el-button size="small" :disabled="!isBusy(view.phase)" @click="emit('stop')">
        停止
      </el-button>
    </div>

    <div v-if="error" class="debug-error">{{ error }}</div>

    <div ref="box" class="debug-log" @scroll.passive="onScroll">
      <div
        v-for="(line, index) in logs"
        :key="index"
        class="log-line"
        :class="line.stream === 'stderr' ? 'is-stderr' : 'is-stdout'"
      >
        <span v-if="line.node" class="log-node">[{{ line.node }}]</span>{{ line.text }}
      </div>
      <div v-if="!logs.length" class="debug-empty">等待日志…</div>
    </div>
  </section>
</template>

<style scoped>
.debug-panel {
  position: relative;
  flex: none;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border-top: 1px solid var(--border);
}

.debug-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 12px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}

.debug-phase {
  font-weight: 600;
  color: var(--muted);
}

.debug-phase.phase-running {
  color: var(--primary);
}

.debug-phase.phase-paused {
  color: var(--warning);
}

.debug-phase.phase-failed {
  color: var(--danger);
}

.debug-current {
  color: var(--text-2);
  font-family: Consolas, 'Courier New', monospace;
}

.debug-spacer {
  flex: 1;
}

.debug-head :deep(.el-button + .el-button) {
  margin-left: 0;
}

.debug-error {
  flex: none;
  padding: 4px 12px;
  background: rgba(245, 108, 108, 0.08);
  color: var(--danger);
  font-size: 12px;
  line-height: 18px;
  border-bottom: 1px solid var(--border);
}

.debug-log {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 6px 12px 10px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 11px;
  line-height: 16px;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.log-line.is-stderr {
  color: var(--danger);
}

.log-node {
  margin-right: 4px;
  color: var(--muted);
}

.debug-empty {
  color: var(--muted);
  font-family: inherit;
}
</style>
