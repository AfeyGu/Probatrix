"""CalcBook —— 结构构件批量计算书工具。

公开 API（模板作者只需 import 这三个名字）::

    from calcbook import CalcBook, Field, template
"""

from .calcbook import CalcBook
from .fields import Field, param_meta
from .template import TemplateMeta, template

__version__ = "0.1.0"

__all__ = ["CalcBook", "Field", "param_meta", "template", "TemplateMeta"]
