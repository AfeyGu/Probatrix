<script setup>
/** 批量视图：一行一个构件；列显隐、统一设置、Excel 粘贴、行内应力比/结论。 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { store, itemsOf, visibleParams, hiddenCols, toggleCol, scheduleRun,
         runAll, addItem, copyItem, deleteItem, applyToAll, exportItemHtml } from '../store'

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
function openUni() {
  const first = items.value[0]
  uni.value = first ? { ...first.params } : {}
  uniVisible.value = true
}
function applyUni() {
  applyToAll(templateId.value, { ...uni.value })
  uniVisible.value = false
  ElMessage.success('已应用到全部行')
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
    let item = items.value[i]
    if (!item) {
      const cells = line.split('\t')
      const seed = {}
      params.forEach((name, j) => { if (cells[j] !== undefined) seed[name] = cells[j] })
      addItem(templateId.value).then(created => {
        params.forEach((name, j) => {
          if (cells[j] !== undefined) created.params[name] = coerce(cells[j], cols.value[j])
        })
        scheduleRun(created.id)
      })
      appended++
      return
    }
    line.split('\t').forEach((cell, j) => {
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
              class="grid" :class="{ dropping: false }">
      <el-table-column label="名称" width="150">
        <template #default="{ row }">
          <el-input v-model="row.name" size="small" />
        </template>
      </el-table-column>

      <el-table-column v-for="p in cols" :key="p.name" :min-width="p.choices ? 130 : 110">
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

      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="copyItem(row.id)">复制</el-button>
          <el-button size="small" text type="primary" @click="onExportRow(row)">导出</el-button>
          <el-button size="small" text type="danger" @click="deleteItem(row.id)">删</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="uniVisible" title="统一设置（应用到全部行）" width="480">
      <div v-for="p in store.schema?.params || []" :key="p.name" class="field">
        <div class="field-label">
          {{ p.label || p.name }}<span v-if="p.unit" class="unit">（{{ p.unit }}）</span>
        </div>
        <el-select v-if="cellType(p) === 'select'" v-model="uni[p.name]">
          <el-option v-for="c in p.choices" :key="c" :value="c" :label="c" />
        </el-select>
        <el-input-number v-else-if="cellType(p) === 'number'" v-model="uni[p.name]"
                         :controls="false" class="num" />
        <el-switch v-else-if="cellType(p) === 'switch'" v-model="uni[p.name]" />
        <el-input v-else v-model="uni[p.name]" />
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
.summary { color: #606266; font-size: 13px; }
.bad { color: #f56c6c; }
.hint { color: #909399; font-size: 12px; }
.unit { color: #909399; font-size: 11px; margin-left: 4px; font-weight: 400; }
.grid { flex: 1; }
.grid :deep(.el-input__inner), .grid :deep(.el-input-number__decreasing),
.grid :deep(.el-input-number__increasing) { text-align: left; }
.num { width: 100%; }
.ok { color: #67c23a; }
.over { color: #f56c6c; }
.col-row { margin-bottom: 4px; }
.tip-pre { max-height: 220px; overflow: auto; font-size: 11px; }
</style>
