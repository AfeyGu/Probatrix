"""发布一致性：pyproject / calcbook.__version__ 版本号必须同步。

教训：0.1.0a10→a11 升级时漏改 __init__.py；旧离线包时代启动器还持有
EXPECTED_VERSION 校验 venv 内版本，漏改会导致每次启动都重装 wheel。
现离线包整包替换、启动器不再持有版本号，本测试只保证前两者一致。
"""

from __future__ import annotations

import re
from pathlib import Path

import calcbook

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_version_matches_package() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'version = "([^"]+)"', text)
    assert m, "pyproject.toml 里找不到 version"
    assert m.group(1) == calcbook.__version__
