# AGENTS.md

CalcBook——结构构件批量计算书工具。FastAPI 后端 + Vue3 前端，pip 分发，`calcbook serve` 一条命令起本地服务。

## 常用命令

```bash
pip install -e .                      # 可编辑安装（改后端代码即时生效）
python -m pytest tests -q             # 全部测试（37 个：契约/后端/API 三层）
python -m pytest tests/test_server.py::test_run_batch -q   # 单个测试

calcbook serve --templates examples --port 8317 --no-browser   # 起本地服务
calcbook serve --templates <目录>      # 生产形态：自动开浏览器，默认端口 8317

cd web
npm install                           # 仅前端开发需要 Node
npm run dev                           # vite:5173，/api 代理到 127.0.0.1:8317
npm run build                         # 构建到 src/calcbook/web/ 并拷贝 vendor-katex
```

- **打包验证**：`pip wheel --no-deps -w _wheelcheck .`（wheel 应 ~2.4 MB，含 `src/calcbook/web` 与 `src/calcbook/vendor`，用完删 `_wheelcheck/`）。
- 服务端 Python 代码改动需重启服务；`src/calcbook/web`、`src/calcbook/vendor` 由构建产出，**不要手改**。
- 打包配置在 `pyproject.toml`（package-data 含 web/vendor）+ `MANIFEST.in`，两者要同步维护。

## 架构（数据流）

```
模板文件（examples/gl.py）
  → loader.py    目录扫描，importlib 导入（报错隔离到 errors，不打断其他文件），
                 收集 __calcbook_template__ 标记，填 template_id = "文件名.函数名"，算 sha256
  → engine.py    run_template(meta, params_dict)：校验（pydantic）→ 执行 → 永不抛异常，
                 失败时 traceback 原样进 RunResult.error（这是模板作者的调试界面）
  → calcbook.py  CalcBook Builder：formula/subs/check/cite/image/table → Markdown+LaTeX；
                 check() 一等公民：正文判定行 + 末尾自动「验算结论汇总」表 + max_ratio
  → server.py    FastAPI：/api/templates、/api/run(-batch)、/api/project、/api/hash-check、
                 /api/render、/api/export/html；静态托管 src/calcbook/web
  → web/ (Vue3)  store.js 单一状态源；参数变更防抖 300ms 自动重算；工程 800ms 防抖回写服务端
                 （刷新页面不丢）；导出走 api.exportHtml，勾选离线版则 inline_assets=true
  → project.py   .cbproj 纯 JSON：items[{id,name,template_id,template_hash,params,deps}] + views
```

## 关键设计决定（改代码前先读 `计算书工具文档.md`）

- **契约是产品核心**：模板作者只 import `CalcBook / Field / template` 三个名字（`src/calcbook/__init__.py`）。参数声明的 `label/unit/choices/group` 同时驱动前端表单、批量表格列、.cbproj 三处——改契约要三处一起考虑。
- **模板内部统一 SI 基本单位**，`Field(unit=...)` 只管展示换算；不做自动单位引擎。
- **统一设置是批量赋值操作**：每行 params 始终存完整值，无隐藏状态。
- **hash 只覆盖模板主文件**，`deps` 字段为依赖模块（如 Hsteel.py）预留。
- **离线导出只内联 woff2**：woff/ttf 加上会到 1.73 MB，不划算；vendor 目录只备 css+2js+20 个 woff2。
- **导出页模板用 `@@MARKER@@` 占位 + `str.replace`**，不能用 `str.format`（CSS 花括号冲突）。md→HTML 渲染必须**先剥前缀再 html.escape**（回归教训：`> 依据` 变 `t; 依据`），粗体 `**…**` 在 `_inline()` 处理。

## 前端易错点（都踩过）

- **store 里往 items 塞对象后必须返回数组里的元素**（`store.project.items[len-1]`）——push 进 reactive 数组的原始对象赋值会绕过代理、界面不刷新（数据对、显示错，极难排查）。
- `web/src/main.js` 用独立导出的 `init()`，不是 `store.init()`。
- 刷新/切模板后对无缓存结果的项要 `scheduleRun` 补算，否则导出报「没有可导出的结果」。
- Element Plus 2.9 的 el-select 选中值不在 `input.value` 里，读 DOM 验证用 `.el-select__wrapper` 的 textContent。
- label 里包 el-button **不会**触发关联 file input（交互元素拦截转发），要用 `input.click()`。

## Git 约定

- 中文提交信息，小步聚焦；前缀风格：`init: 范围`、`feat: …`、`fix: …`、`chore: …`、`docs: …`、`test: …`。
- `.gitattributes` 强制 LF、字体图片标 binary——新加二进制类型记得补。
- `src/calcbook/web` 与 `src/calcbook/vendor` 是**提交入库的构建产物**（使 pip 安装的使用侧无需 Node），改动前端后必须 `npm run build` 再提交。
- 杀本地服务进程按端口找 PID（`netstat -ano | findstr :8317` → `taskkill /F /PID <pid>`），**禁止** `taskkill /IM python.exe`。
