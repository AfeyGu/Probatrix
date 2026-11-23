"""Probatrix —— 结构构件批量计算书工具。

公开 API（模板作者只需 import 这三个名字）::

    from probatrix import Probatrix, Field, template
"""

from .probatrix import Probatrix
from .fields import Field, param_meta
from .template import TemplateMeta, template

__version__ = "0.1.0a13"

__all__ = ["Probatrix", "Field", "param_meta", "template", "TemplateMeta"]
