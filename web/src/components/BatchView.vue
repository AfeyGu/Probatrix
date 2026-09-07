<script setup>
/** 批量视图：一行一个构件；列显隐、统一设置、Excel 粘贴、行内应力比/结论。 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { store, itemsOf, visibleParams, hiddenCols, toggleCol, scheduleRun,
         runAll, addItem, copyItem, deleteItem, moveItem, applyToAll, exportItemHtml } from '../store'

const templateId = computed(() => store.currentTemplateId)
const items = computed(() => itemsOf(templateId.value))
const cols = computed(() => visibleParams(templateId.value))

const runningAny = computed(() => items.value.some(i => store.runningIds.has(i.id)))
const summary = computed(() => {
  const rs = items.value.map(i => store.results[i.id]).filter(r => r?.ok)
  const bad = rs.filter(r => r.all_ok === false).length
  return { total: items.value.length, done: rs.length, bad }
})

// ---- 统一设置（scratch 表单 → 应用到全部）----
const uniVisible = ref(false)
const uni = ref({})
const mixedNames = ref([])        // 各行取值不一致的参数名
function openUni() {
  const items = itemsOf(templateId.value)
  if (!items.length) { ElMessage.info('先加一行再统一设置'); return }
  const val = {}
  const mixed = []
  for (const p of store.schema?.params || []) {
    const first = items[0].params[p.name]
    const same = items.every(i => i.params[p.name] === first)
    // 取值不一致时预置空：number 用 null，其余用 ''，应用时跳过
    val[p.name] = same ? first : (cellType(p) === 'number' ? null : '')
    if (!same) mixed.push(p.name)
  }
  uni.value = val
  mixedNames.value = mixed
  uniVisible.value = true
}
function isMixed(p) { return mixedNames.value.includes(p.name) }
function applyUni() {
  // 只统一「本来就一致」的字段和「用户填/选了值」的字段；
  // 混合且留空的字段保持各行原值（避免用第一行的值悄悄覆盖其他行）
  const patch = {}
  for (const p of store.schema?.params || []) {
    const v = uni.value[p.name]
    if (isMixed(p) && (v === '' || v == null)) continue
    patch[p.name] = v
  }
  applyToAll(templateId.value, patch)
  uniVisible.value = false
  ElMessage.success(`已统一 ${Object.keys(patch).length} 项参数`)
}

// ---- 列显隐 ----
const colVisible = ref(false)

function cellType(p) {
  if (p.choices) return 'select'
  if (p.type === 'float' || p.type === 'int') return 'number'
  if (p.type === 'bool') return 'switch'
  return 'text'
}

// ---- Excel 粘贴：TSV → 可见参数列，行数不够自动补行 ----
function onPaste(e) {
  const text = e.clipboardData?.getData('text/plain')
  if (!text) return
  const lines = text.trim().split(/\r?\n/).filter(l => l)
  if (!lines.length) return
  e.preventDefault()

  const params = cols.value.map(p => p.name)
  const coerce = (v, p) => {
    if (cellType(p) === 'number') { const n = Number(v); return Number.isNaN(n) ? v : n }
    return v.trim()
  }
  let appended = 0
  lines.forEach((line, i) => {
    const cells = line.split('\t')
    let item = items.value[i]
    if (!item) {
      addItem(templateId.value).then(created => {
        params.forEach((name, j) => {
          if (cells[j] !== undefined) created.params[name] = coerce(cells[j], cols.value[j])
        })
        scheduleRun(created.id)
      })
      appended++
      return
    }
    cells.forEach((cell, j) => {
      if (j < params.length && cols.value[j]) {
        item.params[params[j]] = coerce(cell, cols.value[j])
      }
    })
    scheduleRun(item.id)
  })
  ElMessage.success(`粘贴 ${lines.length} 行${appended ? `（新增 ${appended} 行）` : ''}，开始重算`)
}

function ratioText(r) {
  if (!r?.ok) return null
  return r.max_ratio == null ? null : r.max_ratio.toFixed(2)
}

// ---- 结果指标列（模板经 b.metric() 输出，如 A端支座配筋）----
// 取当前模板所有行结果中出现过指标名的并集，按首次出现顺序排列
const metricKeys = computed(() => {
  const keys = []
  for (const it of items.value) {
    const m = store.results[it.id]?.metrics
    if (!m) continue
    for (const k of Object.keys(m)) if (!keys.includes(k)) keys.push(k)
  }
  return keys
})
function metricMinW(k) {
  let w = 0
  for (const ch of k) w += ch.charCodeAt(0) > 255 ? 14 : 7
  return Math.max(88, Math.ceil(w) + 24)
}

// 列最小宽度 = 表头文字单行宽度（拖动不可低于此值，保证单行显示）
function colMinW(p) {
  const text = (p.label || p.name) + (p.unit || '')
  let w = 0
  for (const ch of text) w += ch.charCodeAt(0) > 255 ? 14 : 7
  return Math.max(88, Math.ceil(w) + (p.choices ? 44 : 30))   // 选择框留箭头位
}

function canMove(row, dir) {
  const list = items.value
  const idx = list.findIndex(i => i.id === row.id)
  if (idx < 0) return false
  return dir < 0 ? idx > 0 : idx < list.length - 1
}

async function onExportRow(row) {
  try {
    await exportItemHtml(row.id)
    ElMessage.success(`已导出 ${row.name}`)
  } catch (e) { ElMessage.error(e.message) }
}
</script>

<template>
  <div class="batch" @paste="onPaste">
    <div class="toolbar">
      <el-button type="primary" plain @click="addItem(templateId)">＋ 加一行</el-button>
      <el-button :loading="runningAny" @click="runAll(templateId)">全部重算</el-button>
      <el-button @click="openUni">统一设置</el-button>
      <el-popover v-model:visible="colVisible" width="260" trigger="click">
        <template #reference>
          <el-button>列显隐</el-button>
        </template>
        <div v-for="p in store.schema?.params || []" :key="p.name" class="col-row">
          <el-checkbox
            :model-value="!hiddenCols(templateId).includes(p.name)"
            @change="v => toggleCol(templateId, p.name, v)">
            {{ p.label || p.name }}<span v-if="p.unit" class="unit">（{{ p.unit }}）</span>
          </el-checkbox>
        </div>
      </el-popover>
      <span class="summary">
        共 {{ summary.total }} 行
        <template v-if="summary.done">，已算 {{ summary.done }}</template>
        <template v-if="summary.bad">，<b class="bad">{{ summary.bad }} 行不满足</b></template>
      </span>
      <span class="hint">支持从 Excel 直接 Ctrl+V 粘贴（按当前可见列对齐，行数不够自动补行）</span>
    </div>

    <el-table :data="items" row-key="id" size="small" border
              class="grid">
      <el-table-column label="名称" width="150" fixed="left">
        <template #default="{ row }">
          <el-input v-model="row.name" size="small" />
        </template>
      </el-table-column>

      <el-table-column v-for="p in cols" :key="p.name" :min-width="colMinW(p)">
        <template #header>
          {{ p.label || p.name }}<span v-if="p.unit" class="unit">{{ p.unit }}</span>
        </template>
        <template #default="{ row }">
          <el-select v-if="cellType(p) === 'select'" v-model="row.params[p.name]"
                     size="small" @change="scheduleRun(row.id)">
            <el-option v-for="c in p.choices" :key="c" :value="c" :label="c" />
          </el-select>
          <el-input-number v-else-if="cellType(p) === 'number'" v-model="row.params[p.name]"
                           size="small" :controls="false" class="num"
                           @change="scheduleRun(row.id)" />
          <el-switch v-else-if="cellType(p) === 'switch'" v-model="row.params[p.name]"
                     size="small" @change="scheduleRun(row.id)" />
          <el-input v-else v-model="row.params[p.name]" size="small"
                    @change="scheduleRun(row.id)" />
        </template>
      </el-table-column>

      <el-table-column label="应力比" width="90">
        <template #default="{ row }">
          <span v-if="store.runningIds.has(row.id)">…</span>
          <b v-else-if="ratioText(store.results[row.id]) != null"
             :class="store.results[row.id].all_ok ? 'ok' : 'over'">
            {{ ratioText(store.results[row.id]) }}
          </b>
        </template>
      </el-table-column>

      <el-table-column label="结论" width="90">
        <template #default="{ row }">
          <el-tag v-if="store.results[row.id]?.ok" size="small"
                  :type="store.results[row.id].all_ok ? 'success' : 'danger'">
            {{ store.results[row.id].all_ok ? '满足' : '不满足' }}
          </el-tag>
          <el-tooltip v-else-if="store.results[row.id]" placement="top">
            <template #content>
              <pre class="tip-pre">{{ store.results[row.id].error_title }}&#10;{{ store.results[row.id].error }}</pre>
            </template>
            <el-tag size="small" type="warning">出错</el-tag>
          </el-tooltip>
        </template>
      </el-table-column>

      <el-table-column v-for="k in metricKeys" :key="k" :min-width="metricMinW(k)">
        <template #header>{{ k }}</template>
        <template #default="{ row }">
          <span class="metric-cell">{{ store.results[row.id]?.metrics?.[k] ?? '' }}</span>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="174" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" title="上移"
                     :disabled="!canMove(row, -1)"
                     @click="moveItem(templateId, row.id, -1)">↑</el-button>
          <el-button size="small" text type="primary" title="下移"
                     :disabled="!canMove(row, 1)"
                     @click="moveItem(templateId, row.id, 1)">↓</el-button>
          <el-button size="small" text type="primary" @click="copyItem(row.id)">复制</el-button>
          <el-button size="small" text type="primary" @click="onExportRow(row)">导出</el-button>
          <el-button size="small" text type="danger" @click="deleteItem(row.id)">删</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="uniVisible" title="统一设置（应用到全部行）" width="480">
      <div v-if="mixedNames.length" class="uni-hint">
        标 <span class="mixed-mark">＊</span> 的参数各行取值不同：留空则保持各行原值，填入/选择后应用即统一该列。
      </div>
      <div v-for="p in store.schema?.params || []" :key="p.name" class="field">
        <div class="field-label">
          {{ p.label || p.name }}<span v-if="isMixed(p)" class="mixed-mark">＊</span><span v-if="p.unit" class="unit">（{{ p.unit }}）</span>
        </div>
        <el-select v-if="cellType(p) === 'select'" v-model="uni[p.name]">
          <el-option v-if="isMixed(p)" value="" label="（各行不同，保持不变）" />
          <el-option v-for="c in p.choices" :key="c" :value="c" :label="c" />
        </el-select>
        <el-input-number v-else-if="cellType(p) === 'number'" v-model="uni[p.name]"
                         :controls="false" class="num"
                         :placeholder="isMixed(p) ? '各行不同，留空保持原值' : ''" />
        <el-select v-else-if="cellType(p) === 'switch' && isMixed(p)" v-model="uni[p.name]">
          <el-option value="" label="（各行不同，保持不变）" />
          <el-option :value="true" label="开" />
          <el-option :value="false" label="关" />
        </el-select>
        <el-switch v-else-if="cellType(p) === 'switch'" v-model="uni[p.name]" />
        <el-input v-else v-model="uni[p.name]"
                  :placeholder="isMixed(p) ? '各行不同，留空保持原值' : ''" />
      </div>
      <template #footer>
        <el-button @click="uniVisible = false">取消</el-button>
        <el-button type="primary" @click="applyUni">应用到全部</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.batch { height: 100%; display: flex; flex-direction: column; }
.toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.summary { color: var(--cb-text-2); font-size: 13px; }
.bad { color: var(--cb-bad); }
.hint { color: var(--cb-text-3); font-size: 12px; }
.unit { color: var(--cb-text-3); font-size: 11px; margin-left: 4px; font-weight: 400; }
.grid { flex: 1; }
/* 表格直接落在画布上：圆角融掉自身边框，不套卡片 */
.grid { border-radius: 8px; }
.grid :deep(.el-table__inner-wrapper::before) { border-radius: 8px; }
/* 单元格/表头单行显示，不换行（配合 min-width 拖动下限） */
.grid :deep(.el-table__cell .cell) { white-space: nowrap; }
/* 操作列按钮收紧，保证完整显示 */
.grid :deep(td:last-child .el-button) { padding: 5px 6px; }
.grid :deep(td:last-child .el-button + .el-button) { margin-left: 4px; }
/* 列多时横向滚动条常显（el-scrollbar 默认 hover 才出现，容易被认为不能滚） */
.grid :deep(.el-scrollbar__bar.is-horizontal) { display: block !important; opacity: 1; height: 10px; }
.grid :deep(.el-input__inner), .grid :deep(.el-input-number__decreasing),
.grid :deep(.el-input-number__increasing) { text-align: left; }
/* 结果指标列：纯文本，随全局单行规则即可，稍微收紧字号 */
.metric-cell { font-size: 13px; }
.num { width: 100%; }
.ok { color: var(--cb-ok); }
.over { color: var(--cb-bad); }
.col-row { margin-bottom: 4px; }
.tip-pre { max-height: 220px; overflow: auto; font-size: 11px; }
.uni-hint { font-size: 12px; color: var(--cb-text-3); line-height: 1.6;
            margin-bottom: 12px; padding: 8px 10px;
            background: var(--cb-surface); border: 1px solid var(--cb-border); border-radius: 6px; }
.mixed-mark { color: var(--cb-warn); font-weight: 600; }
</style>
