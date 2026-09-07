"""FastAPI 服务：CalcBook 本地后端（单用户本地应用，服务端持有状态）。

端点一览（均挂 /api 前缀）：

    GET    /api/templates                模板列表（含加载报错的文件）
    POST   /api/templates/refresh        重扫模板目录（改代码免重启）
    GET    /api/templates/{tid}/schema   参数元信息（驱动表单/表格列）
    POST   /api/run                      单项计算 → RunResult
    POST   /api/run-batch                批量计算 → 逐项 RunResult
    GET    /api/project                  当前工程
    PUT    /api/project                  整体替换当前工程（前端持有编辑态）
    POST   /api/project/new              新建工程
    POST   /api/project/save             保存到 .cbproj
    POST   /api/project/load             从 .cbproj 载入
    GET    /api/hash-check               工程内模板 hash 与当前文件比对（失效提示）
    GET    /api/doc.css                  计算书文档排版 CSS（前端预览用）
    POST   /api/export/html              md → 自包含 HTML（KaTeX + 打印样式）
"""

from __future__ import annotations

import base64
import html
import re
import webbrowser
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel as APIModel

from .docstyle import DOC_CSS
from .engine import RunResult, run_template
from .fields import param_meta
from .loader import TemplateLoader
from .project import Project, load_project, new_project, save_project

__all__ = ["create_app", "AppContext"]

#: 导出页模板：@@...@@ 为填充标记（不用 str.format，避开 CSS 花括号冲突）
_HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>@@TITLE@@</title>
@@ASSETS@@
<style>
@@DOCSTYLE@@
  body { max-width: 210mm; margin: 0 auto; padding: 24px 32px; }
  .meta { border-bottom: 2px solid #333; padding-bottom: 8px; margin-bottom: 20px;
          font-size: 14px; color: #444; }
  .meta b { margin-right: 24px; }
  @media print {
    body { padding: 0; }
    .no-print { display: none; }
    .page-break { page-break-before: always; }
  }
</style>
</head>
<body class="cb-doc">
<div class="meta">@@META@@</div>
<div class="no-print" style="text-align:right;margin-bottom:8px">
  <button onclick="window.print()">打印 / 存为 PDF</button>
</div>
<div id="content">@@CONTENT@@</div>
<script>
  renderMathInElement(document.getElementById("content"), {
    delimiters: [
      {left: "$$", right: "$$", display: true},
      {left: "$", right: "$", display: false},
    ],
  });
</script>
</body>
</html>"""

_KATEX_CDN = """<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>"""

#: 离线导出仅内联 woff2（现代浏览器全支持）：约 0.65 MB；
#: 再加 woff/ttf 会膨胀到 1.7 MB，收益只覆盖十几年前的旧浏览器。
_SRC_RE = re.compile(r"src:(.*?)(?=;|\})", re.S)
_FACE_ITEM_RE = re.compile(r'''url\(([^)]+)\)\s*format\("([^"]+)"\)''')


@dataclass
class AppContext:
    """服务端状态：模板加载器 + 当前工程（单用户本地应用）。"""

    loader: TemplateLoader
    project: Project = field(default_factory=new_project)

    def ensure_template(self, template_id: str):
        entry = self.loader.entries.get(template_id)
        if entry is None:
            raise HTTPException(404, f"模板不存在：{template_id}")
        return entry


# ----------------------------------------------------------------------
# 请求/响应模型
# ----------------------------------------------------------------------
class RunReq(APIModel):
    template_id: str
    params: dict[str, Any] = {}
    name: str = ""


class BatchReq(APIModel):
    template_id: str
    items: list[RunReq]


class ProjectDoc(APIModel):
    name: str = "未命名工程"
    items: list[dict[str, Any]] = []
    views: dict[str, Any] = {}


class PathReq(APIModel):
    path: str


class ExportReq(APIModel):
    md: str
    title: str = "计算书"
    meta: dict[str, str] = {}          # 工程名/计算人/日期/校对人等页眉字段
    inline_assets: bool = False        # 离线版：内联 KaTeX 与字体（~0.7 MB）


class RenderReq(APIModel):
    md: str


# ----------------------------------------------------------------------
# 应用工厂
# ----------------------------------------------------------------------
def create_app(template_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="CalcBook API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"],
        allow_methods=["*"], allow_headers=["*"],
    )
    ctx = AppContext(loader=TemplateLoader(template_dir or default_template_dir()))
    ctx.loader.scan()
    app.state.ctx = ctx

    # ---- 模板 --------------------------------------------------------
    @app.get("/api/templates")
    def list_templates() -> dict[str, Any]:
        return {
            "templates": [
                {
                    "template_id": e.meta.template_id,
                    "name": e.meta.name,
                    "description": e.meta.description,
                    "manual": e.meta.manual,
                    "hash": e.hash,
                }
                for e in ctx.loader.entries.values()
            ],
            "errors": [
                {"file": str(err.file), "error": err.error}
                for err in ctx.loader.errors
            ],
        }

    @app.post("/api/templates/refresh")
    def refresh_templates() -> dict[str, Any]:
        ctx.loader.scan()
        return list_templates()

    @app.get("/api/templates/{template_id}/schema")
    def template_schema(template_id: str) -> dict[str, Any]:
        entry = ctx.ensure_template(template_id)
        return {
            "template_id": entry.meta.template_id,
            "name": entry.meta.name,
            "description": entry.meta.description,
            "manual": entry.meta.manual,
            "hash": entry.hash,
            "params": param_meta(entry.meta.params_model),
        }

    # ---- 计算 --------------------------------------------------------
    @app.post("/api/run")
    def run(req: RunReq) -> dict[str, Any]:
        entry = ctx.ensure_template(req.template_id)
        result = run_template(entry.meta, req.params, name=req.name)
        return _result_json(result)

    @app.post("/api/run-batch")
    def run_batch(req: BatchReq) -> dict[str, Any]:
        entry = ctx.ensure_template(req.template_id)
        return {
            "results": [
                {"id": it.name or str(i), **_result_json(
                    run_template(entry.meta, it.params, name=it.name))}
                for i, it in enumerate(req.items)
            ],
        }

    # ---- 工程 --------------------------------------------------------
    def _doc() -> dict[str, Any]:
        return {
            "name": ctx.project.name,
            "items": [
                {
                    "id": it.id, "name": it.name,
                    "template_id": it.template_id,
                    "template_hash": it.template_hash,
                    "params": it.params, "deps": it.deps,
                }
                for it in ctx.project.items
            ],
            "views": ctx.project.views,
        }

    @app.get("/api/project")
    def get_project() -> dict[str, Any]:
        return _doc()

    @app.put("/api/project")
    def put_project(doc: ProjectDoc) -> dict[str, Any]:
        proj = Project(
            name=doc.name,
            items=[],
            views=doc.views,
        )
        from .project import CalcItem
        for it in doc.items:
            item = CalcItem(
                name=it.get("name", ""),
                template_id=it.get("template_id", ""),
                template_hash=it.get("template_hash", ""),
                params=it.get("params", {}),
                deps=it.get("deps", {}),
            )
            if it.get("id"):
                item.id = it["id"]          # 保留前端已有 id，否则用新生成
            proj.items.append(item)
        ctx.project = proj
        return _doc()

    @app.post("/api/project/new")
    def new_proj(doc: ProjectDoc | None = None) -> dict[str, Any]:
        ctx.project = new_project((doc or ProjectDoc()).name)
        return _doc()

    @app.post("/api/project/save")
    def save_proj(req: PathReq) -> dict[str, Any]:
        path = save_project(ctx.project, req.path)
        return {"saved": str(path)}

    @app.post("/api/project/load")
    def load_proj(req: PathReq) -> dict[str, Any]:
        ctx.project = load_project(req.path)
        return _doc()

    # ---- hash 校验 ----------------------------------------------------
    @app.get("/api/hash-check")
    def hash_check() -> dict[str, Any]:
        from .loader import file_hash
        rows = []
        for it in ctx.project.items:
            entry = ctx.loader.entries.get(it.template_id)
            current = entry.hash if entry else None
            rows.append({
                "id": it.id, "template_id": it.template_id,
                "stored": it.template_hash, "current": current,
                "stale": current is not None and current != it.template_hash,
                "missing": entry is None,
            })
        return {"items": rows}

    # ---- 导出 --------------------------------------------------------
    @app.post("/api/export/html")
    def export_html(req: ExportReq) -> dict[str, str]:
        meta_cells = "".join(f"<b>{html.escape(k)}：{html.escape(v)}</b>"
                             for k, v in req.meta.items())
        try:
            assets = _assets_html(req.inline_assets)
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        page = (_HTML_TMPL
                .replace("@@TITLE@@", html.escape(req.title))
                .replace("@@ASSETS@@", assets)
                .replace("@@META@@", meta_cells)
                .replace("@@DOCSTYLE@@", DOC_CSS)
                .replace("@@CONTENT@@", _render_markdown(req.md)))
        return {"html": page, "inline": str(req.inline_assets)}

    # ---- 预览渲染（与导出同一套 md→HTML 逻辑）---------------------------
    @app.post("/api/render")
    def render(req: RenderReq) -> dict[str, str]:
        return {"html": _render_markdown(req.md)}

    # ---- 文档排版 CSS：前端预览与导出共用 docstyle.DOC_CSS ---------------
    @app.get("/api/doc.css")
    def doc_css() -> Response:
        return Response(DOC_CSS, media_type="text/css")

    # 前端：构建产物在包内 calcbook/web（由 vite 输出），有则静态托管
    dist = Path(__file__).resolve().parent / "web"
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:
        @app.get("/")
        def index() -> dict[str, str]:
            return {"app": "CalcBook", "api": "/docs"}

    return app


# ----------------------------------------------------------------------
def _assets_html(inline: bool) -> str:
    """头部资源：CDN（默认，文件小）或全量内联（离线可看）。"""
    if not inline:
        return _KATEX_CDN
    css, kjs, arjs = _katex_inline_assets()
    return (f"<style>{css}</style>"
            f"<script>{kjs}</script><script>{arjs}</script>")


@lru_cache(maxsize=1)
def _katex_inline_assets() -> tuple[str, str, str]:
    """读包内 vendor/katex（由 web/scripts/vendor-katex.mjs 构建时拷入）。

    字体只保留 woff2 并转 base64，其余格式从 src 列表剔除（避免拼出无效 CSS）。
    结果进进程缓存：改了 KaTeX 版本需重启服务。
    """
    k = Path(__file__).resolve().parent / "vendor" / "katex"
    needed = ("katex.min.css", "katex.min.js", "contrib/auto-render.min.js")
    missing = [n for n in needed if not (k / n).is_file()]
    if missing:
        raise RuntimeError(
            f"缺少内嵌 KaTeX 资源：{missing}——请重新构建前端（cd web && npm run build）"
        )

    def _data_uri(rel: str, fmt: str) -> str:
        path = (k / rel.lstrip("./")).resolve()
        if not path.is_file():
            return f'url("{rel}") format("{fmt}")'
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        mime = {"woff2": "font/woff2", "woff": "font/woff",
                "truetype": "font/ttf"}.get(fmt, "application/octet-stream")
        return f'url(data:{mime};base64,{b64}) format("{fmt}")'

    def _rewrite_src(m: re.Match[str]) -> str:
        items = _FACE_ITEM_RE.findall(m.group(1))
        keep = [it for it in items if it[0].endswith(".woff2")] or items[:1]
        return "src:" + ", ".join(_data_uri(u, f) for u, f in keep)

    css = _SRC_RE.sub(_rewrite_src, (k / "katex.min.css").read_text(encoding="utf-8"))
    return (css,
            (k / "katex.min.js").read_text(encoding="utf-8"),
            (k / "contrib" / "auto-render.min.js").read_text(encoding="utf-8"))


def _result_json(r: RunResult) -> dict[str, Any]:
    return {
        "ok": r.ok, "md": r.md, "checks": r.checks, "metrics": r.metrics,
        "max_ratio": r.max_ratio, "all_ok": r.all_ok,
        "error_title": r.error_title, "error": r.error,
    }


def _render_markdown(md: str) -> str:
    """MVP 最小 md 渲染：标题/表格/引用/图片/列表/粗体；公式原样交给 KaTeX。"""
    out: list[str] = []
    in_table = False
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("<!--") and "pagebreak" in line:
            out.append("<div class='page-break'></div>")
            continue
        if line.startswith("$$"):
            out.append(f"<p class='formula'>{_esc(line)}</p>")
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= {"-", ":", " "}:     # 分隔行
                continue
            if not in_table:
                out.append("<table><tr>" + "".join(
                    f"<th>{_inline(c)}</th>" for c in cells) + "</tr>")
                in_table = True
            else:
                out.append("<tr>" + "".join(
                    f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if not line:
            continue
        # 先剥前缀（在转义之前），再转义剩余内容
        for prefix, tag in (("### ", "h3"), ("## ", "h2"), ("# ", "h1"),
                            ("> ", "blockquote"), ("- ", "li")):
            if line.startswith(prefix):
                body = _inline(line[len(prefix):])
                if tag == "li":
                    out.append(f"<p class='item'>• {body}</p>")
                else:
                    out.append(f"<{tag}>{body}</{tag}>")
                break
        else:
            if line.startswith("!["):
                alt, _, rest = line[2:].partition("](")
                src = rest.rstrip(")")
                out.append(
                    f"<p style='text-align:center'>"
                    f"<img src='{_esc(src)}' alt='{_esc(alt)}'></p>")
                if alt and alt != "图":          # 小注随 alt 传递，居中显示
                    out.append(
                        f"<p style='text-align:center'>"
                        f"<small>{_inline(alt)}</small></p>")
            else:
                out.append(f"<p>{_inline(line)}</p>")
    if in_table:
        out.append("</table>")
    return "\n".join(out)


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _inline(text: str) -> str:
    """转义后补行内样式：仅粗体（MVP 够用）。"""
    return _BOLD_RE.sub(r"<b>\1</b>", _esc(text))


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def default_template_dir() -> Path:
    return Path.home() / "CalcBook模板"


def find_free_port(host: str, port: int) -> int:
    """从 port 起找第一个可绑定端口（含本身），最多试 100 个。"""
    import socket
    for p in range(port, port + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    raise SystemExit(f"端口 {port}-{port + 99} 均被占用，无法启动服务")


def main(host: str = "127.0.0.1", port: int = 8317,
         template_dir: str | Path | None = None, open_browser: bool = True,
         ui: str = "browser") -> None:
    import uvicorn
    base_port = port
    port = find_free_port(host, port)
    if port != base_port:
        print(f"端口 {base_port} 已被占用，改用 {port}", flush=True)
    url = f"http://{host}:{port}"
    print(f"CalcBook 已启动：{url}（Ctrl+C 退出）", flush=True)
    if ui == "webview":
        _run_webview(host, port, template_dir, url)
        return
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(template_dir), host=host, port=port, log_level="warning")


def _run_webview(host: str, port: int, template_dir: str | Path | None, url: str) -> None:
    """桌面窗口模式：uvicorn 跑后台线程，pywebview 开原生窗口（Win10/11 自带 WebView2）。"""
    import threading
    import time
    import urllib.request
    try:
        import webview
    except ImportError:
        print("未安装 pywebview，退回浏览器模式（pip install pywebview 可启用桌面窗口）", flush=True)
        webbrowser.open(url)
        import uvicorn
        uvicorn.run(create_app(template_dir), host=host, port=port, log_level="warning")
        return

    import uvicorn
    server = uvicorn.Server(uvicorn.Config(
        create_app(template_dir), host=host, port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()

    # 等服务真正监听后再开窗口，避免加载失败
    for _ in range(50):
        try:
            urllib.request.urlopen(url, timeout=1).close()
            break
        except OSError:
            time.sleep(0.1)

    w, h = _window_size()
    webview.create_window("CalcBook 计算书", url, width=w, height=h)
    webview.start()
    server.should_exit = True


def _window_size() -> tuple[int, int]:
    """默认窗口大小：屏幕工作区的 90%（接近常见的浏览器窗口体量）。"""
    try:
        import ctypes.wintypes
        rc = ctypes.wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(
            0x0030, 0, ctypes.byref(rc), 0)  # SPI_GETWORKAREA
        w = int((rc.right - rc.left) * 0.9)
        h = int((rc.bottom - rc.top) * 0.9)
        if w > 200 and h > 200:
            return w, h
    except Exception:
        pass
    return 1280, 800


if __name__ == "__main__":
    main()
