---
name: pb-template
description: >
  引导用户写 Probatrix 计算书模板（.py 文件）。适用于：用户要给 Probatrix 加新模板、
  写构件验算脚本、把 Excel 手算/手稿移植到 Probatrix、问"怎么写模板"或"加个XX计算"。
  流程：grill 需求（验算类型/规范/参数/check 清单/批量场景/命名三件套）→
  查规范资料（deep-research 查条文 + 读本 skill 的 references/api.md）→
  写模板（@template 装饰器 + Pydantic 参数 + Probatrix Builder，参考 assets/）→
  测试（按 references/test-patterns.md 跑契约测试 + 起 probatrix serve 冒烟）。
  不用于改 Probatrix 本体代码（那是普通读源码任务）。
---

# pb-template — 写 Probatrix 计算书模板

让「写一个 pb_template」这件事变得可预测：不会忘 `return b`、不会搞错单位、
不会漏规范引用、不会在错误目录建文件、写完能立刻在界面里跑起来。

**本 skill 自包含**，所有 API、测试模式、反模式都在 `references/` 和 `assets/`
里。**不依赖 Probatrix 项目目录是否在**——但如果项目就在手边，可以参考
项目内的 `docs/模板开发指南.md`（与 `references/api.md` 同步校准）。

---

## 自包含资源（脱离项目也能用）

| 资源 | 用途 | 何时读 |
|---|---|---|
| `references/api.md` | **完整 API 速查**（Field / Probatrix / @template / 单位纪律 / 数字格式） | 阶段 3 写代码时随时查 |
| `references/anti-patterns.md` | 12 条反模式 + 写完模板的自检清单 | 阶段 3 写完跑一遍勾选 |
| `references/test-patterns.md` | 两层测试：pytest 契约 + 起服务 curl 冒烟 | 阶段 4 |
| `assets/skeleton.py` | 空白骨架（带 TODO 注释） | 阶段 3 起点 |
| `assets/example-steel-beam.py` | **完整可运行示例**（钢梁，含 `if __name__` 自检） | 阶段 3 写之前先跑通确认环境 |
| `scripts/img2b64.py` | 图片 → base64 内嵌片段，可顺带裁剪/压缩（`--crop/--max-px/--to`） | 用户给了图片要嵌进模板时 |

---

## 模板作者契约（一句话）

模板作者**只 import 三个名字**（`from probatrix import Probatrix, Field, template`），
**只写两件事**（参数声明 + 计算+写书）。其他全部由 Probatrix 接管——
自动生成表单、批量表格列、参数 JSON、KaTeX 预览、HTML 导出。

**用了第三方库的模板**（如 matplotlib）另加一行模块级声明
`__probatrix_requires__ = ["matplotlib"]`（见阶段 1.5）——否则用户机器
缺库时只能看到一屏 traceback。

API 细节一律查 `references/api.md`，不在此重复。

---

## 阶段 1 — Grill 用户需求（用 grill-me 技能）

加载 `grill-me` 技能后，按以下清单**逐条**问（每题给推荐答案），
先问前置决策，后问细节。**不一次问完所有问题**。

### 1.1 验算对象与规范
- 计算什么？（钢梁/钢柱/雨棚/楼梯/混凝土梁/桩/…）
- 用哪本规范的哪个版本？（GB 50017-2017、GB 50010-2010(2024年版)、GB 50007-2011、JGJ 99-2015…）
- 是单项验算（一段公式一条结论）还是包含多个验算项的完整计算书？

### 1.2 参数清单
让用户列出所有需要的输入参数。每条确认：
- 类型（float / int / str / bool）
- 中文 label、单位、默认值、合理范围（`gt/ge/le`）
- 归属哪个 group（决定批量模式下的「统一设置」颗粒）
- 是否是「每行都不同」的几何/荷载参数（→ 各跑各填）vs「整组统一」的材料/系数（→ 可整组赋值）
- 是否默认隐藏在批量表格里（`batch_hidden=True`，让使用者在列显隐里勾回）

### 1.3 验算项清单
- 要做哪些 check？每个 check 的「value/limit/op/cite/expr/unit」是什么？
- 比值定义（le→value/limit，ge→limit/value；特殊项可显式给 `ratio=`）
- 哪些 check 是「不满足即整本作废」的硬控项，哪些是「参考性」验算？

### 1.4 批量场景
- 这个模板会不会用在批量视图（一行一个构件）？哪些列最常用？
- 是否需要每行独立的「名称/编号」传入？→ 用 `def calc(p, *, name: str = "")` 接住
- 计算量是否大到需要 `manual=True`（不自动实时算）？

### 1.5 插图与可视化
- 是否需要 matplotlib 截面图/计算简图？→ 用 `image_bytes` 内嵌（不要用 `image` 路径，导出离线版会裂图）
- 是否要嵌**静态图片**（扫描件/节点大样图等现成图片文件）？→ 用 `scripts/img2b64.py` 转成片段粘进模板
  （`base64.b64decode(...)` + `b.image_bytes(...)`，保持「一个模板一个 .py」；大图加 `--max-px 1200 --to jpg`
  先压缩，还可 `--crop` 裁边）
- 字体注意：`Microsoft YaHei / SimHei`（中文标签）+ `axes.unicode_minus = False`（负号）
- **用 matplotlib 的模板，必须在文件顶部声明依赖**（模块级）：
  `__probatrix_requires__ = ["matplotlib"]`，让界面提前提示缺失的库。
  便携包预装 matplotlib，额外依赖由用户通过包内 Python 安装。

### 1.6 命名三件套（影响 `template_id` 与工程文件兼容性）
- **文件名** `xxx.py` → 模板 id 前缀（**一旦发布不要改**，旧工程按 id 找不到）
- `@template("显示名", description="…")` → 界面下拉里的项
- `Probatrix(title="…")` → 计算书标题（可拼接 `f"{name or '未命名'}"` 做批量编号）

### 1.7 测试就绪性
- 用户能否给一组**合法**参数和一组**越界**参数用作冒烟测试？
- 比值期望值用户能口算或笔算一个出来吗？（不要求，估算也行）

**完成判据**：上面 7 项每项都有明确答案（含「不适用」也是答案），不是模糊描述。模板文件名已确定。

---

## 阶段 2 — 查规范资料（deep-research + 读已有模板）

并行做三件事：

### 2.1 读 skill 自带的 API 速查
**主源**：`references/api.md`（**自包含的完整 API**，与 Probatrix 项目 `docs/模板开发指南.md` 同步）。
**如果 Probatrix 项目在手边**：
- `docs/模板开发指南.md` —— 完整版（含项目内说明）
- `examples/gl.py` —— 最小示例
- `examples/stair.py` —— 复杂示例（图+选筋+多 check+复杂表格）

### 2.2 查规范条文
调 `deep-research` 技能，搜索用户提到的规范版本（注意条文编号可能因版本不同而变）：
- 搜索关键词样例：「GB 50017-2017 4.1.1 抗弯强度 比值」「GB 50010 最小配筋率 0.2% 受弯构件」
- 拿到：**条文原文 + 条文号 + 公式形式 + 适用条件 + 比值定义**
- 引用格式：`cite=("GB 50017-2017", "4.1.1")` —— 元组自动渲染为「依据：GB 50017-2017 第 4.1.1 条」

### 2.3 跑通示例确认环境
```bash
python -m pip install .        # 在 Probatrix 仓库根目录装包（pydantic 随包依赖）
python assets/example-steel-beam.py
```
应输出 `max_ratio = 0.4430`、`all_ok = True`、写入 `example-steel-beam_output.md`。
**跑不通 = 环境没装好，先修**（别在错的环境上写代码）。

### 2.4 查同类模板（避免重复造轮子）
**如果 Probatrix 项目在手边**：`ls <模板目录>`（默认 `examples/`）找现有模板。
已经有同类（钢梁/楼梯/雨棚/混凝土梁…）时：
- **优先在已有模板上扩展**，不要新开文件
- 必须新开时，文件名要能区分（如 `gl_welded.py` 对接焊缝验算 vs `gl.py` 抗弯验算）

**完成判据**：每个 check 都有「值/限值/规范来源」三件套；引用的条文号在 `deep-research` 结果中得到确认；示例可跑通；决定文件路径（新建 / 扩展 / 复用）。

---

## 阶段 3 — 写模板

### 3.1 起点
从 `assets/skeleton.py` 复制，按 TODO 填实。

### 3.2 写法纪律（每写一行自检）
细节查 `references/api.md`，要点速记：
- **单位**：模板内部统一 SI 基本单位（N、mm、MPa、kN·m），换算写在算式旁（`p.Mx * 1e6`）；`Field(unit=...)` 只展示
- **f-string + LaTeX**：用 `rf""`，LaTeX 的 `{}` 转义为 `{{}}`；公式内**不放千分位逗号**（被当间距）
- **数字格式**：`:g` 避免 `100000000.0`；`:.1f` 给应力；`{{:,}}` 仅用于表格/文字
- **必写项**：`return b`、每个模板至少一个 `check`（否则 `b.max_ratio` 为 `None`、批量视图无比值列）
- **顺序**：代入过程用 `derive()` 推导链——**分段即换行，布局规则见
  api.md「推导链排版规则」**（三种布局、100 字符判据、说明放行尾）；
  `formula + subs` 旧写法仍支持；`check` 紧跟推导之后（界面预览按此节奏）
- **字符串字面量**：不要用 `str.format`（CSS 花括号会冲突；导出模板的工程文件也走 `str.replace`）
- **第三方依赖**：用了 matplotlib 等不在 probatrix 基础依赖里的库 → 文件顶部声明
  `__probatrix_requires__ = ["matplotlib"]`（导入名列表）。缺库时界面提示安装方法。
- **group 设计**：材料/系数整组统一，几何/荷载每行填——参考 `assets/example-steel-beam.py` 的 group 划分

### 3.3 完整反模式清单
写完后**逐条勾选** `references/anti-patterns.md` 末尾的 12 条自检清单。
12 条里**任意一条不通过**就别进入阶段 4。

### 3.4 必做收尾
- 把文件落到约定目录（Probatrix 项目默认 `examples/xxx.py`；独立项目自己定）
- 第一行写带规范的 docstring（`@template` 的 description 在界面下拉里会显示）
- 不要建 `__init__.py`（loader 用 importlib，不走包导入）
- 文件名小写英文 + 下划线（`gl.py`、`stair.py`、`hcolumn.py`）
- 用了第三方库（matplotlib 等）→ 顶部声明 `__probatrix_requires__`（见 1.5）

**完成判据**：文件已落盘；`assets/example-steel-beam.py` 跑得通；新模板也能在自己设计的合法参数下跑通（自己脑内或笔算一组参数验证）。

---

## 阶段 4 — 测试

按 `references/test-patterns.md` 的两层测试顺序执行，每步独立可验证。

### 4.1 单元：写一个契约测试
照 `references/test-patterns.md` §1 的模板写 `test_xxx.py`，断言至少：
- `make_params({})` 用默认值能跑通，`b.all_ok is True`
- 给一份越界参数，`b.all_ok is False` 且 `max_ratio` 符合预期（手算或粗估）
- `to_markdown()` 包含「# <title>」「## 1. ...」「比值」「**满足/不满足**」「| 验算项」
- **每个 check 都有 cite**（漏 cite 是反模式 §9，结论表不出「依据」列）

### 4.2 跑测试
```bash
# 在 Probatrix 项目根目录
python -m pytest tests -q
# 期望：原有测试 + 你的 1 个全绿

# 独立环境（无 pytest）
python smoke.py                                # 见 references/test-patterns.md §4
```

任何红先修，不准带病过阶段 4。

### 4.3 端到端冒烟（curl 验真）
另开终端：
```bash
probatrix serve --templates <你的模板目录> --port 8317 --no-browser
```
等出现「Uvicorn running on http://127.0.0.1:8317」。

按 `references/test-patterns.md` §2.2 的三个 curl：
1. `GET /api/templates` 确认出现新模板
2. `POST /api/run` 用默认参数 → `error=""` + `all_ok=true`
3. `POST /api/run` 用越界参数 → `all_ok=false` + `max_ratio > 1.0`

冒烟后**关掉服务**（按端口找 PID，`taskkill /F /PID <pid>`，**不要** `taskkill /IM python.exe`）。

### 4.4 报错可见性自检（可选但推荐）
临时把公式改坏 → 重跑 4.3 第 2 步 → 确认 `result.error` 含 Python traceback。
改回后必须再跑一遍 4.3 确认恢复。

**完成判据**：
- [ ] `pytest tests -q` 全绿（或 `smoke.py` 通过）
- [ ] `/api/templates` 列出新模板
- [ ] `/api/run` 默认参数通过、越界参数不通过
- [ ] 临时改坏 → 恢复后再跑 4.3 仍绿
- [ ] `references/anti-patterns.md` 末尾 12 条全勾

---

## 完成路径

1. 在 Probatrix 仓库根目录 `python -m pip install .` 装好环境
2. `python assets/example-steel-beam.py` 跑通示例
3. 阶段 1: grill 需求
4. 阶段 2: deep-research 查规范
5. 阶段 3: 复制 `assets/skeleton.py` 填实，落盘
6. `references/anti-patterns.md` 末尾 12 条自检
7. 阶段 4: 写测试 + pytest + 起服务冒烟
8. 全绿后告诉用户：改了模板后界面点「刷新模板」立即生效，**不用重启服务**；用 git 管模板目录

---

## 与 Probatrix 项目的桥梁（项目在手边时）

| 用途 | 路径 |
|---|---|
| 完整开发指南（项目内，与 `references/api.md` 同步） | `docs/模板开发指南.md` |
| 最小示例（项目内） | `examples/gl.py` |
| 复杂示例（图+选筋+多 check） | `examples/stair.py` |
| 契约测试模式 | `tests/test_contract.py`（末尾 `test_example_gl_end_to_end`） |
| 端到端服务入口 | `src/probatrix/server.py` |
| 模板加载器 | `src/probatrix/loader.py`（看 hash 计算、扫描逻辑） |
| 模板目录约定 | 默认 `examples/`，启动时 `--templates` 指定 |

**同步说明**：`references/api.md` 是本 skill 的自包含版本，与项目 `docs/模板开发指南.md`
应保持一致。**当 Probatrix 项目更新了 API 时，记得同步 `references/api.md`**（建议每
半年或发版时校准一次）。
