/** 全局状态：模板、工程（计算项集合）、视图、运行结果。
 *
 * 设计对齐 计算书工具文档.md：
 * - 工程数据模型：items = 多个计算项（完整 params，无隐藏状态）；
 * - 列显隐配置存 views[template_id].hidden_cols；
 * - 自动实时计算：参数变更防抖 300ms，仅手动模板除外；
 * - 统一设置只是「批量赋值操作」，每行参数始终存完整值。
 */
import { reactive } from 'vue'
import { api } from './api'

function debounce(fn, ms) {
  let t = null
  return (...args) => {
    clearTimeout(t)
    t = setTimeout(() => fn(...args), ms)
  }
}

export const store = reactive({
  templates: [],
  loaderErrors: [],
  staleIds: new Set(),           // 模板 hash 已变的计算项 id

  currentTemplateId: '',
  schema: null,                  // {params: [...], name, manual, hash, ...}

  project: { name: '未命名工程', items: [], views: {} },
  activeItemId: null,
  viewMode: 'single',            // 'single' | 'batch'

  results: {},                   // itemId -> RunResult（单项/批量共用）
  runningIds: new Set(),

  /** 导出偏好：离线版内嵌 KaTeX（~0.7 MB/文件，断网可看） */
  pref: {
    offlineExport: localStorage.getItem('calcbook.offline') === '1',
  },
})

export function setOfflineExport(v) {
  store.pref.offlineExport = v
  localStorage.setItem('calcbook.offline', v ? '1' : '0')
}

const runDebounced = {}
const syncNow = () => api.putProject(currentDoc()).catch(() => {})
const syncDebounced = debounce(syncNow, 800)      // 工程变更自动回写服务端，刷新不丢

// ---------------------------------------------------------------- 基础
export async function init() {
  await loadTemplates()
  await pullProject()                             // 恢复服务端持有的工程
  const first = store.project.items[0]
  const target = first?.template_id ?? store.templates[0]?.template_id
  if (target) await selectTemplate(target)
}

async function pullProject() {
  try {
    const doc = await api.getProject()
    if (doc?.items?.length) {
      store.project = { name: doc.name, items: doc.items, views: doc.views ?? {} }
    }
  } catch { /* 服务端不可用时保持本地空工程 */ }
}

export async function loadTemplates() {
  const data = await api.listTemplates()
  store.templates = data.templates
  store.loaderErrors = data.errors
  await refreshStale()
}

export async function refreshTemplates() {
  const data = await api.refreshTemplates()
  store.templates = data.templates
  store.loaderErrors = data.errors
  await refreshStale()
  if (store.currentTemplateId && !store.templates.some(t => t.template_id === store.currentTemplateId)) {
    // 当前模板被删/改名：切到第一个可用的
    if (store.templates.length) await selectTemplate(store.templates[0].template_id)
  } else if (store.currentTemplateId) {
    store.schema = await api.schema(store.currentTemplateId)
  }
}

export async function selectTemplate(templateId) {
  store.currentTemplateId = templateId
  store.schema = await api.schema(templateId)
  const items = itemsOf(templateId)
  if (!items.length) {
    await addItem(templateId)               // 打开模板即给一个默认计算项
  } else {
    // 刷新/切换后没有缓存结果：补算一轮，否则预览空白、导出会报「无结果」
    for (const it of items) if (!store.results[it.id]) scheduleRun(it.id)
  }
  if (store.viewMode === 'single' &&
      (!store.activeItemId || !items.some(i => i.id === store.activeItemId))) {
    store.activeItemId = items[0].id
  }
}

export function setView(mode) {
  store.viewMode = mode
  if (mode === 'single') {
    const items = itemsOf(store.currentTemplateId)
    if (!store.activeItemId || !items.some(i => i.id === store.activeItemId)) {
      store.activeItemId = items[0]?.id ?? null
    }
  }
}

// ---------------------------------------------------------------- 工程项
export function itemsOf(templateId) {
  return store.project.items.filter(i => i.template_id === templateId)
}

export function activeItem() {
  return store.project.items.find(i => i.id === store.activeItemId) ?? null
}

export async function addItem(templateId) {
  if (!store.schema || store.schema.template_id !== templateId) {
    store.schema = await api.schema(templateId)
  }
  const count = itemsOf(templateId).length + 1
  const params = {}
  for (const p of store.schema.params) params[p.name] = p.default
  const item = {
    id: crypto.randomUUID().replace(/-/g, '').slice(0, 12),
    name: defaultItemName(templateId, count),
    template_id: templateId,
    template_hash: store.schema.hash,
    params,
  }
  store.project.items.push(item)
  store.activeItemId = item.id
  scheduleRun(item.id)
  syncDebounced()
  // 必须返回数组里的 reactive 代理：给原始对象赋值会绕过代理、不触发重渲染
  return store.project.items[store.project.items.length - 1]
}

function defaultItemName(templateId, count) {
  const stem = templateId.split('.')[0].toUpperCase()
  return `${stem}-${count}`
}

export function copyItem(id) {
  const idx = store.project.items.findIndex(i => i.id === id)
  if (idx < 0) return
  const src = store.project.items[idx]
  const copy = {
    ...structuredClone(toRawItem(src)),
    id: crypto.randomUUID().replace(/-/g, '').slice(0, 12),
    name: src.name + '-副本',
  }
  store.project.items.splice(idx + 1, 0, copy)
  store.activeItemId = copy.id
  scheduleRun(copy.id)
  syncDebounced()
  return store.project.items[idx + 1]          // 同上：返回代理
}

// 去掉 vue 响应式代理，保证 JSON 干净
function toRawItem(item) {
  return JSON.parse(JSON.stringify({
    id: item.id, name: item.name, template_id: item.template_id,
    template_hash: item.template_hash, params: item.params,
  }))
}

export function deleteItem(id) {
  const idx = store.project.items.findIndex(i => i.id === id)
  if (idx < 0) return
  store.project.items.splice(idx, 1)
  delete store.results[id]
  syncDebounced()
  if (store.activeItemId === id) {
    store.activeItemId = itemsOf(store.currentTemplateId)[0]?.id ?? null
  }
}

/** 改了名字等非参数内容：标记变更并延迟回写 */
export function touch() {
  syncDebounced()
}

// ---------------------------------------------------------------- 运行
export function scheduleRun(itemId) {
  const item = store.project.items.find(i => i.id === itemId)
  if (!item) return
  syncDebounced()                             // 参数编辑也回写，刷新不丢
  const meta = store.templates.find(t => t.template_id === item.template_id)
  if (meta?.manual) return                    // 仅手动模板：不自动跑
  if (!runDebounced[itemId]) {
    runDebounced[itemId] = debounce((id) => runItem(id), 300)
  }
  runDebounced[itemId](itemId)
}

export async function runItem(itemId) {
  const item = store.project.items.find(i => i.id === itemId)
  if (!item) return
  store.runningIds.add(itemId)
  try {
    store.results[itemId] = await api.run(item.template_id, item.params, item.name)
  } catch (e) {
    store.results[itemId] = { ok: false, error_title: '请求失败', error: String(e) }
  } finally {
    store.runningIds.delete(itemId)
  }
}

export async function runAll(templateId) {
  const items = itemsOf(templateId)
  await Promise.all(items.map(i => runItem(i.id)))
}

/** 统一设置：把若干字段值应用到模板的全部行（批量赋值，非存储结构）。 */
export function applyToAll(templateId, fields) {
  for (const item of itemsOf(templateId)) {
    Object.assign(item.params, fields)
    scheduleRun(item.id)
  }
}

// ---------------------------------------------------------------- 列显隐
export function hiddenCols(templateId) {
  return store.project.views[templateId]?.hidden_cols ?? []
}

export function toggleCol(templateId, name, visible) {
  const views = store.project.views
  const view = (views[templateId] ??= { hidden_cols: [] })
  const hidden = new Set(view.hidden_cols)
  visible ? hidden.delete(name) : hidden.add(name)
  view.hidden_cols = [...hidden]
  syncDebounced()
}

export function visibleParams(templateId) {
  if (!store.schema) return []
  const hidden = new Set(hiddenCols(templateId))
  return store.schema.params.filter(p => !hidden.has(p.name))
}

// ---------------------------------------------------------------- hash 校验
export async function refreshStale() {
  try {
    const { items } = await api.hashCheck()
    store.staleIds = new Set(items.filter(i => i.stale).map(i => i.id))
  } catch { /* 工程为空等，忽略 */ }
}

// ---------------------------------------------------------------- 工程 IO
export function currentDoc() {
  return {
    name: store.project.name,
    items: store.project.items.map(toRawItem),
    views: store.project.views,
  }
}

export async function putProject(doc) {
  store.project = await api.putProject(doc)
  await refreshStale()
}

export function downloadFile(filename, content, mime = 'application/json') {
  const blob = new Blob([content], { type: mime })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

export function saveProjectAs() {
  downloadFile(`${store.project.name || '工程'}.cbproj`,
    JSON.stringify(currentDoc(), null, 2))
}

export async function openProjectFile(file) {
  const text = await file.text()
  const doc = JSON.parse(text)                 // 解析失败让上层提示
  await putProject(doc)
  const first = store.project.items[0]
  if (first) {
    await selectTemplate(first.template_id)
    store.activeItemId = first.id
  }
}

/** 新建空白工程 */
export async function newBlankProject() {
  store.project = { name: '未命名工程', items: [], views: {} }
  store.results = {}
  store.staleIds = new Set()
  store.activeItemId = null
  syncNow()
}

// ---------------------------------------------------------------- 导出
function metaFields() {
  return {
    工程名称: store.project.name,
    导出日期: new Date().toISOString().slice(0, 10),
  }
}

async function htmlOf(md, title) {
  const { html } = await api.exportHtml(md, title, metaFields(), store.pref.offlineExport)
  return html
}

export async function exportItemHtml(itemId) {
  const r = store.results[itemId]
  if (!r?.ok) throw new Error('该计算项还没有成功计算结果，先让它算完')
  const item = store.project.items.find(i => i.id === itemId)
  const page = await htmlOf(r.md, item.name)
  downloadFile(`${item.name}.html`, page, 'text/html')
}

/** 导出整个工程：各计算项按顺序合并，计算项之间分页。 */
export async function exportProjectHtml() {
  const parts = []
  for (const item of store.project.items) {
    const r = store.results[item.id]
    if (!r?.ok) continue
    parts.push(`# ${item.name}\n\n${r.md}`)
  }
  if (!parts.length) throw new Error('没有可导出的计算结果，先完成计算')
  const page = await htmlOf(parts.join('\n\n<!-- pagebreak -->\n\n'),
    store.project.name)
  downloadFile(`${store.project.name || '工程'}.html`, page, 'text/html')
}
