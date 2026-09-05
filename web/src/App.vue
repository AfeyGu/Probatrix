<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { store, refreshTemplates, selectTemplate, setView, addItem,
         saveProjectAs, openProjectFile, exportProjectHtml,
         newBlankProject, touch, setOfflineExport } from './store'
import SingleView from './components/SingleView.vue'
import BatchView from './components/BatchView.vue'

const fileInput = ref(null)

const groupedItems = computed(() => {
  const groups = []
  for (const t of store.templates) {
    const items = store.project.items.filter(i => i.template_id === t.template_id)
    if (items.length) groups.push({ id: t.template_id, name: t.name, items })
  }
  // 工程里可能有模板已卸载的计算项
  const known = new Set(store.templates.map(t => t.template_id))
  const orphans = store.project.items.filter(i => !known.has(i.template_id))
  if (orphans.length) groups.push({ id: '?', name: '（模板未加载）', items: orphans })
  return groups
})

const hasLoaderErrors = () => store.loaderErrors.length > 0

async function onOpenFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (!file) return
  try {
    await openProjectFile(file)
    ElMessage.success(`已打开：${store.project.name}`)
  } catch (e) {
    ElMessage.error(`打开失败：${e.message}`)
  }
}

async function onNewProject() {
  await ElMessageBox.confirm('新建工程将清空当前内容，继续？', '新建工程', { type: 'warning' })
  await newBlankProject()
}

async function onExportProject() {
  try {
    await exportProjectHtml()
    ElMessage.success('已导出 HTML')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function onPickItem(group, item) {
  if (group.id !== '?') await selectTemplate(group.id)
  store.activeItemId = item.id
  setView('single')
}

function ratioOf(item) {
  return store.results[item.id]?.max_ratio
}
</script>

<template>
  <el-container class="root">
    <el-header height="52px" class="header">
      <span class="brand">CalcBook 计算书工具</span>
      <el-input v-model="store.project.name" class="proj-name" placeholder="工程名"
                @change="touch" />
      <el-button @click="onNewProject">新建</el-button>
      <input ref="fileInput" type="file" accept=".cbproj,.json" hidden @change="onOpenFile" />
      <el-button @click="fileInput?.click()">打开</el-button>
      <el-button type="primary" plain @click="saveProjectAs()">保存工程</el-button>
      <el-divider direction="vertical" />
      <el-select v-model="store.currentTemplateId" class="tpl-select"
                 placeholder="选择模板" @change="selectTemplate">
        <el-option v-for="t in store.templates" :key="t.template_id"
                   :value="t.template_id" :label="t.name" />
      </el-select>
      <el-button @click="refreshTemplates().then(() => ElMessage.success('模板已刷新'))">
        刷新模板
      </el-button>
      <el-divider direction="vertical" />
      <el-radio-group v-model="store.viewMode" @change="setView">
        <el-radio-button value="single">单项</el-radio-button>
        <el-radio-button value="batch">批量</el-radio-button>
      </el-radio-group>
      <el-divider direction="vertical" />
      <el-tooltip content="勾选后导出文件内嵌公式字体（约 0.7 MB），断网也能正常显示；不勾选则文件小、需联网渲染公式"
                 placement="bottom">
        <el-checkbox v-model="store.pref.offlineExport" @change="setOfflineExport($event)">
          导出离线版
        </el-checkbox>
      </el-tooltip>
      <el-button type="primary" plain @click="onExportProject">导出工程 HTML</el-button>
    </el-header>

    <el-container class="body">
      <el-aside width="270px" class="aside">
        <el-alert v-if="hasLoaderErrors()" type="error" :closable="false" class="loader-err">
          <template #title>
            模板加载错误（{{ store.loaderErrors.length }} 个文件）
          </template>
          <pre class="err-pre">{{ store.loaderErrors.map(e => e.file + '\n' + e.error).join('\n\n') }}</pre>
        </el-alert>

        <div class="aside-head">
          <span>计算项</span>
          <el-button size="small" type="primary" plain
                     :disabled="!store.currentTemplateId"
                     @click="addItem(store.currentTemplateId)">
            ＋ 加一项
          </el-button>
        </div>

        <div v-for="g in groupedItems" :key="g.id" class="group">
          <div class="group-title">{{ g.name }}</div>
          <div v-for="item in g.items" :key="item.id"
               class="item-row" :class="{ active: item.id === store.activeItemId }"
               @click="onPickItem(g, item)">
            <span class="item-name">{{ item.name }}</span>
            <el-tooltip v-if="store.staleIds.has(item.id)" content="模板已修改，结果可能过期（点开重算）">
              <el-tag size="small" type="warning">模板已改</el-tag>
            </el-tooltip>
            <el-tag v-if="ratioOf(item) != null" size="small"
                    :type="store.results[item.id].all_ok ? 'success' : 'danger'">
              {{ ratioOf(item).toFixed(2) }}
            </el-tag>
            <el-icon v-if="store.runningIds.has(item.id)" class="is-loading spin">◌</el-icon>
          </div>
        </div>
        <div v-if="!store.project.items.length" class="empty-hint">
          还没有计算项：选择模板后点「＋加一项」
        </div>
      </el-aside>

      <el-main class="main">
        <SingleView v-if="store.viewMode === 'single' && store.activeItemId" />
        <BatchView v-else-if="store.viewMode === 'batch' && store.currentTemplateId" />
        <el-empty v-else description="选择模板后开始计算" />
      </el-main>
    </el-container>
  </el-container>
</template>

<style>
* { box-sizing: border-box; }
html, body, #app { height: 100%; margin: 0; }
.root { height: 100%; }
.header { display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #e4e7ed; }
.brand { font-weight: 600; white-space: nowrap; color: #303133; }
.proj-name { width: 180px; }
.tpl-select { width: 180px; }
.body { height: calc(100% - 52px); }
.aside { border-right: 1px solid #e4e7ed; padding: 10px; overflow: auto; }
.loader-err { margin-bottom: 10px; }
.err-pre { max-height: 200px; overflow: auto; font-size: 11px; line-height: 1.4; margin: 4px 0 0; }
.aside-head { display: flex; justify-content: space-between; align-items: center; margin: 4px 0 8px; }
.group-title { font-size: 12px; color: #909399; margin: 10px 0 4px; }
.item-row { display: flex; align-items: center; gap: 6px; padding: 5px 8px; border-radius: 4px;
            cursor: pointer; font-size: 13px; }
.item-row:hover { background: #f5f7fa; }
.item-row.active { background: #ecf5ff; }
.item-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-hint { color: #909399; font-size: 12px; margin-top: 20px; text-align: center; }
.main { padding: 12px; overflow: auto; }
.spin { animation: rotate 1s linear infinite; }
@keyframes rotate { to { transform: rotate(360deg); } }
</style>
