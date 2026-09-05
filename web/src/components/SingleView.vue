<script setup>
/** 单项视图：左侧参数表单（声明即界面），右侧计算书实时预览（KaTeX）。 */
import { computed, ref, watch, nextTick } from 'vue'
import renderMathInElement from 'katex/contrib/auto-render'
import { api } from '../api'
import { store, activeItem, scheduleRun, runItem, exportItemHtml } from '../store'
import { ElMessage } from 'element-plus'

const item = computed(() => activeItem())

const groups = computed(() => {
  if (!store.schema) return []
  const order = []
  const map = {}
  for (const p of store.schema.params) {
    const g = p.group || '参数'
    if (!map[g]) { map[g] = []; order.push(g) }
    map[g].push(p)
  }
  return order.map(g => ({ name: g, params: map[g] }))
})

const openGroups = ref([])
watch(groups, g => { openGroups.value = g.map(x => x.name) }, { immediate: true })

const result = computed(() => store.results[item.value?.id] ?? null)
const running = computed(() => item.value && store.runningIds.has(item.value.id))

// ---- 预览渲染：md → HTML → KaTeX ----
const previewHtml = ref('')
const previewEl = ref(null)

watch(() => result.value?.md, async (md) => {
  if (!md) { previewHtml.value = ''; return }
  try {
    previewHtml.value = (await api.render(md)).html
  } catch { previewHtml.value = '' }
  await nextTick()
  if (previewEl.value) {
    renderMathInElement(previewEl.value, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false },
      ],
    })
  }
}, { immediate: true })

function onChanged() {
  scheduleRun(item.value.id)
}

async function onExport() {
  try {
    await exportItemHtml(item.value.id)
    ElMessage.success('已导出 HTML')
  } catch (e) { ElMessage.error(e.message) }
}

function controlType(p) {
  if (p.choices) return 'select'
  if (p.type === 'float' || p.type === 'int') return 'number'
  if (p.type === 'bool') return 'switch'
  return 'text'
}
</script>

<template>
  <div v-if="item" class="single">
    <div class="pane form-pane">
      <div class="pane-head">
        <el-input v-model="item.name" class="item-name" placeholder="计算项名称" />
        <el-tag v-if="running" size="small" type="info">计算中…</el-tag>
        <el-button size="small" @click="runItem(item.id)">重算</el-button>
        <el-button size="small" type="primary" plain @click="onExport">导出 HTML</el-button>
      </div>

      <el-collapse v-model="openGroups">
        <el-collapse-item v-for="g in groups" :key="g.name" :name="g.name">
          <template #title><b>{{ g.name }}</b></template>
          <div v-for="p in g.params" :key="p.name" class="field">
            <div class="field-label">
              {{ p.label || p.name }}
              <span v-if="p.unit" class="unit">（{{ p.unit }}）</span>
            </div>
            <el-select v-if="controlType(p) === 'select'"
                       v-model="item.params[p.name]" @change="onChanged">
              <el-option v-for="c in p.choices" :key="c" :value="c" :label="c" />
            </el-select>
            <el-input-number v-else-if="controlType(p) === 'number'"
                             v-model="item.params[p.name]" :controls="false"
                             class="num" @change="onChanged" />
            <el-switch v-else-if="controlType(p) === 'switch'"
                       v-model="item.params[p.name]" @change="onChanged" />
            <el-input v-else v-model="item.params[p.name]" @change="onChanged" />
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <div class="pane preview-pane">
      <el-alert v-if="result && !result.ok" type="error" :closable="false">
        <template #title>{{ result.error_title || '计算失败' }}</template>
        <pre class="err-pre">{{ result.error }}</pre>
      </el-alert>
      <div v-show="result?.ok" ref="previewEl" class="md-body" v-html="previewHtml" />
      <el-empty v-if="!result" description="尚无结果，修改参数即自动计算" />
    </div>
  </div>
</template>

<style scoped>
.single { display: flex; gap: 12px; height: 100%; }
.pane { flex: 1; overflow: auto; border: 1px solid #e4e7ed; border-radius: 6px; padding: 12px; }
.pane-head { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
.item-name { width: 200px; }
.field { margin-bottom: 12px; }
.field-label { font-size: 13px; color: #606266; margin-bottom: 4px; }
.unit { color: #909399; font-size: 12px; }
.num { width: 100%; }
.err-pre { max-height: 300px; overflow: auto; font-size: 12px; line-height: 1.5;
           margin: 6px 0 0; white-space: pre-wrap; }
.md-body :deep(blockquote) { margin: 4px 0; padding: 2px 12px; color: #555;
  border-left: 3px solid #bbb; font-size: 13px; }
.md-body :deep(table) { border-collapse: collapse; margin: 10px 0; width: 100%; }
.md-body :deep(th), .md-body :deep(td) { border: 1px solid #999; padding: 4px 10px; }
.md-body :deep(th) { background: #f2f2f2; }
.md-body :deep(.katex-display) { margin: 10px 0; }
</style>
