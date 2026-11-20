<script setup>
import { computed } from 'vue'

const visible = defineModel('visible', { type: Boolean, default: false })
const rows = defineModel('rows', { type: Array, default: () => [] })

const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/

const duplicateKeys = computed(() => {
  const counts = new Map()
  for (const row of rows.value) {
    if (row.key) counts.set(row.key, (counts.get(row.key) || 0) + 1)
  }
  return new Set([...counts].filter(([, count]) => count > 1).map(([key]) => key))
})

function isInvalid(row) {
  return row.key.length > 0 && !NAME_RE.test(row.key)
}

function isDuplicate(row) {
  return Boolean(row.key) && duplicateKeys.value.has(row.key)
}

function addRow() {
  rows.value = [...rows.value, { key: '', value: '' }]
}

function removeRow(index) {
  rows.value = rows.value.filter((_, rowIndex) => rowIndex !== index)
}
</script>

<template>
  <el-drawer v-model="visible" title="环境变量" size="420px" direction="rtl">
    <p class="env-tip">
      这些变量在工作流运行时注入。<code>workspace</code> / <code>engine_version</code> /
      <code>workflow</code> / <code>run_id</code> 由引擎自动提供，同名会被这里覆盖，不建议。
    </p>

    <div v-if="!rows.length" class="env-empty">还没有环境变量</div>

    <div v-for="(row, index) in rows" :key="index" class="env-row">
      <div class="env-fields">
        <el-input
          v-model="row.key"
          size="small"
          placeholder="名称"
          :class="{ invalid: isInvalid(row) || isDuplicate(row) }"
        />
        <el-input v-model="row.value" size="small" placeholder="值" />
        <el-button size="small" text type="danger" @click="removeRow(index)">删除</el-button>
      </div>
      <div v-if="isInvalid(row)" class="env-error">
        名称需匹配 [A-Za-z_][A-Za-z0-9_]*
      </div>
      <div v-else-if="isDuplicate(row)" class="env-error">名称重复</div>
    </div>

    <el-button size="small" class="env-add" @click="addRow">添加一行</el-button>
  </el-drawer>
</template>

<style scoped>
.env-tip {
  margin: 0 0 14px;
  color: var(--text-2);
  font-size: 12px;
  line-height: 19px;
}

.env-tip code {
  padding: 0 3px;
  border-radius: 3px;
  background: #f0f2f5;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 11px;
}

.env-empty {
  padding: 10px 0 14px;
  color: var(--muted);
  font-size: 12px;
}

.env-row {
  margin-bottom: 10px;
}

.env-fields {
  display: flex;
  align-items: center;
  gap: 6px;
}

.env-fields :deep(.el-input) {
  flex: 1;
  min-width: 0;
}

.env-fields :deep(.invalid .el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--danger) inset;
}

.env-error {
  margin-top: 2px;
  color: var(--danger);
  font-size: 11px;
  line-height: 15px;
}

.env-add {
  margin-top: 4px;
}
</style>
