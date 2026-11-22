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

  /** 导出偏好：离线版内嵌 KaTeX（~0.7 MB/文件，断网可看）；界面主题（浅色多套） */
  pref: {
    offlineExport: localStorage.getItem('calcbook.offline') === '1',
    theme: localStorage.getItem('calcbook.theme') || 'notion',
  },
})

export function setOfflineExport(v) {
  store.pref.offlineExport = v
  localStorage.setItem('calcbook.offline', v ? '1' : '0')
}

/** 主题切换 = 换一组 --cb-* 变量值（见 App.vue 的 data-theme 块） */
export function setTheme(t) {
  store.pref.theme = t
  localStorage.setItem('calcbook.theme', t)
  applyTheme(t)
}

function applyTheme(t) {
  document.documentElement.dataset.theme = t
}
applyTheme(store.pref.theme)

let templateSelection = null
const runDebounced = {}
const syncNow = () => api.putProject(currentDoc()).catch(() => {})
const syncDebounced = debounce(syncNow, 800)      // 工程变更自动回写服务端，刷新不丢

// ---------------------------------------------------------------- 基础
export async function init() {
  await loadTemplates()
  await pullProject()                             // 恢复服务端持有的工程
  await restoreFileHandle()                       // 恢复上次保存位置（可原地覆写）
  const first = store.project.items[0]
  // 只有恢复出计算项才选中其模板；空白启动不默认建项，
  // 界面停留在「选择模板后开始计算」空态，由用户自选模板
  if (first?.template_id) await selectTemplate(first.template_id)
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
  const project = store.project
  store.currentTemplateId = templateId
  if (store.schema?.template_id !== templateId) store.schema = null
  const selection = { templateId, schema: api.schema(templateId) }
  templateSelection = selection
  try {
    const schema = await selection.schema
    if (templateSelection !== selection) return false
    store.schema = schema
    if (store.project !== project) return false

    const items = itemsOf(templateId)
    if (!items.length) {
      // 新模板的默认项由 addItem 设为当前项。
      await addItem(templateId)
    } else {
      // 刷新或切换后补算无缓存结果的项，供预览和导出使用。
      for (const item of items) if (!store.results[item.id]) scheduleRun(item.id)
      if (store.viewMode === 'single' && !items.some(i => i.id === store.activeItemId)) {
        store.activeItemId = items[0].id
      }
    }
    return templateSelection === selection && store.project === project
  } catch (error) {
    if (templateSelection !== selection || store.project !== project) return false
    throw error
  } finally {
    if (templateSelection === selection) templateSelection = null
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
  const project = store.project
  const selection = templateSelection
  let schema = store.schema
  if (schema?.template_id !== templateId) {
    // 切换期间的加项和模板切换共用同一次参数请求。
    schema = await (selection?.templateId === templateId ? selection.schema : api.schema(templateId))
  }
  if (store.project !== project) return null

  const count = itemsOf(templateId).length + 1
  const params = {}
  for (const p of schema.params) params[p.name] = p.default
  const item = {
    id: crypto.randomUUID().replace(/-/g, '').slice(0, 12),
    name: defaultItemName(templateId, count),
    template_id: templateId,
    template_hash: schema.hash,
    params,
  }
  project.items.push(item)
  if (store.currentTemplateId === templateId) {
    if (!store.schema && !templateSelection) store.schema = schema
    store.activeItemId = item.id
  }
  scheduleRun(item.id)
  syncDebounced()
  // 必须返回数组里的 reactive 代理：给原始对象赋值会绕过代理、不触发重渲染
  return project.items[project.items.length - 1]
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

// 去掉 vue 响应式代理，保证 JSON 干净。
// deps（依赖模块 hash，旧工程可能已带）是工程文件契约里要保留的数据，投影不许剥。
function toRawItem(item) {
  return JSON.parse(JSON.stringify({
    id: item.id, name: item.name, template_id: item.template_id,
    template_hash: item.template_hash, params: item.params,
    deps: item.deps ?? {},
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

/** 上移/下移：与同模板相邻的计算项交换位置（dir: -1 上移 / 1 下移） */
export function moveItem(templateId, id, dir) {
  const items = store.project.items
  const idx = items.findIndex(i => i.id === id)
  if (idx < 0) return
  let j = idx
  if (dir < 0) {
    for (let k = idx - 1; k >= 0; k--)
      if (items[k].template_id === templateId) { j = k; break }
  } else {
    for (let k = idx + 1; k < items.length; k++)
      if (items[k].template_id === templateId) { j = k; break }
  }
  if (j === idx) return                       // 已在顶部/底部
  const [it] = items.splice(idx, 1)
  items.splice(j, 0, it)
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
  const saved = store.project.views[templateId]?.hidden_cols
  if (saved) return saved
  // 未保存过列配置：用声明里的默认隐藏标记（batch_hidden，或带 show_if 的条件参数）
  return (store.schema?.params ?? []).filter(p => p.batch_hidden || p.show_if).map(p => p.name)
}

export function toggleCol(templateId, name, visible) {
  const views = store.project.views
  // 首次勾选时以当前生效集合初始化（含 batch_hidden 默认隐藏项），此后为绝对集合
  const view = (views[templateId] ??= { hidden_cols: hiddenCols(templateId).slice() })
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

function projectFileDoc() {
  // 版本与 src/calcbook/project.py 的 FORMAT_VERSION 同步。
  return { format_version: 1, ...currentDoc() }
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

// ---------------- 工程文件：File System Access API 原地保存 ----------------
// 首次保存弹原生「另存为」，之后每次保存直接覆写同一文件，像本地软件；
// 句柄存 IndexedDB，刷新页面后仍记得上次存哪。不支持的浏览器回退下载。
export const fsPickSupported = typeof window !== 'undefined' && 'showSaveFilePicker' in window

let fileHandle = null

function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('calcbook', 1)
    req.onupgradeneeded = () => req.result.createObjectStore('kv')
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function idbSet(key, val) {
  const db = await idb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction('kv', 'readwrite')
    tx.objectStore('kv').put(val, key)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

async function idbGet(key) {
  const db = await idb()
  return new Promise((resolve, reject) => {
    const req = db.transaction('kv', 'readonly').objectStore('kv').get(key)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function ensurePermission(handle) {
  if ((await handle.queryPermission({ mode: 'readwrite' })) === 'granted') return true
  return (await handle.requestPermission({ mode: 'readwrite' })) === 'granted'
}

async function writeProjectTo(handle) {
  const writable = await handle.createWritable()
  await writable.write(JSON.stringify(projectFileDoc(), null, 2))
  await writable.close()
}

async function restoreFileHandle() {
  if (!fsPickSupported) return
  try { fileHandle = (await idbGet('cbproj-handle')) || null } catch { fileHandle = null }
}

/** 保存工程：有句柄则原地覆写；无句柄弹原生另存为。返回文件名，回退下载返回 null。 */
export async function saveProjectAs() {
  if (!fsPickSupported) {
    downloadFile(`${store.project.name || '工程'}.cbproj`, JSON.stringify(projectFileDoc(), null, 2))
    return null
  }
  if (fileHandle) {
    if (!(await ensurePermission(fileHandle))) throw new Error('未获得文件写入权限')
    await writeProjectTo(fileHandle)
    return fileHandle.name
  }
  fileHandle = await window.showSaveFilePicker({
    suggestedName: `${store.project.name || '工程'}.cbproj`,
    types: [{ description: 'CalcBook 工程', accept: { 'application/json': ['.cbproj', '.json'] } }],
  })
  await writeProjectTo(fileHandle)
  await idbSet('cbproj-handle', fileHandle)
  return fileHandle.name
}

/** 打开工程：file 为 File（input 回退）或 FileSystemFileHandle（picker，可原地保存） */
export async function openProjectFile(file) {
  const handle = file?.getFile ? file : null
  const blob = handle ? await handle.getFile() : file
  const doc = JSON.parse(await blob.text())       // 解析失败让上层提示
  await putProject(doc)
  if (handle) {
    fileHandle = handle
    await idbSet('cbproj-handle', handle)
  }
  const first = store.project.items[0]
  if (first) {
    if (await selectTemplate(first.template_id)) store.activeItemId = first.id
  }
}

/** 新建空白工程：脱离当前文件，下次保存会弹另存为 */
export async function newBlankProject() {
  store.project = { name: '未命名工程', items: [], views: {} }
  store.results = {}
  store.staleIds = new Set()
  store.activeItemId = null
  fileHandle = null
  if (fsPickSupported) { try { await idbSet('cbproj-handle', null) } catch { /* 忽略 */ } }
  syncNow()
}

// ---------------------------------------------------------------- 导出
function metaFields() {
  return {
    工程名称: store.project.name,
    导出日期: new Date().toISOString().slice(0, 10),
  }
}

const escHtml = (s) => s.replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

async function htmlOf(html, title) {
  const { html: page } = await api.exportHtml(html, title, metaFields(), store.pref.offlineExport)
  return page
}

export async function exportItemHtml(itemId) {
  const r = store.results[itemId]
  if (!r?.ok) throw new Error('该计算项还没有成功计算结果，先让它算完')
  const item = store.project.items.find(i => i.id === itemId)
  const page = await htmlOf(r.html, item.name)
  downloadFile(`${item.name}.html`, page, 'text/html')
}

/** 导出整个工程：各计算项按顺序合并，计算项之间分页。 */
export async function exportProjectHtml() {
  const parts = []
  for (const item of store.project.items) {
    const r = store.results[item.id]
    if (!r?.ok) continue
    parts.push(`<h1>${escHtml(item.name)}</h1>\n${r.html}`)
  }
  if (!parts.length) throw new Error('没有可导出的计算结果，先完成计算')
  const page = await htmlOf(parts.join('\n<div class="page-break"></div>\n'),
    store.project.name)
  downloadFile(`${store.project.name || '工程'}.html`, page, 'text/html')
}

/** 导出 Markdown：计算原文（md+LaTeX），无需转换、直接下载 */
export async function exportItemMd(itemId) {
  const r = store.results[itemId]
  if (!r?.ok) throw new Error('该计算项还没有成功计算结果，先让它算完')
  const item = store.project.items.find(i => i.id === itemId)
  downloadFile(`${item.name}.md`, r.md, 'text/markdown')
}

export async function exportProjectMd() {
  const parts = []
  for (const item of store.project.items) {
    const r = store.results[item.id]
    if (!r?.ok) continue
    parts.push(r.md)                       // 每项首行已有 # 计算书标题
  }
  if (!parts.length) throw new Error('没有可导出的计算结果，先完成计算')
  downloadFile(`${store.project.name || '工程'}.md`,
    parts.join('\n\n<!-- pagebreak -->\n\n'), 'text/markdown')
}
