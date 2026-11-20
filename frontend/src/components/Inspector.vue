<script setup>
// 右栏占位：参数已搬到节点卡片上（ConfigForm.vue），这里留给后续智能生成。
const emit = defineEmits(['collapse'])
</script>

<template>
  <aside class="inspector">
    <div class="panel-title">
      <span>智能生成</span>
      <button
        class="panel-collapse"
        type="button"
        title="收起右栏"
        aria-label="收起右栏"
        @click="emit('collapse')"
      >
        ▶
      </button>
    </div>
    <div class="smart-placeholder">
      <div class="smart-icon">✦</div>
      <p class="smart-title">智能生成流程图 · 开发中</p>
      <p class="muted small">后续在这里接入智能体，根据需求自动生成工作流。</p>
    </div>
  </aside>
</template>

<style scoped>
.inspector {
  display: flex;
  flex-direction: column;
  width: 100%;
  flex: none;
  background: var(--panel);
  border-left: 1px solid var(--border);
  min-height: 0;
  overflow: auto;
}

.smart-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 24px 18px;
  text-align: center;
}

.smart-icon {
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: linear-gradient(135deg, #ecf5ff, #f0f9eb);
  color: var(--primary);
  font-size: 20px;
}

.smart-title {
  margin: 4px 0 0;
  font-size: 13px;
  font-weight: 600;
}

.smart-placeholder .small {
  margin: 0;
  line-height: 18px;
  max-width: 230px;
}
</style>
