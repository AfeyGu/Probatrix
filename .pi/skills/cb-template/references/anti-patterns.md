# 反模式：CalcBook 模板常见错误

写代码时**逐条自检**，看到立刻改。每条都给出「为什么错」和正确做法，
可以独立使用，不需要先看其他文件。

---

## 1. 忘 `return b`

```python
# ❌ 错
@template("钢梁")
def calc(p: GLParams):
    b = CalcBook(...)
    b.check(...)
    # 忘了 return

# ✅ 对
@template("钢梁")
def calc(p: GLParams) -> CalcBook:
    b = CalcBook(...)
    b.check(...)
    return b
```

**为什么错**：引擎检测到返回值不是 `CalcBook` 类型就报「模板返回值类型错误」——但报的是类型名（如 `<class 'NoneType'>`），不看全文很难发现是漏了 `return`。

---

## 2. LaTeX 公式内放千分位逗号

```python
# ❌ 错
rf"\sigma = \dfrac{{215,000,000}}{{...}}"

# ✅ 对
rf"\sigma = \dfrac{{2.15 \times 10^{8}}}"          # 用科学计数法
# 或：
rf"\sigma = \dfrac{{2.15e8}}"                       # 简短写法
```

**为什么错**：LaTeX 把 `,` 当成数学间距字符，渲染出来数字间会多出一截空隙，破坏公式可读性。

**例外**：千分位**只在文字/表格里**用（`f"{p.Wx:,.0f}"`），不进公式。

---

## 3. 用 `str.format` 拼 md / HTML

```python
# ❌ 错
md = """
<style>
  body {{ color: red; }}      {# format 把 {color: red} 也吃了 #}
</style>
""".format()

# ✅ 对
md = f"""
<style>
  body {{ color: red; }}
</style>
"""
```

**为什么错**：`str.format` 走 `{}` 占位，CSS / JS / LaTeX 里大量 `{}` 会被吃掉或报错。**全用 f-string**（`rf""` 统一前缀）。

---

## 4. 用 `image(path)` 引用磁盘文件

```python
# ❌ 错
b.image("./section.png", caption="截面图")

# ✅ 对
import io, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def make_png():
    fig, ax = plt.subplots()
    # ...
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()

b.image_bytes(make_png(), caption="截面图")
```

**为什么错**：相对路径依赖当前工作目录，且离线导出 HTML 时图片不会被打包，
预览能看到但发出去的文件裂图。`image_bytes` 把 PNG 内联成 base64 data URI，
导出离线版时也保留。

> 用 matplotlib 的模板，别忘了文件顶部声明依赖：
> `__calcbook_requires__ = ["matplotlib"]`（见 `api.md` §5）。

---

## 5. 限值硬编在 calc 函数里

```python
# ❌ 错
@template("钢梁")
def calc(p: GLParams) -> CalcBook:
    if p.Mx > 200:                         # 硬编 200 这个限值
        ...
    b.check("抗弯强度", value=sigma, limit=215, ...)   # 硬编 215

# ✅ 对
class GLParams(BaseModel):
    Mx: float = Field(100, ..., lt=300)             # 声明里写 lt=300
    fy: float = Field(215, ..., gt=0)               # 声明里写 gt=0

@template("钢梁")
def calc(p: GLParams) -> CalcBook:
    b.check("抗弯强度", value=sigma, limit=p.fy, ...)  # 从 p 读
```

**为什么错**：硬编限值意味着：
- pydantic 不知道边界，输入框不会标红
- 改规范时要在代码里找
- 批量模式下不同行不能换限值

把限值写进 `Field(gt=, ge=, lt=, le=)` 声明，是免费的正确性保险 + UI 提示。

---

## 6. 中文 / 带空格 / 大写文件名

```python
# ❌ 错
templates/钢梁.py
templates/Steel Beam.py
templates/GL.py

# ✅ 对
templates/gl.py
templates/stair.py
templates/hcolumn.py
```

**为什么错**：
- 模板 id 是 `文件名.函数名`（`gl.py` → `gl.calc`），中文/空格会让工程文件 JSON 难读；
- 大写在某些文件系统上大小写不敏感（Windows / macOS 默认），git 跨平台协作会出怪事；
- 一旦发布，**永远不要重命名**（旧工程按 id 引用）。

**命名约定**：小写英文 + 下划线，`xxx.py` 表达一个验算类型（不混多种构件）。

---

## 7. 一个模板塞多种构件

```python
# ❌ 错：一个 gl.py 里同时算钢梁、钢柱、支撑
@template("钢构件综合验算", description="梁柱撑都算")
def calc(p: AnyParams) -> CalcBook:
    if p.type == "梁":
        ...
    elif p.type == "柱":
        ...

# ✅ 对：拆三个文件
# gl.py      → 钢梁
# gz.py      → 钢柱
# gsupport.py → 钢支撑
```

**为什么错**：
- 批量视图里不同构件混在一张表，参数含义混淆（梁的 `Mx` vs 柱的 `N` 怎么可能用同一字段？）
- 公式里的 `if/elif` 是模板作者偷懒，使用者看不懂；
- 模板的「参数声明驱动界面」承诺破裂——参数没法按构件类型分组。

**约定**：一个模板只做一类验算；多个验算类型请开多个文件。

---

## 8. 模板里有 `print` 或日志

```python
# ❌ 错
@template("钢梁")
def calc(p: GLParams) -> CalcBook:
    print("debug:", p)                     # 污染 stdout
    import logging
    logging.warning(...)                   # 多进程下日志乱序
    ...

# ✅ 对
@template("钢梁")
def calc(p: GLParams) -> CalcBook:
    # 调试靠 traceback：故意写错，跑到界面看报错，定位完改回
    ...
```

**为什么错**：服务端多进程并发处理批量行时，`print` 输出会乱序污染日志，UI 拿不到但 stderr 也不安静。**调试方式**：故意让公式抛异常 → 预览区显示完整 traceback → 定位后改回。

---

## 9. 漏写 `cite=`

```python
# ❌ 错
b.check("抗弯强度", value=sigma, limit=p.fy, unit="N/mm²",
        expr=r"\sigma \le f")                          # 没 cite

# ✅ 对
b.check("抗弯强度", value=sigma, limit=p.fy, unit="N/mm²",
        expr=r"\sigma \le f", cite=("GB 50017-2017", "4.1.1"))
```

**为什么错**：结论表里没 cite 就不显示「依据」列，使用者不知道结论出处的规范版本，复核人无法快速校核。**每个 check 都应带 cite**。

---

## 10. `formula` 和 `subs` 顺序倒置

```python
# ❌ 错：先代入后给符号公式
b.subs(rf"\sigma = \dfrac{{{p.Mx:g} \times 10^6}}{{...}} = {sigma:.1f}")
b.formula(r"\sigma = \dfrac{M_x}{\gamma_x W_x} \le f")

# ✅ 对：符号 → 代入 → 判定
b.formula(r"\sigma = \dfrac{M_x}{\gamma_x W_x} \le f",
          cite=("GB 50017-2017", "4.1.1"))
b.subs(rf"\sigma = \dfrac{{{p.Mx:g} \times 10^6}}{{...}} = {sigma:.1f}")
b.check("抗弯强度", value=sigma, limit=p.fy, ...)
```

**为什么错**：结构计算书的标准是「先说公式（通用形式），再代值（这一项的数），最后判定」。
顺序倒过来读者要回头找符号定义，不专业。

---

## 11. 模板文件忘记 `from __future__ import annotations`

```python
# ❌ 错（Pydantic 2 没问题但 Pydantic 1 + Python 3.9 会因前向引用报错）
class P(BaseModel):
    child: "OtherModel" = None

# ✅ 对
from __future__ import annotations
class P(BaseModel):
    child: "OtherModel" = None
```

**为什么对**：`from __future__ import annotations` 让所有注解变字符串，延迟求值，避免前向引用问题；同时让 Pydantic v1/v2 行为一致。**统一加，零成本**。

---

## 12. 把 matplotlib 的 plt 设为全局中文

```python
# ❌ 错（在共享脚本里改全局 rcParams）
matplotlib.rcParams["font.sans-serif"] = ["SimHei"]     # 影响所有图

# ✅ 对（每个模板自己设，自己清）
def section_fig(...):
    old = matplotlib.rcParams["font.sans-serif"]
    try:
        matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        fig, ax = plt.subplots(...)
        # ... 画图 ...
        return buf.getvalue()
    finally:
        matplotlib.rcParams["font.sans-serif"] = old
```

**为什么错**：模板目录是 git 仓库，多个模板作者共用，`global rcParams` 会相互污染（一个改了全受影响）。**局部设、try/finally 恢复**。

---

## 自检清单（写完模板跑一遍）

模板写完后过这 12 条：

- [ ] 文件有 `return b`
- [ ] 公式内无千分位逗号
- [ ] 全用 f-string（`rf""`），无 `str.format`
- [ ] 插图用 `image_bytes`（不用 `image(path)`）
- [ ] 限值在 `Field` 声明里（`gt/ge/le`），不在 calc 函数里硬编
- [ ] 文件名小写英文 + 下划线
- [ ] 只做一类验算（不混梁柱撑）
- [ ] 无 `print` / `logging`（调试靠 traceback）
- [ ] 每个 `check` 都有 `cite=`
- [ ] `formula` → `subs` → `check` 顺序
- [ ] 顶部有 `from __future__ import annotations`
- [ ] matplotlib rcParams 局部设置、try/finally 恢复
- [ ] 用了第三方库（matplotlib 等）→ 顶部写了 `__calcbook_requires__` 声明
