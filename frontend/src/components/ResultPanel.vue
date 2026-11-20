<script setup>
import { computed } from 'vue'

const props = defineProps({
  report: { type: Object, default: null },
  run: { type: Object, default: null },
})

const activeTab = defineModel('activeTab', { type: String, default: 'validate' })
const emit = defineEmits(['collapse'])

const totalMs = computed(() => {
  const nodes = props.run?.nodes
  if (!nodes?.length) return null
  const sum = nodes.reduce((acc, item) => acc + (item.ms || 0), 0)
  return Math.round(sum * 10) / 10
})

const failedCount = computed(() => props.run?.failedIds?.length || 0)
</script>

<template>
  <section class="result-panel">
    <button
      class="panel-collapse result-collapse"
      type="button"
      title="收起底部"
      aria-label="收起底部"
      @click="emit('collapse')"
    >
      ▼
    </button>
    <el-tabs v-model="activeTab" class="result-tabs">
      <el-tab-pane name="validate">
        <template #label>
          <span>校验结果</span>
          <span v-if="report && report.errors.length" class="tab-count error">
            {{ report.errors.length }}
          </span>
          <span v-else-if="report && report.warnings.length" class="tab-count warn">
            {{ report.warnings.length }}
          </span>
        </template>

        <div class="pane-body">
          <div v-if="!report" class="placeholder">
            点击顶部「校验」，运行前检查端口、类型和参数配置。
          </div>
          <template v-else>
            <div class="summary">
              <el-tag size="small" :type="report.ok ? 'success' : 'danger'" effect="plain">
                {{ report.ok ? '校验通过' : '校验失败' }}
              </el-tag>
              <span class="muted">{{ report.errors.length }} 个错误 · {{ report.warnings.length }} 个警告</span>
              <span v-if="report.order.length" class="muted">
                执行顺序：{{ report.order.join(' → ') }}
              </span>
            </div>
            <div v-for="(message, index) in report.errors" :key="'e' + index" class="msg error">
              {{ message }}
            </div>
            <div v-for="(message, index) in report.warnings" :key="'w' + index" class="msg warn">
              {{ message }}
            </div>
          </template>
        </div>
      </el-tab-pane>

      <el-tab-pane name="run">
        <template #label>
          <span>运行结果</span>
          <span v-if="failedCount" class="tab-count error">{{ failedCount }}</span>
        </template>

        <div class="pane-body">
          <div v-if="!run" class="placeholder">
            点击顶部「运行」，这里会显示每个节点的耗时和各端口输出预览。
          </div>
          <template v-else>
            <div class="summary">
              <el-tag size="small" :type="run.ok ? 'success' : 'danger'" effect="plain">
                {{ run.ok ? '运行成功' : '运行失败' }}
              </el-tag>
              <span class="muted">
                {{ run.nodes.length }} 个节点返回<template v-if="totalMs !== null"> · 合计 {{ totalMs }} ms</template>
              </span>
              <span v-if="failedCount" class="failed-ids">失败节点：{{ run.failedIds.join(', ') }}</span>
            </div>

            <div v-for="(message, index) in run.errors" :key="'re' + index" class="msg error">
              {{ message }}
            </div>
            <div v-for="(message, index) in run.warnings" :key="'rw' + index" class="msg warn">
              {{ message }}
            </div>

            <div
              v-for="row in run.nodes"
              :key="row.id"
              class="run-row"
              :class="{ failed: row.failed }"
            >
              <div class="run-head">
                <el-tag size="small" :type="row.failed ? 'danger' : 'success'" effect="plain">
                  {{ row.failed ? '失败' : '成功' }}
                </el-tag>
                <span class="run-id">{{ row.id }}</span>
                <span class="run-name">{{ row.component }}</span>
                <span v-if="!row.failed" class="run-ms">{{ row.ms.toFixed(1) }} ms</span>
              </div>
              <div v-if="row.error" class="msg error">{{ row.error }}</div>
              <div v-for="output in row.outputs" :key="output.port" class="output">
                <span class="output-port">{{ output.port }}</span>
                <pre class="output-text">{{ output.text }}</pre>
              </div>
              <div v-if="!row.outputs.length && !row.error" class="muted small">（无输出）</div>
            </div>

            <div v-if="!run.nodes.length && !run.errors.length" class="placeholder">
              这次运行没有返回节点结果。
            </div>
          </template>
        </div>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
.result-panel {
  position: relative;
  height: 232px;
  flex: none;
  background: var(--panel);
  border-top: 1px solid var(--border);
  min-height: 0;
}

.result-collapse {
  position: absolute;
  top: 6px;
  right: 10px;
  margin-left: 0;
  z-index: 2;
}

.result-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.result-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 12px;
}

.result-tabs :deep(.el-tabs__item) {
  height: 34px;
  line-height: 34px;
  font-size: 12px;
}

.result-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
}

.result-tabs :deep(.el-tab-pane) {
  height: 100%;
}

.pane-body {
  height: 100%;
  overflow: auto;
  padding: 8px 14px 12px;
}

.summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 6px;
  font-size: 12px;
}

.tab-count {
  display: inline-block;
  min-width: 16px;
  height: 16px;
  line-height: 16px;
  padding: 0 4px;
  margin-left: 4px;
  border-radius: 8px;
  font-size: 10px;
  text-align: center;
  color: #fff;
}

.tab-count.error {
  background: var(--danger);
}

.tab-count.warn {
  background: var(--warning);
}

.msg {
  font-size: 12px;
  line-height: 18px;
  padding: 3px 8px;
  border-radius: 4px;
  margin: 3px 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg.error {
  background: #fef0f0;
  color: #c45656;
}

.msg.warn {
  background: #fdf6ec;
  color: #b88230;
}

.failed-ids {
  color: var(--danger);
  font-size: 12px;
}

.run-row {
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 6px 9px;
  margin: 6px 0;
  background: #fff;
}

.run-row.failed {
  border-color: #fbc4c4;
  background: #fff8f8;
}

.run-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.run-id {
  font-weight: 600;
  font-family: Consolas, 'Courier New', monospace;
}

.run-name {
  color: var(--text-2);
  font-family: Consolas, 'Courier New', monospace;
}

.run-ms {
  margin-left: auto;
  color: var(--muted);
  font-size: 11px;
}

.output {
  margin-top: 4px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.output-port {
  flex: none;
  min-width: 64px;
  color: var(--primary);
  font-size: 11px;
  font-family: Consolas, 'Courier New', monospace;
  padding-top: 1px;
}

.output-text {
  margin: 0;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 11px;
  line-height: 16px;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 96px;
  overflow: auto;
  flex: 1;
  background: #f7f8fa;
  border-radius: 4px;
  padding: 3px 6px;
}

.placeholder {
  color: var(--muted);
  padding: 18px 4px;
}
</style>
