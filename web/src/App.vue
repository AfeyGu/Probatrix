<script setup>
import { computed, nextTick, onMounted, ref, shallowRef } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { store, refreshTemplates, selectTemplate, setView, addItem,
         saveProjectAs, openProjectFile, exportProjectHtml, exportProjectMd,
         newBlankProject, touch, setOfflineExport, setTheme, fsPickSupported,
         PROJECT_FILE_SUFFIX, PROJECT_FILE_TYPE } from './store'
import SingleView from './components/SingleView.vue'
import BatchView from './components/BatchView.vue'
import WindowControls from './components/WindowControls.vue'

const fileInput = ref(null)
const desktopWindow = shallowRef(null)
const windowControls = ref(null)

onMounted(async () => {
  try {
    const windowApi = window.__TAURI__?.window?.getCurrentWindow()
    if (!windowApi) return
    await windowApi.isMaximized()
    desktopWindow.value = windowApi
    await nextTick()
    // 保证按钮已挂载，启动和授权失败时仍可用系统按钮关窗。
    if (!windowControls.value) {
      desktopWindow.value = null
      return
    }
    await windowApi.setDecorations(false)
  } catch (error) {
    desktopWindow.value = null
    console.warn('使用系统标题栏', error)
  }
})

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
        types: [PROJECT_FILE_TYPE],
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

/** 顶栏「⋯」菜单：低频操作（导出 md / 导出离线版 / 刷新模板） */
async function onHeaderMenu(cmd) {
  if (cmd === 'offline') {
    await setOfflineExport(!store.pref.offlineExport)
  } else if (cmd === 'md') {
    try {
      await exportProjectMd()
      ElMessage.success('已导出 Markdown')
    } catch (e) {
      ElMessage.error(e.message)
    }
  } else if (cmd === 'refresh') {
    await refreshTemplates()
    ElMessage.success('模板已刷新')
  }
}

const THEME_NAMES = { notion: '雾蓝', paper: '素白', linen: '暖砂' }
function onTheme(t) { setTheme(t) }
function themeLabel() { return THEME_NAMES[store.pref.theme] || store.pref.theme }

// 当前服务地址（桌面窗口 / 浏览器一致；端口被占用递加后仍准确）
const serverUrl = window.location.origin

async function onSelectTemplate(templateId) {
  try {
    return await selectTemplate(templateId)
  } catch (error) {
    ElMessage.error(`读取模板失败：${error.message}`)
    return false
  }
}

async function onAddItem() {
  try {
    await addItem(store.currentTemplateId)
  } catch (error) {
    ElMessage.error(`添加计算项失败：${error.message}`)
  }
}

async function onPickItem(group, item) {
  if (group.id !== '?' && !(await onSelectTemplate(group.id))) return
  store.activeItemId = item.id
  setView('single')
}

function ratioOf(item) {
  return store.results[item.id]?.max_ratio
}
</script>

<template>
  <el-container class="root">
    <el-header height="48px" class="header" :class="{ 'desktop-header': desktopWindow }"
               :data-tauri-drag-region="desktopWindow ? '' : undefined">
      <div class="hgroup">
        <span class="brand" :data-tauri-drag-region="desktopWindow ? '' : undefined">Probatrix</span>
        <el-input v-model="store.project.name" class="proj-name" placeholder="工程名"
                  @change="touch" />
      </div>
      <div class="hgroup">
        <el-button @click="onNewProject">新建</el-button>
        <input ref="fileInput" type="file" :accept="PROJECT_FILE_SUFFIX" hidden @change="onOpenFile" />
        <el-button @click="onOpenProject">打开</el-button>
        <el-button @click="onSaveProject">保存工程</el-button>
      </div>
      <div class="hgroup">
        <el-select v-model="store.currentTemplateId" class="tpl-select"
                   placeholder="选择模板" @change="onSelectTemplate">
          <el-option v-for="t in store.templates" :key="t.template_id"
                     :value="t.template_id"
                     :label="t.name + (t.missing_deps && t.missing_deps.length ? '（缺依赖：' + t.missing_deps.join('、') + '）' : '')" />
        </el-select>
        <el-radio-group v-model="store.viewMode" class="view-switch" aria-label="计算视图"
                        :data-mode="store.viewMode" @change="setView">
          <el-radio-button value="single">单项</el-radio-button>
          <el-radio-button value="batch">批量</el-radio-button>
        </el-radio-group>
      </div>
      <div class="header-spacer" :data-tauri-drag-region="desktopWindow ? '' : undefined" />
      <span v-if="!desktopWindow" class="server-url" :title="serverUrl">{{ serverUrl }}</span>
      <div class="hgroup">
        <el-dropdown @command="onTheme">
          <el-button :aria-label="`切换主题，当前${themeLabel()}`"><span class="theme-prefix">主题：</span>{{ themeLabel() }} ▾</el-button>
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
              <el-dropdown-item command="md" divided>导出 Markdown（.md 计算原文）</el-dropdown-item>
              <el-dropdown-item command="refresh" divided>刷新模板</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <WindowControls v-if="desktopWindow" ref="windowControls" :window-api="desktopWindow" />
    </el-header>

    <el-container class="body">
      <el-aside width="clamp(200px, 22vw, 270px)" class="aside glass-panel">
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
                     @click="onAddItem">
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
/* ============ Probatrix 设计令牌（v2-pro 通透体系，规范见 docs/subsystems/UI设计规范.md）============
   三档半径 · 三级材质 · 全按钮无突出色 · 光自上来。主题切换 = 换 data-theme 下的色组。 */
:root {
  /* 画布与色斑（body 三团 radial 渐变叠加在画布上） */
  --cb-canvas: #e8edf5;
  --cb-spot-1: rgba(110, 155, 232, .52);
  --cb-spot-2: rgba(190, 164, 238, .44);
  --cb-spot-3: rgba(126, 196, 222, .38);

  /* 材质：L1 主卡 / L2 浮层 / 输入件 */
  --cb-surface: rgba(255, 255, 255, .56);        /* L1 玻璃卡 */
  --cb-surface-solid: #ffffff;                    /* 纸面等实心场景 */
  --cb-l1-blur: 40px;  --cb-l1-sat: 1.9;
  --cb-l2-bg: rgba(255, 255, 255, .74);
  --cb-l2-blur: 52px;  --cb-l2-sat: 2.1;
  --cb-glass-hi: rgba(255, 255, 255, .95);        /* 卡片上缘高光 */
  --cb-glass-lo: rgba(15, 34, 64, .10);           /* 下缘暗线 */
  --cb-sh-near: 0 2px 8px rgba(30, 58, 92, .18);
  --cb-sh-far: 0 12px 32px rgba(30, 58, 92, .26);

  /* 交互面色 */
  --cb-hover: rgba(15, 34, 64, .05);
  --cb-active: rgba(15, 34, 64, .09);
  --cb-border: rgba(15, 34, 64, .10);
  --cb-border-strong: rgba(15, 34, 64, .16);

  /* 文字三级 + 功能色 */
  --cb-text: #12161d;
  --cb-text-2: #4e5a6b;
  --cb-text-3: #7b8798;
  --cb-accent: #1a6fd4;
  --cb-accent-hover: #0f5bb5;
  --cb-accent-soft: rgba(26, 111, 212, .09);
  --cb-ok: #137a52;
  --cb-bad: #b42318;
  --cb-warn: #9a6700;

  /* 三档半径（全站只此三档，禁止第四档） */
  --cb-r-card: 24px;
  --cb-r-ctl: 12px;
  --cb-r-pill: 999px;
  --cb-panel-gap: 12px;

  /* 字体三级：Display 标题 / Text 正文 / Num 数值 */
  --cb-font-display: "Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI",
                     system-ui, "Microsoft YaHei UI", "PingFang SC", sans-serif;
  --cb-font-text: "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI",
                  "PingFang SC", system-ui, sans-serif;
  --cb-font-num: "Cascadia Mono", "Segoe UI Variable Text", ui-monospace, Consolas, monospace;

  /* ---- Element Plus 变量映射（light 变体为编译期字面量，必须逐个覆盖）---- */
  --el-color-primary: var(--cb-accent);
  --el-color-primary-light-3: #5b93dd;
  --el-color-primary-light-5: #8db4e8;
  --el-color-primary-light-7: #bed4f1;
  --el-color-primary-light-8: #d3e2f6;
  --el-color-primary-light-9: #e8f0fb;
  --el-color-primary-dark-2: var(--cb-accent-hover);
  --el-color-success: var(--cb-ok);
  --el-color-success-light-3: #4f9681;
  --el-color-success-light-5: #87bdae;
  --el-color-success-light-7: #bfd8cf;
  --el-color-success-light-8: #d9e7e2;
  --el-color-success-light-9: #ecf3f0;
  --el-color-danger: var(--cb-bad);
  --el-color-danger-light-3: #cb6159;
  --el-color-danger-light-5: #d9928d;
  --el-color-danger-light-7: #ecc4c1;
  --el-color-danger-light-8: #f3d8d6;
  --el-color-danger-light-9: #f9eceb;
  --el-color-warning: var(--cb-warn);
  --el-color-warning-light-3: #b8871a;
  --el-color-warning-light-5: #ccab63;
  --el-color-warning-light-7: #e5d2a8;
  --el-color-warning-light-8: #eee0c2;
  --el-color-warning-light-9: #f6eeda;
  --el-color-error: var(--cb-bad);
  --el-text-color-primary: var(--cb-text);
  --el-text-color-regular: var(--cb-text-2);
  --el-text-color-secondary: var(--cb-text-3);
  --el-text-color-placeholder: #9aa5b2;
  --el-border-color: var(--cb-border-strong);
  --el-border-color-light: var(--cb-border);
  --el-border-color-lighter: var(--cb-border);
  --el-fill-color: var(--cb-active);
  --el-fill-color-light: var(--cb-hover);
  --el-fill-color-lighter: rgba(15, 34, 64, .03);
  --el-fill-color-blank: transparent;
  --el-bg-color: var(--cb-surface-solid);
  --el-bg-color-overlay: var(--cb-l2-bg);
  --el-bg-color-page: var(--cb-canvas);
  --el-border-radius-base: var(--cb-r-ctl);
  --el-font-size-base: 14px;
  --el-box-shadow: var(--cb-sh-near), var(--cb-sh-far);
  --el-box-shadow-light: var(--cb-sh-near);
}

/* ============ 主题多套（换 data-theme 值 = 换画布色相，材质与三档半径不变）============ */
:root[data-theme='paper'] {
  --cb-canvas: #eef1f6;
  --cb-spot-1: rgba(146, 172, 214, .40);
  --cb-spot-2: rgba(178, 178, 208, .32);
  --cb-spot-3: rgba(160, 190, 206, .26);
}
:root[data-theme='linen'] {
  --cb-canvas: #f0ece4;
  --cb-spot-1: rgba(226, 176, 128, .34);
  --cb-spot-2: rgba(198, 168, 214, .26);
  --cb-spot-3: rgba(232, 202, 140, .26);
}

* { box-sizing: border-box; }
html, body, #app { height: 100%; margin: 0; }
body {
  color: var(--cb-text);
  font-family: var(--cb-font-text);
  background:
    radial-gradient(1200px 700px at 10% -12%, var(--cb-spot-1), transparent 58%),
    radial-gradient(1000px 620px at 94% 2%, var(--cb-spot-2), transparent 60%),
    radial-gradient(900px 700px at 58% 112%, var(--cb-spot-3), transparent 58%),
    var(--cb-canvas);
  background-attachment: fixed;
  -webkit-font-smoothing: antialiased;
}
.root { height: 100%; color: var(--cb-text); }

/* ════════════ 顶栏：Mica 玻璃条 ════════════ */
.header {
  --cb-toolbar-control-height: 32px;
  display: flex; align-items: center; gap: 16px;
  padding: 0 14px;
  background: rgba(255, 255, 255, .62);
  -webkit-backdrop-filter: blur(24px) saturate(1.8);
  backdrop-filter: blur(24px) saturate(1.8);
  border-bottom: 1px solid var(--cb-border);
  box-shadow: inset 0 1px 0 var(--cb-glass-hi);
}
.hgroup { display: flex; align-items: center; gap: 6px; }
.header-spacer { flex: 1; }
.server-url {
  font-size: 12px; color: var(--cb-text-3); font-family: var(--cb-font-num);
  white-space: nowrap; user-select: text;
}
.brand {
  font-weight: 600; font-size: 14px; white-space: nowrap; color: var(--cb-text);
  font-family: var(--cb-font-display); letter-spacing: .01em;
}
.proj-name { width: 170px; }
.tpl-select { width: 180px; }

.header :is(.el-input__wrapper, .el-select__wrapper, .el-button) {
  height: var(--cb-toolbar-control-height);
  corner-shape: round;
}
.header :is(.el-input__wrapper, .el-select__wrapper) { border-radius: var(--cb-r-pill); }
.header .export-btn .el-button-group { display: inline-flex; }

.desktop-header { gap: 12px; padding-inline: 12px; }
.desktop-header .hgroup { flex: none; gap: 4px; }
.desktop-header .hgroup > .el-button + .el-button { margin-left: 0; }
.desktop-header .proj-name { width: clamp(88px, 10vw, 170px); }
.desktop-header .tpl-select { width: clamp(108px, 12vw, 180px); }
.desktop-header .header-spacer { align-self: stretch; min-width: 24px; }
.desktop-header .brand { user-select: none; }

@media (max-width: 1100px) {
  .desktop-header { gap: 8px; }
  .desktop-header .hgroup > .el-button,
  .desktop-header .el-dropdown .el-button { padding-inline: 8px; }
  .desktop-header .view-switch { --cb-mode-padding: 8px; }
  .desktop-header .theme-prefix { display: none; }
}

/* 输入与下拉共用轻材质。顶栏轮廓由上方的顶栏控件样式定义。 */
.el-input__wrapper, .el-select__wrapper {
  background-color: rgba(255, 255, 255, .86);
  border-radius: var(--cb-r-ctl);
  corner-shape: squircle;
  box-shadow: 0 0 0 1px rgba(15, 34, 64, .12) inset, inset 0 1px 0 rgba(255, 255, 255, .95);
  transition: background-color 150ms ease-out, box-shadow 180ms ease-out;
}
.el-input__wrapper:hover, .el-select__wrapper:hover {
  background-color: #fff;
  box-shadow: 0 0 0 1px rgba(15, 34, 64, .22) inset, inset 0 1px 0 #fff;
}
.el-input__wrapper.is-focus, .el-select__wrapper.is-focused {
  background-color: #fff;
  box-shadow: 0 0 0 1px var(--cb-accent) inset, 0 0 0 3px var(--cb-accent-soft);
}
.el-textarea__inner {
  background-color: rgba(255, 255, 255, .86);
  border-radius: var(--cb-r-ctl);
  corner-shape: squircle;
  box-shadow: 0 0 0 1px rgba(15, 34, 64, .12) inset, inset 0 1px 0 rgba(255, 255, 255, .95);
}

/* ════════════ 按钮：全站唯一玻璃胶囊，无突出色 ════════════ */
.el-button {
  --el-button-bg-color: rgba(255, 255, 255, .9);
  --el-button-border-color: transparent;
  --el-button-hover-bg-color: #fff;
  --el-button-hover-border-color: rgba(26, 111, 212, .34);
  --el-button-active-bg-color: rgba(255, 255, 255, .72);
  --el-button-active-border-color: rgba(26, 111, 212, .34);
  --el-button-text-color: var(--cb-text);
  --el-button-hover-text-color: var(--cb-text);
  --el-button-disabled-bg-color: rgba(255, 255, 255, .5);
  --el-button-disabled-border-color: transparent;
  --el-button-disabled-text-color: var(--cb-text-3);
  border-radius: var(--cb-r-pill);
  corner-shape: squircle;
  font-weight: 500;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .95), 0 1px 2px rgba(16, 28, 48, .06);
  transition: background-color 150ms ease-out, box-shadow 150ms ease-out, border-color 150ms ease-out;
}
.el-button:hover { box-shadow: inset 0 1px 0 #fff, 0 2px 8px rgba(30, 58, 92, .14); }
.el-button.is-disabled, .el-button.is-disabled:hover { box-shadow: none; }
/* primary 同款（不做实心突出色；主次靠位置与字重） */
.el-button--primary:not(.is-text):not(.is-link) {
  --el-button-bg-color: rgba(255, 255, 255, .9);
  --el-button-border-color: transparent;
  --el-button-hover-bg-color: #fff;
  --el-button-hover-border-color: rgba(26, 111, 212, .34);
  --el-button-text-color: var(--cb-text);
  --el-button-hover-text-color: var(--cb-text);
  font-weight: 600;
}
/* text / link 按钮：透明底、文字色 */
.el-button.is-text, .el-button.is-link {
  border: 0; background: transparent; box-shadow: none;
}
.el-button.is-text:hover, .el-button.is-link:hover { background: var(--cb-hover); }
.el-button--primary.is-text, .el-button--primary.is-link { color: var(--cb-accent); }
.el-button--danger.is-text { color: var(--cb-bad); }
/* split-button：两段各自胶囊端 */
.el-button-group .el-button:first-child {
  border-radius: var(--cb-r-pill) 0 0 var(--cb-r-pill);
}
.el-button-group .el-button:last-child {
  border-radius: 0 var(--cb-r-pill) var(--cb-r-pill) 0;
}

/* ════════════ 视图切换：选中胶囊沿共同轨道滑动 ════════════ */
.header .view-switch {
  position: relative;
  isolation: isolate;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  flex: none;
  height: var(--cb-toolbar-control-height);
  padding: 2px;
  background: var(--cb-active);
  border-radius: var(--cb-r-pill);
  corner-shape: round;
  box-shadow: inset 0 1px 0 var(--cb-border);
}
.view-switch::before {
  content: "";
  position: absolute;
  z-index: -1;
  inset: 2px auto 2px 2px;
  width: calc(50% - 2px);
  border-radius: var(--cb-r-pill);
  corner-shape: round;
  background: var(--cb-surface-solid);
  box-shadow: 0 1px 2px var(--cb-border-strong);
  pointer-events: none;
  transform: translateX(0);
  transition: transform 200ms cubic-bezier(.22, 1, .36, 1);
}
.view-switch[data-mode='batch']::before { transform: translateX(100%); }
.view-switch .el-radio-button {
  --el-radio-button-checked-bg-color: transparent;
  --el-radio-button-checked-text-color: var(--cb-text);
  --el-radio-button-checked-border-color: transparent;
  height: 100%;
}
.view-switch .el-radio-button .el-radio-button__inner {
  display: grid;
  place-items: center;
  height: 100%;
  padding: 0 var(--cb-mode-padding, 12px);
  border: 0;
  border-radius: var(--cb-r-pill);
  corner-shape: round;
  outline-color: transparent;
  color: var(--cb-text-2);
  font-size: 13px;
  font-weight: 500;
  transition: color 150ms ease-out;
}
.view-switch .el-radio-button.is-active .el-radio-button__inner { font-weight: 600; }
.view-switch .el-radio-button__original-radio:focus-visible + .el-radio-button__inner {
  outline: 2px solid var(--cb-accent);
  outline-offset: -2px;
}

/* ════════════ 工作区：侧栏、参数与预览共用玻璃卡材质 ════════════ */
.root .body {
  flex: 1;
  min-height: 0;
  padding: var(--cb-panel-gap);
  gap: var(--cb-panel-gap);
}
.glass-panel {
  background: linear-gradient(180deg, rgba(255, 255, 255, .5), transparent 110px),
              var(--cb-surface);
  -webkit-backdrop-filter: blur(var(--cb-l1-blur)) saturate(var(--cb-l1-sat));
  backdrop-filter: blur(var(--cb-l1-blur)) saturate(var(--cb-l1-sat));
  border: 1px solid rgba(255, 255, 255, .9);
  border-radius: var(--cb-r-card);
  corner-shape: squircle;
  box-shadow: inset 0 1px 0 var(--cb-glass-hi), inset 0 -1px 0 var(--cb-glass-lo),
              0 1px 2px rgba(16, 28, 48, .05), 0 10px 28px -14px rgba(16, 28, 48, .18);
}
.aside { padding: 12px; overflow: auto; }
.loader-err { margin-bottom: 10px; border-radius: var(--cb-r-ctl); corner-shape: squircle; }
.err-pre { max-height: 200px; overflow: auto; font-size: 11px; line-height: 1.4; margin: 4px 0 0; }
.aside-head {
  display: flex; justify-content: space-between; align-items: center; margin: 4px 0 8px;
  color: var(--cb-text-2); font-size: 13px; font-weight: 600;
  font-family: var(--cb-font-display);
}
.group-title { font-size: 12px; color: var(--cb-text-3); margin: 10px 0 4px; }
.item-row {
  display: flex; align-items: center; gap: 6px; padding: 6px 10px;
  border-radius: var(--cb-r-pill);
  corner-shape: squircle;
  cursor: pointer; font-size: 13px; color: var(--cb-text);
  transition: background-color 150ms ease-out;
}
.item-row:hover { background: var(--cb-hover); }
.item-row.active { background: rgba(15, 34, 64, .08); font-weight: 500; }
.item-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-hint { color: var(--cb-text-3); font-size: 12px; margin-top: 20px; text-align: center; }

.body > .main { min-width: 0; padding: 0; overflow: visible; }
.spin { animation: rotate 1s linear infinite; }
@keyframes rotate { to { transform: rotate(360deg); } }

/* ════════════ 批量表格（保持紧凑密度，13px）════════════ */
.el-table {
  --el-table-border-color: rgba(15, 34, 64, .08);
  --el-table-header-bg-color: rgba(255, 255, 255, .5);
  --el-table-header-text-color: var(--cb-text-2);
  --el-table-row-hover-bg-color: rgba(26, 111, 212, .06);
  --el-table-tr-bg-color: transparent;
  --el-table-bg-color: transparent;
  --el-table-expanded-cell-bg-color: transparent;
  font-size: 13px;
}
.el-table th.el-table__cell { font-weight: 600; }
.el-table td.el-table__cell, .el-table th.el-table__cell { border-bottom: 1px solid rgba(15, 34, 64, .07); }
/* 冻结列必须有遮挡底色：表格整体透明化后，横滚内容会从固定列下方穿透
   （EP 冻结列 = sticky 覆盖层，靠自身背景遮挡，见 AGENTS.md 前端易错点） */
.el-table .el-table__cell.el-table-fixed-column--left,
.el-table .el-table__cell.el-table-fixed-column--right {
  background: rgba(248, 250, 253, .97);
}
.el-table th.el-table__cell.el-table-fixed-column--left,
.el-table th.el-table__cell.el-table-fixed-column--right {
  background: rgba(250, 252, 254, .97);
}
.el-table__body tr:hover > td.el-table-fixed-column--left,
.el-table__body tr:hover > td.el-table-fixed-column--right {
  background: rgba(233, 240, 250, .98);
}
.el-table td .cell { font-variant-numeric: tabular-nums; }
/* 数值类输入：等宽数字（含批量表格与表单） */
.el-input__inner { font-variant-numeric: tabular-nums; }
.el-input-number .el-input__inner { font-family: var(--cb-font-num); text-align: left; }

/* ════════════ 浮层：L2 Acrylic 材质 ════════════ */
.el-popper.is-light, .el-dropdown__popper, .el-select__popper {
  background: var(--cb-l2-bg);
  -webkit-backdrop-filter: blur(52px) saturate(2.1);
  backdrop-filter: blur(52px) saturate(2.1);
  border: 1px solid rgba(255, 255, 255, .92);
  border-radius: var(--cb-r-card);
  corner-shape: squircle;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .55), inset 0 -1px 0 rgba(30, 58, 92, .16),
              var(--cb-sh-near), var(--cb-sh-far);
}
.el-popper.is-light .el-popper__arrow::before { background: rgba(255, 255, 255, .74); border-color: rgba(255, 255, 255, .92); }
.el-dropdown-menu__item, .el-select-dropdown__item {
  border-radius: var(--cb-r-pill);
  corner-shape: squircle;
  margin: 2px 6px;
  padding: 5px 12px;
}
.el-dropdown-menu__item:not(.is-disabled):focus,
.el-dropdown-menu__item:not(.is-disabled):hover,
.el-select-dropdown__item.is-hovering {
  background: rgba(15, 34, 64, .06);
  color: var(--cb-text);
}
.el-select-dropdown__item.is-selected { color: var(--cb-accent); font-weight: 600; }

/* ════════════ 对话框 / 确认框 / 消息：L2 玻璃 ════════════ */
.el-overlay { background: rgba(12, 22, 38, .24); backdrop-filter: blur(3px); }
.el-dialog, .el-message-box {
  background: var(--cb-l2-bg);
  -webkit-backdrop-filter: blur(52px) saturate(2.1);
  backdrop-filter: blur(52px) saturate(2.1);
  border: 1px solid rgba(255, 255, 255, .92);
  border-radius: var(--cb-r-card);
  corner-shape: squircle;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .55), inset 0 -1px 0 rgba(30, 58, 92, .16),
              var(--cb-sh-near), var(--cb-sh-far);
}
.el-dialog__title, .el-message-box__title { font-family: var(--cb-font-display); font-weight: 600; }
.el-message {
  background: var(--cb-l2-bg);
  -webkit-backdrop-filter: blur(40px) saturate(2);
  backdrop-filter: blur(40px) saturate(2);
  border: 1px solid rgba(255, 255, 255, .92);
  border-radius: var(--cb-r-pill);
  corner-shape: squircle;
  box-shadow: var(--cb-sh-near), var(--cb-sh-far);
}
.el-popper.is-dark {
  border-radius: 12px; corner-shape: squircle;
  background: rgba(18, 22, 29, .92); backdrop-filter: blur(20px);
}

/* ════════════ 小元件 ════════════ */
.el-tag {
  border-radius: var(--cb-r-pill);
  corner-shape: squircle;
  border: 0;
  font-weight: 500;
}
.el-switch.is-checked .el-switch__core { background: var(--cb-accent); border-color: var(--cb-accent); }
.el-switch__core { border-radius: var(--cb-r-pill); corner-shape: squircle; }
.el-checkbox__inner { border-radius: 4px; corner-shape: squircle; }
.el-checkbox__input.is-checked .el-checkbox__inner { background: var(--cb-accent); border-color: var(--cb-accent); }
.el-checkbox__inner::after { border-color: #fff; }
.el-popover { padding: 10px 12px; }
/* 滚动条细长圆角 */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-corner { background: transparent; }
::-webkit-scrollbar-thumb {
  background: rgba(15, 34, 64, .16); border-radius: 5px;
  border: 3px solid transparent; background-clip: content-box;
}
::-webkit-scrollbar-thumb:hover { background: rgba(15, 34, 64, .28); background-clip: content-box; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; }
}
</style>
