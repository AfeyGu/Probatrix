# AGENTS.md

CalcBook——结构构件批量计算书工具。FastAPI 后端 + Vue3 前端，pip 分发，`calcbook serve` 一条命令起本地服务。

## 常用命令

```bash
pip install -e .                      # 可编辑安装（改后端代码即时生效）
python -m pytest tests -q             # 全部测试（90 个：契约/后端/API + 模板回归）
python -m pytest tests/test_server.py::test_run_batch -q   # 单个测试

calcbook serve --templates examples --port 8317 --no-browser   # 起本地服务
calcbook serve --templates <目录>      # 生产形态：自动开浏览器，默认端口 8317

cd web
npm install                           # 仅前端开发需要 Node
npm run dev                           # vite:5173，/api 代理到 127.0.0.1:8317
npm run build                         # 构建到 src/calcbook/web/ 并拷贝 vendor-katex
```

- **打包验证**：`pip wheel --no-deps -w _wheelcheck .`（wheel 应 ~2.4 MB，含 `src/calcbook/web` 与 `src/calcbook/vendor`，用完删 `_wheelcheck/`）。
- **离线发布包**：`python tools/build_release.py`（依赖 `pip install build pyinstaller`），产出 `release/calcbook-<版本>.zip`，全离线，详见「关键设计决定」。
- 服务端 Python 代码改动需重启服务；`src/calcbook/web`、`src/calcbook/vendor` 由构建产出，**不要手改**。
- 打包配置在 `pyproject.toml`（package-data 含 web/vendor）+ `MANIFEST.in`，两者要同步维护。

## 架构（数据流）

```
模板文件（examples/gl.py）
  → loader.py    目录扫描，importlib 导入（报错隔离到 errors，不打断其他文件），
                 收集 __calcbook_template__ 标记，填 template_id = "文件名.函数名"，算 sha256；
                 读模块级 __calcbook_requires__ 声明并查环境（find_spec），缺的记入 meta.missing_deps
  → engine.py    run_template(meta, params_dict, name="")：校验（pydantic）→ 执行 → 永不抛异常，
                 失败时 traceback 原样进 RunResult.error（这是模板作者的调试界面）；
                 模板函数声明可选 name 形参时，计算项「名称」作项目编号传入
  → calcbook.py  CalcBook Builder：formula/subs/check/cite/image/table → items；
                 to_html() 直出 HTML（预览/导出用）、to_markdown() 纯导出物（下载阅读）；
                 check() 一等公民：正文判定行 + 末尾自动「验算结论汇总」表 + max_ratio；
                 metric(name, 值)：批量表格附加指标列（不进正文，随 RunResult.metrics 到前端动态成列）
  → server.py    FastAPI：/api/templates、/api/run(-batch)（响应含 html）、/api/project、
                 /api/hash-check、/api/export/html（收前端拼好的 html）、/api/doc.css；
                 静态托管 src/calcbook/web
  → web/ (Vue3)  store.js 单一状态源；参数变更防抖 300ms 自动重算；工程 800ms 防抖回写服务端
                 （刷新页面不丢）；预览直接用 run 返回的 html（KaTeX 扫描）；导出：HTML 走
                 api.exportHtml（多项合并时前端拼 page-break div；勾选离线版则 inline_assets=true），
                 Markdown 直接前端下载（md 为纯导出物，不参与渲染）；
                 界面主题/离线偏好存 localStorage
  → project.py   .cbproj 纯 JSON：items[{id,name,template_id,template_hash,params,deps}] + views
  → docstyle.py  计算书文档排版 CSS（.cb-doc）唯一定义处：预览经 /api/doc.css 加载，
                 导出模板注入 @@DOCSTYLE@@——保证所见即所得，不要在别处复制这份样式
```

## 关键设计决定（改代码前先读 `计算书工具文档.md`）

- **改了机制/约定必须同步文档**：凡涉及契约、API、数据流、行为约定的变更，
  同轮同步相关 md（`AGENTS.md` 架构图、`计算书工具文档.md`、`docs/模板开发指南.md`、
  `README.md`），不能只改代码。
- **模板第三方依赖用 `__calcbook_requires__` 声明**（模块级 import 名列表，可选）：
  loader 加载时检查环境，缺失记入 meta.missing_deps（/api/templates 与 schema 带出，
  前端下拉标注）；run 前拦截给「缺少依赖 + pip 指引」；engine 另兜底 ModuleNotFoundError
  （解析 No module named 'X'，不甩原始 traceback）；离线包启动器（CalcBook.exe）启动时按全部模板
  声明把缺的库用 pip（国内镜像）自动装进包内 python/。
- **离线发布包内置 Python，全离线**：`tools/build_release.py` 产出
  `release/calcbook-<版本>.zip` = `CalcBook.exe`（PyInstaller `--windowed` 启动器，
  无控制台黑窗）+ `python/`（嵌入版 Python 3.12，构建时启用 site、装 pip、
  预装 calcbook wheel + numpy/scipy/pandas/matplotlib/openpyxl，并剔除各库
  tests/ 目录）+ `examples/` + `docs/`。**wheel 是构建中间产物**——构建时装进
  包内 Python，不随 zip 分发。用户解压双击即用：零联网、不依赖系统 Python、
  不写注册表/环境变量，删目录即完全卸载；仅模板缺第三方库时启动器用包内
  pip（国内镜像）补装进 `python/`。升级 = 整包替换。
- **契约是产品核心**：模板作者只 import `CalcBook / Field / template` 三个名字（`src/calcbook/__init__.py`）。参数声明的 `label/unit/choices/group/batch_hidden/row/show_if` 同时驱动前端表单、批量表格列、.cbproj 三处——改契约要三处一起考虑（batch_hidden：批量表格默认隐藏列，可在「列显隐」勾回；row：声明相邻且同标记的参数在单件表单并排一行；show_if：条件显隐小表达式，不满足时表单隐藏但值保留，批量侧降级为默认隐藏列——它只是界面提示，开关想改变计算需模板计算里自己分支）。
- **模板内部统一 SI 基本单位**，`Field(unit=...)` 只管展示换算；不做自动单位引擎。
- **统一设置是批量赋值操作**：每行 params 始终存完整值，无隐藏状态。
- **hash 只覆盖模板主文件**，`deps` 字段为依赖模块（如 Hsteel.py）预留。
- **离线导出只内联 woff2**：woff/ttf 加上会到 1.73 MB，不划算；vendor 目录只备 css+2js+20 个 woff2。
- **导出页模板用 `@@MARKER@@` 占位 + `str.replace`**，不能用 `str.format`（CSS 花括号冲突）。
- **管线是 items → HTML 直通**（无 md 解析层）：结构只由 Builder API 决定，文本一律 `_esc` 后进 `_inline`（仅 `**粗体**`），转义与行内格式契约由 `tests/test_html_contract.py` 锁定——改渲染必须同步契约文档（模板开发指南 §3.1）。

## 界面设计系统（Notion 风，改样式前先看这段）

- **UI 设计标准（v2-pro 定稿）见 `docs/ui-design.md`**：三档半径（squircle 变曲率）、Mica/Acrylic 三级材质、全按钮无突出色等硬规则；新增或修改界面一律遵照该文档。本节其余内容为当前代码的样式实现说明。

- **所有颜色走 App.vue `:root` 的 `--cb-*` token**（画布/表面/hover/文字/语义色），Element Plus 的 `--el-*` 映射到 token。**改配色只改 token，不硬编码色值**。
- **主题切换 = 换 `data-theme` 属性下的 token 组**（现有米白/纯白/亚麻三套浅色，暗色暂不做）。新主题只需在 App.vue 加一个 `:root[data-theme=…]` 块。
- EP 的 `--el-color-primary-light-3/5/7/8/9`、`-dark-2` 是编译期字面量，**换主色必须逐个覆盖**，只改 `--el-color-primary` 会让 plain 按钮/标签还是旧色。
- Notion 风硬规则：禁渐变、禁大圆角（>8px）、禁重阴影、禁 translate/scale 动画；过渡只允许 background/border-color 150ms；按钮透明底、hover 仅背景变 `--cb-hover`、active `--cb-active`。
- 双密度：批量表格保持紧凑（small/13px/单行），其余界面 14px 带呼吸感；批量表格列 min-width 由表头文字单行宽度算出（`colMinW`），单元格 nowrap。
- 文档预览区（.cb-doc）是正式纸感（衬线/黑白），与界面风格刻意分区——预览必须与导出一致，改排版只改 `docstyle.py`。

## 前端易错点（都踩过）

- **store 里往 items 塞对象后必须返回数组里的元素**（`store.project.items[len-1]`）——push 进 reactive 数组的原始对象赋值会绕过代理、界面不刷新（数据对、显示错，极难排查）。
- `web/src/main.js` 用独立导出的 `init()`，不是 `store.init()`。
- 刷新/切模板后对无缓存结果的项要 `scheduleRun` 补算，否则导出报「没有可导出的结果」。
- Element Plus 2.9 的 el-select 选中值不在 `input.value` 里，读 DOM 验证用 `.el-select__wrapper` 的 textContent。
- **EP 的 el-scrollbar 滚动条默认 hover 才显示**（v-show 的 display:none）——要常显必须 `display:block !important`，只覆盖 opacity 无效；thumb 宽度由 EP 在 resize/scroll 时计算，改容器宽度后要触发 window resize 才会更新。
- **BatchView 的控件类型函数是 `cellType`，SingleView 的是 `controlType`**——同名不同文件，混用会运行时白屏（踩过：统一设置弹窗空白）。
- 读 el-table 样式别读根元素的 borderColor——未设置的边 fallback 到 currentColor，会误判成深色；要看 td/th 具体边的 style+width+color。
- label 里包 el-button **不会**触发关联 file input（交互元素拦截转发），要用 `input.click()`。

## Git 约定

- 中文提交信息，小步聚焦；前缀风格：`init: 范围`、`feat: …`、`fix: …`、`chore: …`、`docs: …`、`test: …`。
- `.gitattributes` 强制 LF、字体图片标 binary——新加二进制类型记得补。
- `src/calcbook/web` 与 `src/calcbook/vendor` 是**提交入库的构建产物**（使 pip 安装的使用侧无需 Node），改动前端后必须 `npm run build` 再提交。
- 杀本地服务进程按端口找 PID（`netstat -ano | findstr :8317` → `taskkill /F /PID <pid>`），**禁止** `taskkill /IM python.exe`。
