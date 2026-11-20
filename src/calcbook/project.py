"""工程文件：.cbproj（纯 JSON）读写。

数据模型（契约第 5 节）：一个工程 = 多个「计算项」的集合；
每项 = {id, 名称, 模板id, 模板hash, 参数JSON}。
views 按模板 id 记录批量视图的列显隐配置；依赖模块 hash 位预留（deps）。
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .loader import file_hash

__all__ = ["CalcItem", "Project", "new_project", "load_project", "save_project"]

#: 工程文件格式版本；结构不兼容时递增
FORMAT_VERSION = 1


@dataclass
class CalcItem:
    """一个计算项：某模板的一次具体计算。"""

    name: str                                   # 显示名，如「GL-1」
    template_id: str                            # 如 "gl.calc"
    template_hash: str                          # 加载/保存时与当前模板文件比对
    params: dict[str, Any]                      # 完整参数（无隐藏状态）
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    deps: dict[str, str] = field(default_factory=dict)   # 预留：依赖模块 hash


@dataclass
class Project:
    name: str = "未命名工程"
    items: list[CalcItem] = field(default_factory=list)
    #: 按模板 id 记录的视图配置，如 {"gl.calc": {"hidden_cols": ["fy"]}}
    views: dict[str, dict[str, Any]] = field(default_factory=dict)

    def items_by_template(self, template_id: str) -> list[CalcItem]:
        return [it for it in self.items if it.template_id == template_id]


def new_project(name: str = "未命名工程") -> Project:
    return Project(name=name)


def save_project(project: Project, path: str | Path) -> Path:
    path = Path(path)
    doc = {
        "format_version": FORMAT_VERSION,
        "name": project.name,
        "items": [
            {
                "id": it.id,
                "name": it.name,
                "template_id": it.template_id,
                "template_hash": it.template_hash,
                "params": it.params,
                "deps": it.deps,
            }
            for it in project.items
        ],
        "views": project.views,
    }
    # 原子替换：先写同目录临时文件再 os.replace——中途崩溃/断电不会留下半个工程文件
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def load_project(path: str | Path) -> Project:
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"工程文件不是有效的 JSON（{path.name}）：{e}") from e
    if not isinstance(doc, dict):
        raise ValueError(f"工程文件结构异常（{path.name}）：顶层应为 JSON 对象")
    version = doc.get("format_version")
    if version != FORMAT_VERSION:
        raise ValueError(f"工程文件版本不支持：{version}（当前支持 {FORMAT_VERSION}）")
    items = []
    for i, it in enumerate(doc.get("items") or []):
        if not isinstance(it, dict) or not it.get("template_id"):
            raise ValueError(
                f"工程文件损坏：第 {i + 1} 个计算项缺少 template_id（{path.name}）")
        items.append(CalcItem(
            name=str(it.get("name", "")),
            template_id=it["template_id"],
            template_hash=it.get("template_hash", ""),
            params=it.get("params", {}),
            id=it.get("id") or uuid.uuid4().hex[:12],
            deps=it.get("deps", {}),
        ))
    return Project(
        name=doc.get("name", "未命名工程"),
        items=items,
        views=doc.get("views", {}),
    )


__all__ += ["file_hash"]  # re-export：工程侧校验 hash 与 loader 同源
