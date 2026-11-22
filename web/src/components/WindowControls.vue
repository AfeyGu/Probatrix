<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({ windowApi: { type: Object, required: true } })
const maximized = ref(false)
const pending = ref(false)
const maximizeLabel = computed(() => maximized.value ? '还原窗口' : '最大化')

async function syncMaximized() {
  try {
    maximized.value = await props.windowApi.isMaximized()
  } catch (error) {
    console.warn('无法读取窗口状态', error)
  }
}

onMounted(() => {
  syncMaximized()
  window.addEventListener('resize', syncMaximized)
})
onUnmounted(() => window.removeEventListener('resize', syncMaximized))

async function run(action, ...args) {
  if (pending.value) return
  pending.value = true
  try {
    await props.windowApi[action](...args)
    if (action === 'toggleMaximize') await syncMaximized()
  } catch (error) {
    console.error('窗口操作失败', error)
    ElMessage.error('窗口操作失败')
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="window-controls" role="group" aria-label="窗口操作">
    <el-button text class="window-control" title="最小化" aria-label="最小化"
               :aria-disabled="pending" @click="run('minimize')">
      <span class="window-glyph" aria-hidden="true">&#xE921;</span>
    </el-button>
    <el-button text class="window-control" :title="maximizeLabel" :aria-label="maximizeLabel"
               :aria-disabled="pending" @click="run('toggleMaximize')">
      <span class="window-glyph" aria-hidden="true">{{ maximized ? '\uE923' : '\uE922' }}</span>
    </el-button>
    <el-button text class="window-control window-close" title="关闭" aria-label="关闭"
               :aria-disabled="pending" @click="run('close')">
      <span class="window-glyph" aria-hidden="true">&#xE8BB;</span>
    </el-button>
  </div>
  <Teleport to="body">
    <div v-if="!maximized" class="window-resize-corner" aria-hidden="true"
         @mousedown.left.prevent="run('startResizeDragging', 'SouthEast')" />
  </Teleport>
</template>

<style scoped>
.window-resize-corner {
  position: fixed;
  right: 0;
  bottom: 0;
  width: calc(2 * var(--cb-panel-gap));
  height: calc(2 * var(--cb-panel-gap));
  /* 只接收卡片外的鼠标事件，留出预览卡底部和右侧的滚动条。 */
  clip-path: polygon(50% 0, 100% 0, 100% 100%, 0 100%, 0 50%, 50% 50%);
  cursor: nwse-resize;
}

.window-controls {
  display: flex;
  flex: none;
  align-items: center;
  height: var(--cb-toolbar-control-height);
  padding-inline: 2px;
  border-radius: var(--cb-r-pill);
  corner-shape: round;
  background: var(--cb-surface);
  box-shadow: inset 0 0 0 1px var(--cb-border), inset 0 1px 0 var(--cb-glass-hi);
}

.window-control.el-button.is-text {
  width: 40px;
  height: calc(100% - 4px);
  margin: 0;
  padding: 0;
  color: var(--cb-text);
  border-radius: var(--cb-r-pill);
  corner-shape: round;
}

.window-control.el-button.is-text:active {
  background: var(--cb-active);
}

.window-close.el-button.is-text:hover {
  background: var(--el-color-danger-light-9);
  color: var(--cb-bad);
}

.window-control:focus-visible {
  outline: 2px solid var(--cb-accent);
  outline-offset: -2px;
}

.window-control[aria-disabled='true'] {
  opacity: .6;
  cursor: default;
}

.window-glyph {
  font: 12px/1 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
}
</style>
