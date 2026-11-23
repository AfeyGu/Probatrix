"""Markdown 块渲染：把整篇文档当计算书正文（`Probatrix.markdown` 的实现）。

与 `p()` 的分工（两条契约互不干扰，各自有测试锁）：
- `p()`：**单段文字**，只认 `**粗体**` 与 `$…$`，长得像结构也按字面显示；
- `markdown()`：**整篇 Markdown**，标题/段落/围栏代码块/有序无序列表/表格/
  引用/分隔线成结构，行内认 `code`、`**粗体**`、`[链接](url)` 与 `$…$`（KaTeX），
  独占一行的 `![图注](相对路径)` 内嵌本地图片（需显式给 base_dir，见纪律 3）。

三条纪律：
1. **转义优先**：先整体 HTML 转义再做标记替换；行内代码先抽成占位符，
   其内部的 `**`、`<` 不参与标记解析。md 里写 `<script>` 只会显示成文字。
2. **站内链接不生成 `<a>`**：预览区是页面内嵌容器，真链接会把整个界面跳走。
   非 http(s) 目标（如 `[模板开发指南.md](模板开发指南.md)`）渲染成行内代码。
3. **图片只读显式给出的 base_dir**：同一份 md 既进预览也进 HTML 导出，图片编成
   base64 data URI 才算离线可用；Markdown 导出物则原样保留 `![图注](路径)` 文字。
   读取范围严格限定在 base_dir 及其下级（绝对路径、URL、Windows 盘符、ADS 数据流
   一律拒绝；`..` 与符号链接只在真的指到 base_dir 之外时才拒绝），只认 PNG/JPEG/
   WebP/GIF 且按文件头判真实格式，只收普通文件。没给 base_dir、路径不合法或解析
   失败（含非法字符、超长、链接环）、文件缺失、内容不是图片时，就地给一行可读提示
   并显示引用的路径（HTML 转义），绝不静默丢图、绝不抛异常中断整篇计算，也绝不联网取图。

图片语法只认**独占一行**的 `![图注](路径)`：图注可为空，路径可含空格与中文；
图注按行内格式渲染、显示在图下方。图片行会结束上一段（不吞进前一段落），
围栏代码块里仍是文字。不支持 `![a](b "title")`、尖括号路径与行内混排图片。

刻意不做：setext 标题、深层嵌套列表、表格单元格内的竖线转义、行内图片、
图片标题（title）、HTML 直通——文档里用不到，多一分代码多一分错。
"""

from __future__ import annotations

import base64
import html
import re
import unicodedata
from pathlib import Path

__all__ = ["md_to_html"]

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^\s`]*)")
_IMAGE = re.compile(r"^ {0,3}!\[([^\]]*)\]\((.*)\)\s*$")   # 独占一行；路径取到行尾最后一个 )
_CTRL = re.compile(r"[\x00-\x1f\x7f]")                      # 提示里显示的控制字符（如 NUL）
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


def md_to_html(text: str, *, base_dir: str | Path | None = None) -> str:
    """Markdown → HTML 片段（块级元素逐行排版，行内标记见模块说明）。

    base_dir：图片相对路径的根目录。缺省 None 时不读任何文件，图片位置只留提示。
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(_blocks(lines, base_dir))


# ----------------------------------------------------------------------
# 块级
# ----------------------------------------------------------------------
def _blocks(lines: list[str], base_dir: str | Path | None = None) -> list[str]:
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

        image = _IMAGE.match(line)
        if image:
            out.append(_image_block(image.group(1), image.group(2).strip(), base_dir))
            i += 1
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
            out.append("<blockquote>" + "\n".join(_blocks(body, base_dir))
                       + "</blockquote>")
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
        _FENCE.match(line) or _IMAGE.match(line) or _HEADING.match(line)
        or _HR.match(line) or _QUOTE.match(line) or _UL.match(line)
        or _OL.match(line) or _is_table_start(lines, i)
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
# 图片：只读显式给出的 base_dir，成功即编成 base64 data URI
# ----------------------------------------------------------------------
#: 准入名单（扩展名只管「像不像图片」，真实格式按文件头判）
_IMG_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}


class _ImageProblem(Exception):
    """无法内嵌图片的原因（消息给读者看，必须是中文短句）。"""


def _image_block(alt: str, ref: str, base_dir: str | Path | None) -> str:
    """图片行 → figure（内嵌 base64）；失败则一行就地提示，保留引用路径。"""
    try:
        mime, data = _read_image(ref, base_dir)
    except _ImageProblem as exc:
        return (f"<p class='cb-md-img-note'>图片未嵌入：<code>{_shown(ref)}</code>"
                f"（{_esc(str(exc))}）</p>")
    src = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    caption = f"<figcaption>{_inline(alt)}</figcaption>" if alt.strip() else ""
    return (f"<figure class='cb-md-img'><img src='{_esc(src)}' alt='{_esc(alt)}'>"
            f"{caption}</figure>")


def _read_image(ref: str, base_dir: str | Path | None) -> tuple[str, bytes]:
    """校验并读取图片，返回 (MIME, 原始字节)；不合限制时抛 _ImageProblem。

    安全边界：只看显式传入的 base_dir；ref 与 base_dir 都先 resolve 成真实路径
    再判包含关系——`..` 与符号链接（Windows 的目录联接）只要指到 base_dir 之外
    就被拒，指在目录里的照常放行。
    `:` 一律拒绝：一条规则同时挡掉 Windows 盘符（`C:\\`）、目录替代数据流
    （`a.png:stream`）和各种 URL 协议（`http:`、`data:`、`file:`）——Windows
    文件名本身不允许冒号。首字符 `/`、`\\` 挡掉绝对路径与 UNC 共享目录。

    任何文件系统怪状（非法字符、超长路径、链接环、权限、设备文件）都折成
    _ImageProblem：计算书正文里留一行提示，不让整篇计算因为一张图而失败。
    """
    if base_dir is None:
        raise _ImageProblem("未提供 base_dir，相对路径无从解析")
    if not ref:
        raise _ImageProblem("图片路径为空")
    if ":" in ref or ref.startswith(("/", "\\")):
        raise _ImageProblem("只接受 base_dir 内的相对路径")
    try:
        root = Path(base_dir).resolve()
        target = (root / ref).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise _ImageProblem(f"路径无法解析：{_why(exc)}") from exc
    if not target.is_relative_to(root):
        raise _ImageProblem("路径超出 base_dir 范围")
    if _IMG_SUFFIX.get(target.suffix.lower()) is None:
        raise _ImageProblem("只支持 PNG/JPEG/WebP/GIF 图片")
    try:
        if target.is_dir():
            raise _ImageProblem("这是目录，不是图片文件")
        if not target.is_file():           # 不存在，或设备/管道等非普通文件
            raise _ImageProblem("文件不存在" if not target.exists() else "不是普通文件")
        data = target.read_bytes()
    except _ImageProblem:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise _ImageProblem(f"读取失败：{_why(exc)}") from exc
    if not data:
        raise _ImageProblem("文件是空的")
    mime = _sniff(data)
    if mime is None:
        raise _ImageProblem("文件内容不是 PNG/JPEG/WebP/GIF")
    return mime, data


def _why(exc: Exception) -> str:
    """异常 → 给读者看的一小段原因（系统报错文字可能是英文长句，这里只取要点）。"""
    if isinstance(exc, ValueError):        # 典型：embedded null byte
        return "路径含非法字符"
    return str(getattr(exc, "strerror", None) or exc or type(exc).__name__).strip()


def _sniff(data: bytes) -> str | None:
    """按文件头判真实格式：扩展名可能骗人（`.png` 里塞别的格式仍按实际显示）。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _shown(text: str) -> str:
    """提示里回显的引用原文：HTML 转义，控制字符（如 NUL）换成可见的 �。"""
    return _esc(_CTRL.sub("\ufffd", text))


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
