"""模板契约：@template 装饰器与模板元数据。

模板作者用法::

    @template("钢梁强度验算", description="…")
    def calc(p: GLParams) -> CalcBook:
        b = CalcBook()
        ...
        return b

装饰器只在函数上打 `__calcbook_template__` 标记，不做全局注册——
加载器扫描模板目录、import 模块后按标记收集，importlib reload 安全。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel

__all__ = ["TemplateMeta", "template"]


@dataclass
class TemplateMeta:
    """一个计算模板的完整元数据。"""

    name: str                                  # 界面显示名，如「钢梁强度验算」
    func: Callable[..., Any]                   # 计算入口，接收参数实例，返回 CalcBook
    params_model: type[BaseModel]              # 参数声明（Pydantic 模型）
    description: str = ""
    manual: bool = False                       # 仅手动计算开关（迭代试算类模板）
    template_id: str = ""                      # 加载时由加载器填：「文件名.函数名」
    accepts_name: bool = False                 # 模板函数声明了可选 name 形参时为 True
    requires: list[str] = field(default_factory=list)     # 模板声明的第三方库（import 名）
    missing_deps: list[str] = field(default_factory=list) # 环境检查后缺失的库（加载时填）

    def make_params(self, data: dict[str, Any]) -> BaseModel:
        """用参数 JSON 构造参数实例（校验失败抛 pydantic.ValidationError）。"""
        return self.params_model.model_validate(data)

    def run(self, params: BaseModel, name: str = "") -> Any:
        if self.accepts_name:
            return self.func(params, name=name)
        return self.func(params)


def template(
    name: str,
    *,
    description: str = "",
    manual: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """把计算函数标记为 CalcBook 模板。"""

    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        params_model = _first_param_model(func)
        if params_model is None:
            raise TypeError(
                f"模板 {func.__module__}.{func.__qualname__} 的第一个参数必须带 "
                f"Pydantic 模型类型注解（参数声明），如 def calc(p: GLParams)"
            )
        func.__calcbook_template__ = TemplateMeta(
            name=name,
            func=func,
            params_model=params_model,
            description=description,
            manual=manual,
            accepts_name="name" in inspect.signature(func).parameters,
        )
        return func

    return deco


def _first_param_model(func: Callable[..., Any]) -> type[BaseModel] | None:
    """取第一个参数的类型注解，必须是 Pydantic 模型子类。"""
    sig = inspect.signature(func)
    params = [
        p for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if not params:
        return None
    first = params[0].name
    # 注解可能是字符串（模块带 from __future__ import annotations 时），统一解析
    try:
        hints = get_type_hints(func)
    except Exception:
        return None
    ann = hints.get(first)
    if ann is None:
        return None
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann
    return None
