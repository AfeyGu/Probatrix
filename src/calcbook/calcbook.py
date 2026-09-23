"""CalcBook：计算书 Builder——模板作者写书、系统渲染的唯一接口。

模板作者用法（不碰 HTML/Markdown 细节）::

    b = CalcBook()
    b.h2("1. 强度验算")
    b.formula(r"\\sigma = \\dfrac{M_x}{\\gamma_x W_x} \\le f",
              cite=("GB 50017-2017", "4.1.1"))       # 符号公式
    b.subs(r"\\sigma = 150.2\\ \\mathrm{N/mm^2}")     # 代入数值
    b.check(name="抗弯强度", value=150.2, limit=215, cite=("GB 50017-2017", "4.1.1"))
    b.image("section.png", caption="截面简图")        # 计算简图/截面图
    return b

约定：
- 渲染目标为 HTML（to_html，预览/导出用）；LaTeX 交给前端 KaTeX；
  Markdown（to_markdown）是纯导出物，供下载阅读，不参与渲染管线；
- 行内格式契约：`**粗体**` 与行内公式 `$...$`，见 docs/模板开发指南.md；
- check() 是一等公民：正文逐项输出判定，末尾自动汇总「验算结论汇总」表；
- 单位纪律：模板内部统一 SI 基本单位，Field(unit=...) 管输入/展示换算。
"""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["CalcBook"]

#: 默认数值格式（比值等），足够展示且不堆小数
_DEFAULT_DIGITS = 4


@dataclass
class _Item:
    kind: str                       # h1/h2/h3/p/formula/subs/check/image/table
    text: str = ""
    cite: tuple[str, str] | None = None
    # check 专用
    name: str = ""
    value: float | None = None
    limit: float | None = None
    op: str = "le"
    ratio: float | None = None
    passed: bool | None = None
    expr: str = ""
    unit: str = ""
    # image 专用
    path: str = ""
    caption: str = ""
    side: str = ""                  # ""（独立居中）| "left" | "right"（浮动环绕）
    # table 专用
    header: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)


class CalcBook:
    """链式 Builder；收集内容块与验算项，渲染为 HTML（LaTeX 交给 KaTeX）。"""

    def __init__(self, title: str | None = None) -> None:
        self.title = title
        self._items: list[_Item] = []
        self.metrics: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 结构与小节
    # ------------------------------------------------------------------
    def h1(self, text: str) -> "CalcBook":
        self._items.append(_Item(kind="h1", text=text))
        return self

    def h2(self, text: str) -> "CalcBook":
        self._items.append(_Item(kind="h2", text=text))
        return self

    def h3(self, text: str) -> "CalcBook":
        self._items.append(_Item(kind="h3", text=text))
        return self

    def p(self, text: str) -> "CalcBook":
        """文字说明段落（支持行内 LaTeX：$...$）。"""
        self._items.append(_Item(kind="p", text=text))
        return self

    # ------------------------------------------------------------------
    # 公式
    # ------------------------------------------------------------------
    def formula(self, latex: str, *, cite: tuple[str, str] | None = None) -> "CalcBook":
        """符号公式（独立成行）。cite=(规范号, 条文号) 渲染为依据标注。"""
        self._items.append(_Item(kind="formula", text=latex, cite=cite))
        return self

    def subs(self, latex: str, *, cite: tuple[str, str] | None = None) -> "CalcBook":
        """代入数值（独立成行），跟在对应 formula 之后。"""
        self._items.append(_Item(kind="subs", text=latex, cite=cite))
        return self

    def derive(self, left: str, *steps: str,
               cite: tuple[str, str] | None = None) -> "CalcBook":
        """推导链（代入过程的**推荐写法**）：一个等式串下来。

        首行「left = 段1」，其后逐行「= 段2」「= 段3」……等号自动对齐；
        段数 = 1 时即单行公式。相比 formula()+subs() 的两段独立公式块，
        推导链展示为连贯的推导过程：

            b.derive(r"\\sigma",
                     r"\\dfrac{M_x}{\\gamma_x W_x} \\le f",
                     rf"\\dfrac{{{p.Mx:g} \\times 10^6}}{{\\gamma_x W_x}}",
                     rf"{sigma:.1f}\\ \\mathrm{{N/mm^2}}",
                     cite=("GB 50017-2017", "4.1.1"))

        显示效果（aligned 等式链）::

            σ = Mx / (γx·Wnx) ≤ f
              = 95.2×10⁶ / (γx·Wnx)
              = 152.3 N/mm²
        """
        if not steps:
            raise ValueError("derive 至少需要一个推导段")
        rows = [rf"{left} &= {steps[0]}"] + [f"&= {s}" for s in steps[1:]]
        body = (r"\begin{aligned}" + "\n"
                + " \\\\\n".join(rows) + "\n" + r"\end{aligned}")
        self._items.append(_Item(kind="formula", text=body, cite=cite))
        return self

    # ------------------------------------------------------------------
    # 插图
    # ------------------------------------------------------------------
    def image(self, path: str, *, caption: str = "",
              side: Literal["left", "right"] | None = None) -> "CalcBook":
        """插入图片（URL 或相对路径；导出为文件时相对路径会失效，慎用）。

        side="left"/"right"：图文环绕——图片浮动到指定一侧（约占 45% 宽），
        其后的文字段落贴边环绕；公式/表格/标题/判定行自动收边回全宽。
        """
        if side not in (None, "left", "right"):
            raise ValueError(f"side 只支持 None/'left'/'right'，收到 {side!r}")
        self._items.append(_Item(kind="image", path=path, caption=caption,
                                 side=side or ""))
        return self

    def image_bytes(self, data: bytes, *, mime: str = "image/png",
                    caption: str = "", side: Literal["left", "right"] | None = None) -> "CalcBook":
        """插入二进制图片（推荐）：转 base64 data URI，预览/导出/离线全可用。

        典型来源：matplotlib 画截面简图/计算简图，savefig 到 BytesIO。
        side 语义同 image()。"""
        b64 = base64.b64encode(data).decode("ascii")
        return self.image(f"data:{mime};base64,{b64}", caption=caption, side=side)

    # ------------------------------------------------------------------
    # 表格（自由内容用；验算结论汇总是自动生成的，不需要模板作者手写）
    # ------------------------------------------------------------------
    def table(self, header: list[str], rows: list[list[Any]]) -> "CalcBook":
        self._items.append(_Item(kind="table", header=header, rows=rows))
        return self

    # ------------------------------------------------------------------
    # 批量表格附加指标：不进正文，随 RunResult 送到前端作动态结果列
    # ------------------------------------------------------------------
    def metric(self, name: str, value: Any) -> "CalcBook":
        """声明一个结果指标（如 b.metric("A端支座配筋", "Φ8@200")）。

        批量视图会为出现过的指标名动态增加结果列；同名指标全行共用一列。
        """
        self.metrics[name] = value
        return self

    # ------------------------------------------------------------------
    # 验算：一等公民
    # ------------------------------------------------------------------
    def check(
        self,
        name: str,
        *,
        value: float,
        limit: float,
        op: Literal["le", "ge"] = "le",
        expr: str | None = None,
        unit: str | None = None,
        cite: tuple[str, str] | None = None,
        ratio: float | None = None,
    ) -> "CalcBook":
        """声明一项验算：数值 vs 限值，自动判定并汇总。

        op="le"（默认）：value ≤ limit 成立即满足（需求 ≤ 提供）；
        op="ge"：value ≥ limit 成立即满足（提供 ≥ 需求）。
        ratio：比值，缺省按 le=value/limit、ge=limit/value 计算。
        """
        if ratio is None:
            ratio = value / limit if op == "le" else limit / value
        passed = (value <= limit) if op == "le" else (value >= limit)
        self._items.append(
            _Item(kind="check", name=name, value=value, limit=limit,
                  op=op, expr=expr or "", unit=unit or "", cite=cite,
                  ratio=ratio, passed=passed)
        )
        return self

    # ------------------------------------------------------------------
    # 供界面/后端读取
    # ------------------------------------------------------------------
    @property
    def checks(self) -> list[_Item]:
        return [it for it in self._items if it.kind == "check"]

    @property
    def max_ratio(self) -> float | None:
        ratios = [c.ratio for c in self.checks if c.ratio is not None]
        return max(ratios) if ratios else None

    @property
    def all_ok(self) -> bool:
        checks = self.checks
        return bool(checks) and all(c.passed for c in checks)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def to_markdown(self, *, with_summary: bool = True) -> str:
        """Markdown 导出物（纯阅读用，不参与预览/渲染管线）。"""
        lines: list[str] = []
        if self.title:
            lines += [f"# {self.title}", ""]

        for it in self._items:
            if it.kind == "h1":
                lines += [f"# {it.text}", ""]
            elif it.kind == "h2":
                lines += [f"## {it.text}", ""]
            elif it.kind == "h3":
                lines += [f"### {it.text}", ""]
            elif it.kind == "p":
                lines += [it.text, ""]
            elif it.kind in ("formula", "subs"):
                lines += [f"$${it.text}$$", *self._cite_lines(it), ""]
            elif it.kind == "check":
                lines += [f"- {self._check_text(it)}", *self._cite_lines(it), ""]
            elif it.kind == "image":
                alt = it.caption or "图"
                lines += [f"![{alt}]({it.path})", ""]
            elif it.kind == "table":
                lines += self._render_table(it.header, it.rows)

        if with_summary and self.checks:
            header, rows = self._summary_table()
            lines += self._render_table(header, rows)
        return "\n".join(lines).rstrip() + "\n"

    def to_html(self, *, with_summary: bool = True) -> str:
        """items 直出 HTML（界面预览与 HTML 导出用）。

        结构只由 API 决定；文本一律转义；行内格式（粗体/行内公式）契约见
        docs/模板开发指南.md「内容语法契约」。图片环绕（side）由 image() 参数驱动。
        """
        out: list[str] = []
        if self.title:
            out.append(f"<h1>{_inline(self.title)}</h1>")
        for it in self._items:
            k = it.kind
            if k in ("h1", "h2", "h3"):
                out.append(f"<{k}>{_inline(it.text)}</{k}>")
            elif k == "p":
                for line in it.text.split("\n"):
                    if line.strip():
                        out.append(f"<p>{_inline(line)}</p>")
            elif k in ("formula", "subs"):
                out.append(f"<p class='formula'>{_esc(f'$${it.text}$$')}</p>")
                out.extend(_cite_html(it))
            elif k == "check":
                out.append(f"<p class='item'>• {_inline(self._check_text(it))}</p>")
                out.extend(_cite_html(it))
            elif k == "image":
                alt = it.caption or "图"
                if it.side:      # 图文环绕：浮动 figure（收边规则见 docstyle.py）
                    cap = (f"<figcaption>{_inline(alt)}</figcaption>"
                           if alt != "图" else "")
                    out.append(f"<figure class='cb-float-{it.side}'>"
                               f"<img src='{_esc(it.path)}' alt='{_esc(alt)}'>{cap}</figure>")
                else:
                    out.append(f"<p style='text-align:center'>"
                               f"<img src='{_esc(it.path)}' alt='{_esc(alt)}'></p>")
                    if alt != "图":
                        out.append(f"<p style='text-align:center'>"
                                   f"<small>{_inline(alt)}</small></p>")
            elif k == "table":
                out.extend(_table_html(it.header, it.rows))
        if with_summary and self.checks:
            out.extend(_table_html(*self._summary_table()))
        return "\n".join(out)

    # ------------------------------------------------------------------
    def _cite_lines(self, it: _Item) -> list[str]:
        if it.cite:
            return [f"> 依据：{it.cite[0]} 第 {it.cite[1]} 条", ""]
        return []

    def _check_text(self, it: _Item) -> str:
        """check 判定行的正文（md 版加 `- ` 前缀、html 版包 <p class='item'>）。"""
        sym = "≤" if it.op == "le" else "≥"
        unit = f" {it.unit}" if it.unit else ""
        expr_part = f"${it.expr}$：" if it.expr else ""
        verdict = "**满足**" if it.passed else "**不满足**"
        return (
            f"**{it.name}**：{expr_part}{_fmt(it.value)} {sym} {_fmt(it.limit)}{unit}，"
            f"比值 {_fmt(it.ratio)} —— {verdict}"
        )

    def _render_table(self, header: list[str], rows: list[list[Any]]) -> list[str]:
        out = ["| " + " | ".join(str(h) for h in header) + " |",
               "| " + " | ".join("---" for _ in header) + " |"]
        out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
        return out + [""]

    def _summary_table(self) -> tuple[list[str], list[list[Any]]]:
        has_cite = any(c.cite for c in self.checks)
        rows = []
        for c in self.checks:
            sym = "≤" if c.op == "le" else "≥"
            unit = f" {c.unit}" if c.unit else ""
            verdict = "满足" if c.passed else "**不满足**"
            row = [
                c.name,
                f"{_fmt(c.value)} {sym} {_fmt(c.limit)}{unit}",
                _fmt(c.ratio),
                verdict,
            ]
            if has_cite:
                row.append(f"{c.cite[0]} {c.cite[1]}" if c.cite else "")
            rows.append(row)
        header = ["验算项", "数值", "比值", "结论"]
        if has_cite:
            header.append("依据")
        return header, rows


# ----------------------------------------------------------------------
# HTML 渲染部件（内容语法契约的实现，转义优先）
# ----------------------------------------------------------------------
def _esc(text: str) -> str:
    return html.escape(text, quote=True)


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _inline(text: str) -> str:
    """行内格式：HTML 转义 + `**粗体**`（唯一的内容级语法，见模板开发指南）。"""
    return _BOLD_RE.sub(r"<b>\1</b>", _esc(text))


def _cite_html(it: _Item) -> list[str]:
    if it.cite:
        return [f"<blockquote>{_inline(f'依据：{it.cite[0]} 第 {it.cite[1]} 条')}</blockquote>"]
    return []


def _table_html(header: list[str], rows: list[list[Any]]) -> list[str]:
    ths = "".join(f"<th>{_inline(str(h))}</th>" for h in header)
    out = [f"<table><tr>{ths}</tr>"]
    out += [f"<tr>{''.join(f'<td>{_inline(str(c))}</td>' for c in row)}</tr>"
            for row in rows]
    out.append("</table>")
    return out


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    if isinstance(v, int) or float(v).is_integer():
        return str(int(v))
    return f"{v:.4g}"
