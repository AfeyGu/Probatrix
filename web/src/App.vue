<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { store, refreshTemplates, selectTemplate, setView, addItem,
         saveProjectAs, openProjectFile, exportProjectHtml,
         newBlankProject, touch, setOfflineExport, setTheme, fsPickSupported } from './store'
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

/** 打开工程：支持 FS Access 的浏览器用原生打开对话框（拿到可写句柄，保存可原地覆写） */
async function onOpenProject() {
  if (fsPickSupported) {
    try {
      const [handle] = await window.showOpenFilePicker({
        types: [{ description: 'CalcBook 工程', accept: { 'application/json': ['.cbproj', '.json'] } }],
      })
      await openProjectFile(handle)
      ElMessage.success(`已打开：${store.project.name}`)
    } catch (e) {
      if (e.name !== 'AbortError') ElMessage.error(`打开失败：${e.message}`)
    }
  } else {
    fileInput.value?.click()
  }
}

async function onSaveProject() {
  try {
    const name = await saveProjectAs()
    if (name) ElMessage.success(`已保存到 ${name}`)
    else ElMessage.success('工程文件已下载')
  } catch (e) {
    if (e.name !== 'AbortError') ElMessage.error(`保存失败：${e.message}`)
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

/** 顶栏「⋯」菜单：低频操作（导出离线版 / 刷新模板） */
async function onHeaderMenu(cmd) {
  if (cmd === 'offline') {
    await setOfflineExport(!store.pref.offlineExport)
  } else if (cmd === 'refresh') {
    await refreshTemplates()
    ElMessage.success('模板已刷新')
  }
}

const THEME_NAMES = { notion: '米白', paper: '纯白', linen: '亚麻' }
function onTheme(t) { setTheme(t) }
function themeLabel() { return THEME_NAMES[store.pref.theme] || store.pref.theme }

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
    <el-header height="48px" class="header">
      <div class="hgroup">
        <span class="brand">CalcBook</span>
        <el-input v-model="store.project.name" class="proj-name" placeholder="工程名"
                  @change="touch" />
      </div>
      <div class="hgroup">
        <el-button @click="onNewProject">新建</el-button>
        <input ref="fileInput" type="file" accept=".cbproj,.json" hidden @change="onOpenFile" />
        <el-button @click="onOpenProject">打开</el-button>
        <el-button @click="onSaveProject">保存工程</el-button>
      </div>
      <div class="hgroup">
        <el-select v-model="store.currentTemplateId" class="tpl-select"
                   placeholder="选择模板" @change="selectTemplate">
          <el-option v-for="t in store.templates" :key="t.template_id"
                     :value="t.template_id" :label="t.name" />
        </el-select>
        <el-radio-group v-model="store.viewMode" @change="setView">
          <el-radio-button value="single">单项</el-radio-button>
          <el-radio-button value="batch">批量</el-radio-button>
        </el-radio-group>
      </div>
      <div class="header-spacer" />
      <div class="hgroup">
        <el-dropdown @command="onTheme">
          <el-button>主题：{{ themeLabel() }} ▾</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="(name, key) in THEME_NAMES" :key="key" :command="key">
                {{ store.pref.theme === key ? '✓ ' : '' }}{{ name }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <div class="hgroup">
        <el-dropdown split-button type="primary" class="export-btn"
                     @click="onExportProject" @command="onHeaderMenu">
          导出 HTML
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="offline">
                {{ store.pref.offlineExport ? '✓ ' : '' }}导出离线版（内嵌公式字体，约 0.7 MB）
              </el-dropdown-item>
              <el-dropdown-item command="refresh" divided>刷新模板</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
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
          <el-button size="small"
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
            <el-tag v-if="store.staleIds.has(item.id)" size="small" type="warning">模板已改</el-tag>
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
/* ============ CalcBook 设计 token ============
   未来主题切换 = 换这一组变量值（浅色多套方案；暗色暂不做）。 */
:root {
  --cb-canvas: #f7f6f3;        /* 米色画布（顶栏/侧栏/主区底） */
  --cb-surface: #ffffff;       /* 白色表面（卡片/输入框） */
  --cb-hover: #efedea;         /* 悬停：约 5% 亮度变化 */
  --cb-active: #e3e1db;        /* 选中/按下：仅加深背景 */
  --cb-border: #e9e7e4;        /* 微妙边框 */
  --cb-border-strong: #d8d6d2;
  --cb-text: #37352f;          /* 正文主色 */
  --cb-text-2: #5f5e5b;        /* 次要文字 */
  --cb-text-3: #91918e;        /* 弱化文字 */
  --cb-accent: #2eaadc;        /* 强调色 */
  --cb-accent-hover: #3fb3e0;
  --cb-ok: #0f7b6c;
  --cb-bad: #eb5757;
  --cb-warn: #dfab01;

  /* ---- Element Plus 变量映射（light 变体为编译期字面量，必须逐个覆盖）---- */
  --el-color-primary: var(--cb-accent);
  --el-color-primary-light-3: #6cc0e5;
  --el-color-primary-light-5: #97d2ed;
  --el-color-primary-light-7: #c2e4f6;
  --el-color-primary-light-8: #d5edf9;
  --el-color-primary-light-9: #e7f5fb;
  --el-color-primary-dark-2: #2388b0;
  --el-color-success: var(--cb-ok);
  --el-color-success-light-3: #4f968b;
  --el-color-success-light-5: #87bdb5;
  --el-color-success-light-7: #bfd8d3;
  --el-color-success-light-8: #d9e7e4;
  --el-color-success-light-9: #ecf3f2;
  --el-color-danger: var(--cb-bad);
  --el-color-danger-light-3: #f18b8b;
  --el-color-danger-light-5: #f5b0b0;
  --el-color-danger-light-7: #f9d1d1;
  --el-color-danger-light-8: #fbe0e0;
  --el-color-danger-light-9: #fdf0f0;
  --el-color-warning: var(--cb-warn);
  --el-color-warning-light-3: #e8c24d;
  --el-color-warning-light-5: #efd68c;
  --el-color-warning-light-7: #f6e9c4;
  --el-color-warning-light-8: #f9f0d9;
  --el-color-warning-light-9: #fcf7ec;
  --el-color-error: var(--cb-bad);
  --el-text-color-primary: var(--cb-text);
  --el-text-color-regular: var(--cb-text-2);
  --el-text-color-secondary: var(--cb-text-3);
  --el-text-color-placeholder: #b4b2ae;
  --el-border-color: var(--cb-border-strong);
  --el-border-color-light: var(--cb-border);
  --el-border-color-lighter: var(--cb-border);
  --el-fill-color: var(--cb-active);
  --el-fill-color-light: var(--cb-hover);
  --el-fill-color-lighter: #f4f2ef;
  --el-fill-color-blank: var(--cb-surface);
  --el-bg-color: var(--cb-surface);
  --el-bg-color-page: var(--cb-canvas);
  --el-border-radius-base: 6px;
  --el-font-size-base: 14px;
}

/* ============ 浅色主题多套（主题切换 = 换 data-theme 值）============ */
:root[data-theme='paper'] {
  --cb-canvas: #ffffff;
  --cb-hover: #f2f2f0;
  --cb-active: #e8e8e6;
  --cb-border: #e6e5e2;
  --cb-border-strong: #d5d4d0;
}
:root[data-theme='linen'] {
  --cb-canvas: #f3efe6;
  --cb-hover: #eae5d8;
  --cb-active: #ddd6c4;
  --cb-border: #e2dccd;
  --cb-border-strong: #d1cab8;
}

* { box-sizing: border-box; }
html, body, #app { height: 100%; margin: 0; }
body { background: var(--cb-canvas);
       font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                    "Hiragino Sans GB", "Microsoft YaHei", sans-serif; }
.root { height: 100%; color: var(--cb-text); }

/* ============ 顶栏：三组信息架构 ============ */
.header { display: flex; align-items: center; gap: 18px;
          padding: 0 16px; background: var(--cb-canvas);
          border-bottom: 1px solid var(--cb-border); }
.hgroup { display: flex; align-items: center; gap: 6px; }
.header-spacer { flex: 1; }
.brand { font-weight: 700; font-size: 15px; white-space: nowrap; color: var(--cb-text); }
.proj-name { width: 170px; }
.tpl-select { width: 180px; }
.body { height: calc(100% - 48px); }

/* 顶栏输入/选择：Notion 式透明底，悬停描边，聚焦浮起 */
.header .el-input__wrapper,
.header .el-select__wrapper { background-color: transparent; box-shadow: none; }
.header .el-input__wrapper:hover,
.header .el-select__wrapper:hover { background-color: var(--cb-hover);
                                   box-shadow: 0 0 0 1px var(--cb-border-strong) inset; }
.header .el-input__wrapper.is-focus,
.header .el-select__wrapper.is-focused { background-color: var(--cb-surface);
  box-shadow: 0 0 0 1px var(--cb-accent) inset, 0 0 0 3px rgba(46, 170, 220, .18); }

/* ============ Notion 式按钮：透明底，仅背景变化反馈 ============ */
.el-button { --el-button-bg-color: transparent; --el-button-border-color: transparent;
             --el-button-hover-bg-color: var(--cb-hover);
             --el-button-hover-border-color: transparent;
             --el-button-active-bg-color: var(--cb-active);
             --el-button-active-border-color: transparent;
             --el-button-text-color: var(--cb-text);
             --el-button-hover-text-color: var(--cb-text);
             font-weight: 500; }
.el-button.is-disabled { --el-button-text-color: var(--cb-text-3);
                         --el-button-hover-bg-color: transparent; }
/* 实心主按钮（导出 split-button 等） */
.el-button--primary:not(.is-plain):not(.is-text):not(.is-link) {
  --el-button-bg-color: var(--cb-accent);
  --el-button-border-color: var(--cb-accent);
  --el-button-hover-bg-color: var(--cb-accent-hover);
  --el-button-hover-border-color: var(--cb-accent-hover);
  --el-button-active-bg-color: #2995c4;
  --el-button-text-color: #fff;
  --el-button-hover-text-color: #fff;
}
/* plain 主按钮 → Notion 次级：强调色文字 + 悬停浅背景 */
.el-button--primary.is-plain {
  --el-button-text-color: var(--cb-accent);
  --el-button-hover-text-color: var(--cb-accent);
  --el-button-bg-color: transparent;
  --el-button-hover-bg-color: var(--cb-hover);
}
.el-button--primary.is-text, .el-button--primary.is-link { color: var(--cb-accent); }

/* 单项/批量切换：分段控件，选中仅加深背景（Micro-click） */
.el-radio-button { --el-radio-button-checked-bg-color: var(--cb-active);
                   --el-radio-button-checked-text-color: var(--cb-text);
                   --el-radio-button-checked-border-color: var(--cb-border-strong); }
.el-radio-group { --el-border-color: var(--cb-border-strong); }
.el-radio-button__inner { background-color: transparent; font-weight: 500; }

/* ============ 侧栏 ============ */
.aside { background: var(--cb-canvas); border-right: 1px solid var(--cb-border);
         padding: 10px; overflow: auto; }
.loader-err { margin-bottom: 10px; }
.err-pre { max-height: 200px; overflow: auto; font-size: 11px; line-height: 1.4; margin: 4px 0 0; }
.aside-head { display: flex; justify-content: space-between; align-items: center; margin: 4px 0 8px;
              color: var(--cb-text-2); font-size: 13px; font-weight: 600; }
.group-title { font-size: 12px; color: var(--cb-text-3); margin: 10px 0 4px; }
.item-row { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-radius: 4px;
            cursor: pointer; font-size: 13px; color: var(--cb-text);
            transition: background-color 150ms; }
.item-row:hover { background: var(--cb-hover); }
.item-row.active { background: var(--cb-active); }
.item-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-hint { color: var(--cb-text-3); font-size: 12px; margin-top: 20px; text-align: center; }

/* ============ 主区：米色画布 + 白色卡片 ============ */
.main { padding: 8px 16px 16px; overflow: auto; }
.spin { animation: rotate 1s linear infinite; }
@keyframes rotate { to { transform: rotate(360deg); } }

/* ============ 批量表格（保持紧凑双密度）============ */
.el-table { --el-table-border-color: var(--cb-border);
            --el-table-header-bg-color: #faf9f6;
            --el-table-header-text-color: var(--cb-text-2);
            --el-table-row-hover-bg-color: #f3f1ee;
            --el-table-tr-bg-color: var(--cb-surface);
            --el-table-bg-color: var(--cb-surface); }
.el-table th.el-table__cell { font-weight: 600; }

/* 弹层：白底 + 微妙边框（menu/popover/dialog 由 EP 变量已覆盖大部分） */
.el-popper.is-light { border-color: var(--cb-border); }
</style>
