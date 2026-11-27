<script setup>
import { computed, ref, watch } from 'vue'
import { fetchFile, payloadErrors } from '../api'
import { useFileSync } from '../fileWatch'
import FileSyncBar from './FileSyncBar.vue'

const props = defineProps({
  path: { type: String, required: true },
})

const file = ref(null)
const error = ref('')

function formatSize(size) {
  if (!Number.isFinite(size)) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

const notice = computed(() => {
  if (!file.value) return ''
  if (file.value.kind === 'binary') return '不是 UTF-8 文本（或含二进制数据），不能以文本方式显示。'
  if (file.value.kind === 'too_large') {
    return `文件太大（${formatSize(file.value.size)}），不在浏览器里打开。`
  }
  return ''
})

/** 读一次文件；成功返回 true。 */
async function load() {
  try {
    const data = await fetchFile(props.path)
    if (data.ok === false) throw new Error(payloadErrors(data))
    file.value = data
    error.value = ''
    return true
  } catch (err) {
    file.value = null
    error.value = `读取失败：${err.message}`
    return false
  }
}

async function reloadFile() {
  if (await load()) markSynced()
}

const { changed, missing, reload, markSynced } = useFileSync(() => props.path, reloadFile)

watch(
  () => props.path,
  () => {
    file.value = null
    error.value = ''
    void load()
  },
  { immediate: true },
)
</script>

<template>
  <section class="text-viewer">
    <FileSyncBar :changed="changed" :missing="missing" @reload="reload" />
    <div class="text-scroll">
      <div v-if="error" class="text-notice">{{ error }}</div>
      <div v-else-if="notice" class="text-notice">{{ notice }}</div>
      <pre v-else-if="file" class="text-body">{{ file.text }}</pre>
      <div v-else class="text-notice">加载中…</div>
    </div>
  </section>
</template>

<style scoped>
.text-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  overflow: hidden;
  background: var(--panel);
}

.text-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
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
