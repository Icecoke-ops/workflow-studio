<script setup>
defineProps({
  changed: { type: Boolean, default: false },
  missing: { type: Boolean, default: false },
})

const emit = defineEmits(['reload'])
</script>

<template>
  <div v-if="changed || missing" class="sync-bar" :class="{ 'is-missing': missing }" role="status">
    <span class="sync-dot" aria-hidden="true">●</span>
    <span class="sync-text">{{ missing ? '文件已从磁盘删除' : '磁盘已更新，未同步' }}</span>
    <button v-if="!missing" class="sync-action" type="button" @click="emit('reload')">
      重新加载
    </button>
  </div>
</template>

<style scoped>
.sync-bar {
  display: flex;
  flex: none;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  background: #fdf6ec;
  border-bottom: 1px solid #f5dab1;
  color: #b88230;
  font-size: 12px;
  line-height: 18px;
}

.sync-dot {
  flex: none;
  font-size: 10px;
}

.sync-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sync-action {
  flex: none;
  margin-left: auto;
  padding: 0 6px;
  border: 1px solid #f5dab1;
  border-radius: 3px;
  background: #fff;
  color: #b88230;
  font: inherit;
  cursor: pointer;
}

.sync-action:hover {
  background: #fdf0dd;
}

.sync-bar.is-missing {
  background: #fef0f0;
  border-bottom-color: #fde2e2;
  color: #c45656;
}
</style>
