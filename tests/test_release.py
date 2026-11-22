"""发布包名称与 Python 包对外提供的版本号保持一致。"""

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
