"""计算执行：参数校验 → 运行模板 → 收集结果/报错。

报错不打断界面（契约第 9 节）：任何异常都变成 RunResult.error 里的
原样 traceback，前端预览区直接展示——这也是模板作者的调试界面。
"""

from __future__ import annotations

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
    md: str = ""                                # CalcBook 渲染的 md+LaTeX
    checks: list[dict[str, Any]] = field(default_factory=list)   # 供表格/汇总
    max_ratio: float | None = None
    all_ok: bool | None = None
    error_title: str = ""                       # 简短错误标题，如「参数校验失败」
    error: str = ""                             # 原样 traceback / 校验详情

    def from_book(self, book: Any) -> "RunResult":
        self.md = book.to_markdown()
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


def run_template(meta: TemplateMeta, params_data: dict[str, Any]) -> RunResult:
    """用参数字典运行模板；永不抛异常，失败信息在 RunResult 里。"""
    try:
        params = meta.make_params(params_data)
    except ValidationError as e:
        return RunResult(
            error_title="参数校验失败",
            error=f"{e.title}\n{e}",
        )
    try:
        book = meta.run(params)
    except Exception:
        return RunResult(
            error_title="计算出错",
            error=traceback.format_exc(),
        )
    if not hasattr(book, "to_markdown"):        # 模板作者忘了 return CalcBook
        return RunResult(
            error_title="模板返回值类型错误",
            error=(
                f"{meta.template_id} 应返回 CalcBook 实例，"
                f"实际返回 {type(book).__name__}"
            ),
        )
    return RunResult().from_book(book)
