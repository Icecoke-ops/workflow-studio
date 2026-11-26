<script setup>
import { computed } from 'vue'

const props = defineProps({
  doc: { type: Object, required: true },
})

function formatSize(size) {
  if (!Number.isFinite(size)) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

const notice = computed(() => {
  if (props.doc.fileKind === 'binary') return '不是 UTF-8 文本（或含二进制数据），不能以文本方式显示。'
  if (props.doc.fileKind === 'too_large') {
    return `文件太大（${formatSize(props.doc.size)}），不在浏览器里打开。`
  }
  return ''
})
</script>

<template>
  <section class="text-viewer">
    <div v-if="notice" class="text-notice">{{ notice }}</div>
    <pre v-else class="text-body">{{ doc.text }}</pre>
  </section>
</template>

<style scoped>
.text-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  overflow: auto;
  background: var(--panel);
}

.text-notice {
  padding: 24px 20px;
  color: var(--muted);
  font-size: 13px;
}

.text-body {
  margin: 0;
  padding: 14px 18px 40px;
  color: var(--text-2);
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 19px;
  white-space: pre;
  tab-size: 2;
}
</style>
