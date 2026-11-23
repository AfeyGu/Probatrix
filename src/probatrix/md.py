"""Markdown 块渲染：把整篇文档当计算书正文（`Probatrix.markdown` 的实现）。

与 `p()` 的分工（两条契约互不干扰，各自有测试锁）：
- `p()`：**单段文字**，只认 `**粗体**` 与 `$…$`，长得像结构也按字面显示；
- `markdown()`：**整篇 Markdown**，标题/段落/围栏代码块/有序无序列表/表格/
  引用/分隔线成结构，行内认 `code`、`**粗体**`、`[链接](url)` 与 `$…$`（KaTeX）。

两条纪律：
1. **转义优先**：先整体 HTML 转义再做标记替换；行内代码先抽成占位符，
   其内部的 `**`、`<` 不参与标记解析。md 里写 `<script>` 只会显示成文字。
2. **站内链接不生成 `<a>`**：预览区是页面内嵌容器，真链接会把整个界面跳走。
   非 http(s) 目标（如 `[模板开发指南.md](模板开发指南.md)`）渲染成行内代码。

刻意不做：setext 标题、深层嵌套列表、表格单元格内的竖线转义、图片语法、
HTML 直通——文档里用不到，多一分代码多一分错。
"""

from __future__ import annotations

import html
import re
import unicodedata

__all__ = ["md_to_html"]

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^\s`]*)")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
_QUOTE = re.compile(r"^ {0,3}> ?(.*)$")
_UL = re.compile(r"^ {0,3}[-*+]\s+(.*)$")
_OL = re.compile(r"^ {0,3}\d{1,9}[.)]\s+(.*)$")
_TABLE_SEP = re.compile(r"^ {0,3}\|?[\s:|-]+\|?\s*$")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_PLACEHOLDER = re.compile("\x00(\\d+)\x00")


def md_to_html(text: str) -> str:
    """Markdown → HTML 片段（块级元素逐行排版，行内标记见模块说明）。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(_blocks(lines))


# ----------------------------------------------------------------------
# 块级
# ----------------------------------------------------------------------
def _blocks(lines: list[str]) -> list[str]:
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        fence = _FENCE.match(line)
        if fence:
            block, i = _code_block(lines, i, fence.group(1), fence.group(2))
            out.append(block)
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if _HR.match(line):
            out.append("<hr>")
            i += 1
            continue

        quote = _QUOTE.match(line)
        if quote:
            body: list[str] = []
            while i < n and (q := _QUOTE.match(lines[i])):
                body.append(q.group(1))
                i += 1
            out.append("<blockquote>" + "\n".join(_blocks(body)) + "</blockquote>")
            continue

        if _is_table_start(lines, i):
            out.append(_table_block(lines, i))
            i = _table_end(lines, i)
            continue

        if _UL.match(line) or _OL.match(line):
            html_list, i = _list_block(lines, i)
            out.append(html_list)
            continue

        paragraph: list[str] = []
        while i < n and lines[i].strip() and not (paragraph and _starts_block(lines, i)):
            paragraph.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(_join(paragraph))}</p>")
    return out


def _code_block(lines: list[str], start: int, fence: str, lang: str) -> tuple[str, int]:
    """围栏代码块：内容整体转义，内部标记一律不解析；返回 (html, 下一行下标)。"""
    body: list[str] = []
    i = start + 1
    while i < len(lines) and not lines[i].lstrip().startswith(fence):
        body.append(lines[i])
        i += 1
    if i < len(lines):
        i += 1                      # 吃掉闭合围栏（缺闭合围栏则到文本末尾）
    cls = f" class='language-{html.escape(lang, quote=True)}'" if lang else ""
    return f"<pre><code{cls}>{html.escape(chr(10).join(body), quote=False)}</code></pre>", i


def _is_table_start(lines: list[str], i: int) -> bool:
    """表格判定：本行含 `|`，下一行是只由 `-:|` 空格组成的分隔行。"""
    return (
        "|" in lines[i]
        and i + 1 < len(lines)
        and "-" in lines[i + 1]
        and bool(_TABLE_SEP.match(lines[i + 1]))
    )


def _table_end(lines: list[str], i: int) -> int:
    i += 2                     # 跳过表头与分隔行
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        i += 1
    return i


def _table_block(lines: list[str], i: int) -> str:
    header = _cells(lines[i])
    rows = [_cells(line) for line in lines[i + 2:_table_end(lines, i)]]
    head = "".join(f"<th>{_inline(c)}</th>" for c in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f"<table><tr>{head}</tr>{body}</table>"


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _list_block(lines: list[str], start: int) -> tuple[str, int]:
    """有序/无序列表；缩进续行并入上一项（不做深层嵌套）。"""
    ordered = bool(_OL.match(lines[start]))
    pattern = _OL if ordered else _UL
    items: list[str] = []
    i = start
    while i < len(lines):
        item = pattern.match(lines[i])
        if item:
            items.append(item.group(1))
            i += 1
        elif items and lines[i].strip() and lines[i][:1] in (" ", "\t"):
            items[-1] += "\n" + lines[i].strip()
            i += 1
        else:
            break
    tag = "ol" if ordered else "ul"
    body = "".join(f"<li>{_inline(t)}</li>" for t in items)
    return f"<{tag}>{body}</{tag}>", i


def _starts_block(lines: list[str], i: int) -> bool:
    line = lines[i]
    return bool(
        _FENCE.match(line) or _HEADING.match(line) or _HR.match(line)
        or _QUOTE.match(line) or _UL.match(line) or _OL.match(line)
        or _is_table_start(lines, i)
    )


def _join(lines: list[str]) -> str:
    """段内折行合并：中文直接相连；ASCII 结尾与汉字/行内代码之间补一个空格。"""
    out = ""
    for line in lines:
        if out and _needs_space(out[-1], line[0]):
            out += " "
        out += line
    return out


def _needs_space(prev: str, nxt: str) -> bool:
    """补空格的边界：英文词之间；ASCII（含行内代码的收尾反引号）与汉字之间。

    中文与标点之间不留空隙——全角括号、逗号自带留白，硬加空格反而难看。
    """
    if prev.isascii() and nxt.isascii():
        return prev.isalnum() and nxt.isalnum()
    return prev.isascii() and unicodedata.category(nxt)[0] not in "PZ"


# ----------------------------------------------------------------------
# 行内
# ----------------------------------------------------------------------
def _inline(text: str) -> str:
    """行内格式：抽行内代码 → 整体转义 → 链接/粗体 → 回填行内代码。"""
    codes: list[str] = []

    def stash(m: re.Match[str]) -> str:
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = html.escape(_CODE_SPAN.sub(stash, text), quote=False)
    text = _LINK.sub(_link, text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    return _PLACEHOLDER.sub(
        lambda m: f"<code>{html.escape(codes[int(m.group(1))], quote=False)}</code>", text)


def _link(m: re.Match[str]) -> str:
    label, url = m.group(1), html.unescape(m.group(2))
    if url.startswith(("http://", "https://")):
        href = html.escape(url, quote=True)
        return f"<a href='{href}' target='_blank' rel='noopener noreferrer'>{label}</a>"
    return f"<code>{label}</code>"      # 站内链接（含 .md）：不生成可点击链接
