# CalcBook 模板 API 速查（自包含版）

> 写给模板作者：会 Python 的结构工程师。一个模板 = 一个 `.py` 文件。
>
> 本文件是 `docs/模板开发指南.md` 的精简自包含版本，**脱离 CalcBook 项目也能用**。
> 完整版（包含项目内的额外说明）见 CalcBook 仓库 `docs/模板开发指南.md`；
> 两者若有出入以本文件为准（Pack 一年一校，与官方同步）。

## 0. 模板作者契约

模板作者只 import **三个名字**：

```python
from calcbook import CalcBook, Field, template
```

**（可选）模块级声明第三方依赖**：模板用了 matplotlib 等不在
calcbook 基础依赖里的库时，在文件顶部写：

```python
__calcbook_requires__ = ["matplotlib"]   # import 名列表
```

不声明也能跑，但用户机器缺库时只看到一屏 traceback；声明后界面提示
「缺少依赖 + 安装指引」，离线发布包启动器启动时还会自动安装。

你只负责两件事，其余 CalcBook 全管：

| 你写 | CalcBook 自动做 |
|---|---|
| **参数声明**（Pydantic + `Field`） | 生成参数表单、批量表格的列、工程文件的参数 JSON |
| **计算 + `CalcBook` 写书** | KaTeX 实时预览、批量重算、应力比列、HTML 导出 |

不写一行界面代码，不碰 HTML，不排版。

## 1. 最小模板

```python
# gl.py —— 钢梁强度验算
from pydantic import BaseModel
from calcbook import CalcBook, Field, template


class GLParams(BaseModel):
    steel: str = Field("Q235B", label="钢材牌号",
                       choices=["Q235B", "Q355B"], group="材料")
    fy: float = Field(215, label="抗弯强度设计值", unit="N/mm²",
                      group="材料", gt=0)
    gamma_x: float = Field(1.05, label="截面塑性发展系数",
                           group="截面", ge=1.0, le=1.25)
    Wx: float = Field(1.0e6, label="截面模量", unit="mm³",
                      group="截面", gt=0)
    Mx: float = Field(100, label="弯矩设计值", unit="kN·m", group="荷载")


@template("钢梁强度验算", description="GB 50017-2017 弯曲正应力验算")
def calc(p: GLParams) -> CalcBook:
    b = CalcBook(title="钢梁强度验算")
    sigma = p.Mx * 1e6 / (p.gamma_x * p.Wx)        # kN·m → N·mm

    b.h2("1. 强度验算")
    b.formula(r"\sigma = \dfrac{M_x}{\gamma_x W_x} \le f",
              cite=("GB 50017-2017", "4.1.1"))
    b.subs(rf"\sigma = \dfrac{{{p.Mx:g} \times 10^6}}"
           rf"{{{p.gamma_x:.2f} \times {p.Wx:,.0f}}}"
           rf"= {sigma:.1f}\ \mathrm{{N/mm^2}}")
    b.check("抗弯强度", value=sigma, limit=p.fy, unit="N/mm²",
            expr=r"\sigma \le f", cite=("GB 50017-2017", "4.1.1"))
    return b                                        # 必须返回 CalcBook
```

保存后界面点「刷新模板」即生效，无需重启服务。

## 2. 参数声明

### 2.1 类型 → 界面控件

| 注解类型 | 表单控件 | 批量表格控件 |
|---|---|---|
| `float` / `int` | 数字输入框 | 数字输入框（可被 Excel 粘贴填充） |
| `str` + `choices` | 下拉框 | 下拉框 |
| `str`（无 choices） | 文本框 | 文本框 |
| `bool` | 开关 | 开关 |
| 其他（`list`、`dict`…） | 文本框（JSON 串） | 同左——**不建议用** |

### 2.2 `Field` 参数

```python
Field(默认值,
      label="中文名",          # 界面显示；缺省显示字段名
      unit="N/mm²",            # 单位，仅展示用（见 §6 单位纪律）
      choices=["Q235B", ...],  # 下拉选项
      group="材料",            # 表单折叠分组；批量模式下成为「统一设置」的颗粒
      batch_hidden=True,       # 批量表格默认不显示该列（使用者在列显隐里可勾回）
      ge=0, gt=0, le=1.25,     # 透传 pydantic 校验
      description="补充说明",   # 透传 pydantic
      )
```

### 2.3 `group` 与批量模式

- `group` 相同的参数（如「材料」组）在批量视图顶部可整组「统一设置」：改一处 → 应用到全部行；
- 每行不同取值的参数（如弯矩、截面）单独一组或用默认组；
- **约定**：
  - 「材料/系数/参数」整组可统一 → 用一个 `group` 名（如「材料」「荷载与系数」）
  - 「几何/构件尺寸」每行不同 → 单独 `group`（如「几何」）
- 参考 `assets/example-steel-beam.py` 里的 group 划分。

### 2.4 校验失败会怎样

界面该输入框标红，预览区显示「参数校验失败 + 原因」——不会静默算错。
所以**把限值写进声明**（`gt=0`、`le=1.25`）是免费的正确性保险。

## 3. `CalcBook` API

链式调用：每个方法返回 `self`。渲染目标：**HTML**（`$$…$$` 独立公式与 `$…$` 行内公式交给前端 KaTeX；Markdown 为纯导出物，不参与渲染）。

### 内容语法契约（只有两条，见模板开发指南 §3.1 完整版）

- `**粗体**` 与行内公式 `$…$` 在标题 / 段落 / 表格单元格 / 图名中生效；
- **结构只由 API 决定**：文本写得像 md（`##`、`>`、`-`、HTML 标签）一律字面显示，转义自动完成；无法字面输出成对 `**` 与 `$…$`。

| 方法 | 用途 | 渲染效果 |
|---|---|---|
| `h1/h2/h3(text)` | 标题（编号自己写，如 `"1. 强度验算"`） | `# / ## / ###` |
| `p(text)` | 文字段落，支持行内 `$…$` | 段落 |
| `formula(latex, cite=None)` | **符号公式**（独立公式块） | `$$…$$` + 依据标注行 |
| `subs(latex, cite=None)` | **代入数值**（跟在 formula 后） | 独立公式块 |
| `check(…)` | 验算项（见 §4） | 判定行 + 自动汇总表 |
| `table(header, rows)` | 自由表格 | md 表格 |
| `image_bytes(data, mime, caption)` | **内嵌图片**（推荐，见 §5） | 居中图片 + 居中图名（小字） |
| `image(path, caption)` | URL 图片（导出离线文件时相对路径会裂图，**慎用**） | 同上 |
| `metric(name, value)` | 批量表格附加指标（不进正文，见 §4 末） | 无（仅进批量结果列） |

`cite=("GB 50017-2017", "4.1.1")` 渲染为公式下方的引用块「依据：GB 50017-2017 第 4.1.1 条」。

**书写惯例**（结构计算书的标准姿势，界面预览按此渲染）：

```python
b.formula(r"\sigma = \dfrac{M_x}{\gamma_x W_x} \le f")   # ① 符号公式
b.subs(rf"\sigma = \dfrac{{{v}}}{{…}} = {sigma:.1f}\ \mathrm{{N/mm^2}}")  # ② 代入
b.check("抗弯强度", value=sigma, limit=p.fy, …)           # ③ 判定
```

计算深度不设限：想写多细写多细（`p()` 补文字说明、`table()` 列中间量），但每个模板自己保持风格一致。

### 属性

| 属性 | 类型 | 含义 |
|---|---|---|
| `b.checks` | `list[dict]` | 所有 check 项（调试用） |
| `b.max_ratio` | `float \| None` | 最大应力比（无 check 时为 `None`） |
| `b.all_ok` | `bool` | 所有 check 是否满足（无 check 时为 `False`） |

## 4. `check` 与结论

```python
b.check(name="抗弯强度",
        value=sigma, limit=p.fy,        # 数值 vs 限值
        op="le",                        # "le"=value≤limit 为满足（默认）；"ge"=value≥limit
        expr=r"\sigma \le f",           # 可选：符号表达式，显示在判定行
        unit="N/mm²",                   # 展示单位
        cite=("GB 50017-2017", "4.1.1"),
        ratio=None)                     # 应力比；缺省 le→value/limit、ge→limit/value
```

`check()` 自动完成三件事：

1. **正文判定行**：`抗弯强度：σ≤f：95.24 ≤ 215 N/mm²，应力比 0.443 —— **满足**`（不满足加粗）；
2. **计算书末尾自动汇总「验算结论」表**（验算项/数值/应力比/结论；有 `cite` 时才附「依据」列）；
3. **批量表格每行显示最大应力比**（`max_ratio`，超限红色）——这是使用者筛选危险构件的依据，所以**每个模板都应至少有一个 check**。

代码里也可读：`b.checks`、`b.max_ratio`、`b.all_ok`。

**批量结果列（`metric()`）**：`b.metric("A端支座配筋", "Φ8@200")` 声明结果指标，
不进正文，随 `RunResult.metrics` 送到前端；批量视图为出现过的指标名动态增加
结果列（按首次出现顺序，全行共用一列）。适合输出选筋结果、关键截面内力等
使用者要扫一眼对比的量。

## 5. 插图：matplotlib 截面简图

用 `image_bytes()` 内嵌（base64 data URI），预览、导出、离线全可用：

```python
import io
import matplotlib
matplotlib.use("Agg")                       # 服务端无界面，必须加
import matplotlib.pyplot as plt

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False   # 负号显示


def section_fig(width_mm: float, height_mm: float) -> bytes:
    fig, ax = plt.subplots(figsize=(3, 4))
    # ... 按参数画截面 / 计算简图 ...
    ax.set_xlim(0, width_mm)
    ax.set_ylim(0, height_mm)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


b.image_bytes(section_fig(p.Wx, 100), caption="截面简图")
```

> ⚠️ **用了 matplotlib（或任何第三方库），必须在文件顶部声明依赖**
> （模块级，import 名）：
>
> ```python
> __calcbook_requires__ = ["matplotlib"]
> ```
>
> 未声明：用户机器缺库 → 运行报一屏 traceback；声明后：界面明确提示
> 「缺少依赖 + 安装指引」，离线发布包启动器启动时自动安装到包内 venv。

> **不要用 `image(path)`**：相对路径在离线导出 HTML 时会裂图。

## 6. 单位纪律（强制约定）

- 模板内部**统一 SI 基本单位**：N、mm、MPa；`kN·m` 在算式处显式换算（`× 1e6` → N·mm）；
- `Field(unit=...)` 只负责界面展示，**不参与换算**；
- 不做自动单位引擎——单位错误靠「声明里的 `unit` 标注 + 算式处显式换算」双保险。

## 7. 数字进公式的格式

公式里直接拼数字容易出丑，推荐：

```python
rf"\sigma = \dfrac{{{p.Mx:g} \times 10^6}}{{…}}"     # :g 避免 100000000.0
rf"{{{p.Wx:,.0f}}}"                                   # 千分位只在表格/文字里用
rf"{sigma:.1f}\ \mathrm{{N/mm^2}}"                    # 单位用 \mathrm{}，别用文字
```

- f-string 里 LaTeX 的 `{}` 要写成 `{{}}`，建议统一用 `rf""` 前缀；
- LaTeX 公式内**不要放千分位逗号**（会被当成间距），用 `\times 10^{n}`；
- `.4g` 左右的有效位数适合展示（CalcBook 结论表默认就是这个量级）。

## 8. 共享数据模块与重计算

- **共享数据表**：同目录的普通 `.py` 直接 `import`：`Hsteel.py` 放国标 H 型钢规格表，`gl.py` 里 `import Hsteel`；
- 目录就是一个 git 仓库——数据表、模板都能版本管理、同事拉取即得；
- 计算随便写：循环试算、迭代收敛都行。**计算量大的模板加 `manual=True`**，界面就不自动实时算，改用「全部重算」按钮：

```python
@template("整体稳定验算（迭代）", description="…", manual=True)
def calc(p: P) -> CalcBook: ...
```

**可选的 `name` 形参**：模板函数声明 `def calc(p: P, *, name: str = "")` 时，
计算项的「名称」（批量首列/单项标题）会传入，用作计算书里的项目编号，
不用再重复声明编号参数：

```python
@template("板式楼梯计算")
def calc(p: P, *, name: str = "") -> CalcBook:
    b = CalcBook(title=f"楼梯计算书 · {name or '未命名'}")
    ...
```

## 9. 调试与发布

| 场景 | 行为 |
|---|---|
| 改了模板代码 | 界面点「刷新模板」，立即生效，**不用重启服务** |
| 计算抛异常 | 预览区原样显示 **Python traceback**——这就是你的调试界面 |
| 参数非法 | 该行标红 + 校验原因 |
| 忘了 `return b` | 明确报「模板返回值类型错误」，指出实际返回的类型 |
| 模板文件写坏（语法错） | 只这一个文件报错，其他模板不受影响 |
| 改动已保存工程的模板 | 使用者界面出现「模板已改」标记，提示旧结果可能过期 |

**命名与版本建议**：

- 文件名即模板 id 的一部分（`gl.py` → `gl.calc`），**发布后不要改文件名**——工程文件按 id 引用，改名会让旧工程找不到模板；
- 用 git 管模板目录；改动后旧工程的「模板已改」提示是按文件 sha256 比对的；
- 一个模板只做一类验算（宁多勿杂），参数控制在十几项以内。

## 10. 契约速查

```python
# ---------- 导入 ----------
from calcbook import CalcBook, Field, template

# ---------- 可选：第三方库依赖声明 ----------
__calcbook_requires__ = ["matplotlib"]   # import 名；缺了会提示/自动装

# ---------- 声明 ----------
@template(name: str, description: str = "", manual: bool = False)
def calc(p: <PydanticModel>) -> CalcBook: ...
# 或：
def calc(p: <PydanticModel>, *, name: str = "") -> CalcBook: ...

Field(default,
      label=, unit=, choices=, group=, batch_hidden=True,
      **pydantic 参数如 gt / ge / le / description)

# ---------- CalcBook 方法 ----------
h1 / h2 / h3(text)                              # 标题
p(text)                                          # 段落
formula(latex, cite=None)                        # 符号公式
subs(latex, cite=None)                           # 代入数值
check(name, value, limit,
      op="le" | "ge",                            # 默认 "le"
      expr=None, unit=None, cite=None, ratio=None)
table(header: list[str], rows: list[list])       # 自由表格
image_bytes(data: bytes, mime="image/png", caption="")
image(path, caption="")                          # 不推荐
metric(name: str, value)                         # 批量附加指标列（不进正文）

# ---------- 属性 ----------
b.checks: list[dict]                             # 所有 check 项
b.max_ratio: float | None                        # 最大应力比
b.all_ok: bool                                   # 全部满足？
```
