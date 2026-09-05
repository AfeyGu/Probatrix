"""参数声明：扩展元信息的 Field 与提取工具。

模板作者用法（契约见 计算书工具文档.md 第三节）：

    from calcbook import Field
    from pydantic import BaseModel

    class GLParams(BaseModel):
        steel: str = Field("Q235B", label="钢材牌号",
                           choices=["Q235B", "Q355B"], group="材料")
        Mx: float = Field(100, label="弯矩设计值", unit="kN·m", group="荷载")
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from pydantic.fields import FieldInfo, PydanticUndefined

__all__ = ["Field", "param_meta"]

#: Field 支持的 CalcBook 扩展元信息键
_META_KEYS = ("label", "unit", "choices", "group")


def Field(  # noqa: N802  # 对齐 pydantic.Field 命名
    default: Any = PydanticUndefined,
    *,
    label: str | None = None,
    unit: str | None = None,
    choices: list | tuple | None = None,
    group: str | None = None,
    **kwargs: Any,
) -> FieldInfo:
    """pydantic.Field 的薄包装，把界面元信息收进 json_schema_extra。

    声明即界面：label（中文名）、unit（单位，展示用）、choices（下拉选项）、
    group（参数分组；批量模式下同组参数可整组「统一设置」）。
    其余参数原样透传 pydantic.Field（如 ge、le、description）。
    """
    extra: dict[str, Any] = dict(kwargs.pop("json_schema_extra", None) or {})
    for key, value in (
        ("label", label),
        ("unit", unit),
        ("choices", list(choices) if choices is not None else None),
        ("group", group),
    ):
        if value is not None:
            extra[key] = value
    return _pydantic_field(default, json_schema_extra=extra or None, **kwargs)


def _pydantic_field(*args: Any, **kwargs: Any) -> FieldInfo:
    from pydantic import Field as _pf

    return _pf(*args, **kwargs)


def param_meta(model: type[BaseModel]) -> list[dict[str, Any]]:
    """按声明顺序提取参数模型的字段元信息，驱动表单/表格列渲染。

    返回项形如::

        {"name": "Mx", "type": "float", "default": 100,
         "label": "弯矩设计值", "unit": "kN·m",
         "choices": [...], "group": "荷载"}
    """
    items: list[dict[str, Any]] = []
    for name, info in model.model_fields.items():
        extra: dict[str, Any] = dict(info.json_schema_extra or {})
        item: dict[str, Any] = {
            "name": name,
            "type": _type_name(info.annotation),
            "default": None if info.default is PydanticUndefined else info.default,
            "required": info.is_required(),
        }
        for key in _META_KEYS:
            if key in extra:
                item[key] = extra[key]
        items.append(item)
    return items


def _type_name(annotation: Any) -> str:
    """类型的展示名：int/float/str/bool 之外的归为 any（MVP 表单按文本处理）。"""
    if annotation in (int, float, str, bool):
        return annotation.__name__
    origin = getattr(annotation, "__origin__", None)
    if annotation is Literal or origin is Literal:
        return "choices"
    return "any"
