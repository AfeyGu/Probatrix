"""计算执行：参数校验 → 运行模板 → 收集结果/报错。

报错不打断界面（契约第 9 节）：任何异常都变成 RunResult.error 里的
原样 traceback，前端预览区直接展示——这也是模板作者的调试界面；
唯例外是缺第三方库（ModuleNotFoundError / 声明缺失）：给「缺少依赖 +
安装指引」的可读信息，不甩原始 traceback。
"""

from __future__ import annotations

import re
import traceback
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from .template import TemplateMeta

__all__ = ["RunResult", "run_template", "RunError"]


@dataclass
class RunResult:
    """一次模板执行的完整结果（成功与失败都是它，不抛异常）。"""

    ok: bool = False
    md: str = ""                                # Markdown 导出物（纯阅读，不参与渲染）
    html: str = ""                              # items 直出的 HTML（预览/导出用）
    checks: list[dict[str, Any]] = field(default_factory=list)   # 供表格/汇总
    metrics: dict[str, Any] = field(default_factory=dict)        # 批量表格附加指标列
    max_ratio: float | None = None
    all_ok: bool | None = None
    error_title: str = ""                       # 简短错误标题，如「参数校验失败」
    error: str = ""                             # 原样 traceback / 校验详情

    def from_book(self, book: Any) -> "RunResult":
        self.md = book.to_markdown()
        self.html = book.to_html()
        self.metrics = dict(getattr(book, "metrics", {}) or {})
        self.checks = [
            {
                "name": c.name,
                "value": c.value,
                "limit": c.limit,
                "op": c.op,
                "ratio": c.ratio,
                "passed": c.passed,
                "unit": c.unit,
            }
            for c in book.checks
        ]
        self.max_ratio = book.max_ratio
        self.all_ok = book.all_ok
        self.ok = True
        return self


@dataclass
class RunError(Exception):
    """带简短标题的计算异常（标题给界面，原文进 error）。"""

    title: str
    detail: str

    def __str__(self) -> str:
        return f"{self.title}\n{self.detail}"


def run_template(meta: TemplateMeta, params_data: dict[str, Any],
                 name: str = "") -> RunResult:
    """用参数字典运行模板；永不抛异常，失败信息在 RunResult 里。

    name：计算项名称（批量行的「名称」列），模板声明了可选 name 形参时传入。
    """
    if meta.missing_deps:
        return RunResult(
            error_title="缺少依赖",
            error=_deps_hint(meta),
        )
    try:
        params = meta.make_params(params_data)
    except ValidationError as e:
        return RunResult(
            error_title="参数校验失败",
            error=f"{e.title}\n{e}",
        )
    try:
        book = meta.run(params, name=name)
    except ModuleNotFoundError as e:          # 模板依赖未装：给可读指引，不甩原始 traceback
        return RunResult(
            error_title="缺少依赖",
            error=_module_not_found_hint(e, meta),
        )
    except Exception:
        return RunResult(
            error_title="计算出错",
            error=traceback.format_exc(),
        )
    if not hasattr(book, "to_html"):            # 模板作者忘了 return CalcBook
        return RunResult(
            error_title="模板返回值类型错误",
            error=(
                f"{meta.template_id} 应返回 CalcBook 实例，"
                f"实际返回 {type(book).__name__}"
            ),
        )
    try:
        return RunResult().from_book(book)
    except Exception:                           # 鸭子对象缺 checks 等属性：同样不抛
        return RunResult(
            error_title="计算结果读取失败",
            error=traceback.format_exc(),
        )


# ----------------------------------------------------------------------
# 依赖缺失的友好提示
# ----------------------------------------------------------------------
_INSTALL_HINT = (
    "解决办法：\n"
    "  1) Python 环境：{cmd}\n"
    "  2) Windows 便携版：关闭 CalcBook，在解压目录执行 .\\python\\python.exe -m {cmd} 后重新打开。\n"
    "  库的导入名与 PyPI 包名可能不同，请按模板说明安装。\n"
)


def _deps_hint(meta: TemplateMeta) -> str:
    """模板声明了依赖但环境缺失：逐条列出缺什么、怎么装。"""
    names = "、".join(meta.missing_deps)
    return (
        f"模板「{meta.name}」（{meta.template_id}）需要已安装的库：{names}\n"
        f"当前环境中未找到，无法运行。\n\n"
        + _INSTALL_HINT.format(cmd=f"pip install {' '.join(meta.missing_deps)}")
    )


def _module_not_found_hint(e: ModuleNotFoundError, meta: TemplateMeta) -> str:
    """运行中途因缺库抛 ModuleNotFoundError：解析缺哪个库，给可读指引。"""
    name = getattr(e, "name", None) or _missing_from_traceback()
    if name:
        return (
            f"模板「{meta.name}」在运行时需要未安装的库：{name}\n\n"
            + _INSTALL_HINT.format(cmd=f"pip install {name}")
        )
    return traceback.format_exc()   # 解析不到具体模块名，退回原始 traceback


_MISSING_RE = re.compile(r"No module named '([^']+)'")


def _missing_from_traceback() -> str | None:
    m = _MISSING_RE.search(traceback.format_exc())
    return m.group(1) if m else None
