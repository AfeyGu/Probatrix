"""工程文件 .pbproj 的版本校验、读写往返和 deps 保留。

窄回归：只测 project.py 的落盘契约，不起服务。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from probatrix.project import (
    FORMAT_VERSION,
    CalcItem,
    Project,
    load_project,
    save_project,
)


def _project() -> Project:
    return Project(
        name="中文工程名",
        items=[
            CalcItem(name="GL-1", template_id="gl.calc", template_hash="a" * 64,
                     params={"Mx": 100, "steel": "Q235B"},
                     deps={"Hsteel": "b" * 64}, id="it0001"),
        ],
        views={"gl.calc": {"hidden_cols": ["fy"]}},
    )


# ----------------------------------------------------------------------
# 写：磁盘格式带版本号与 deps（前端原地保存必须写出同一格式）
# ----------------------------------------------------------------------
def test_save_writes_version_and_deps(tmp_path: Path) -> None:
    path = save_project(_project(), tmp_path / "中文工程.pbproj")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["format_version"] == FORMAT_VERSION == 1
    assert doc["items"][0]["deps"] == {"Hsteel": "b" * 64}
    assert doc["items"][0]["params"] == {"Mx": 100, "steel": "Q235B"}


def test_round_trip_keeps_deps_and_views(tmp_path: Path) -> None:
    path = save_project(_project(), tmp_path / "p.pbproj")
    back = load_project(path)
    assert back.name == "中文工程名"
    assert back.items[0].deps == {"Hsteel": "b" * 64}
    assert back.items[0].params["steel"] == "Q235B"
    assert back.views == {"gl.calc": {"hidden_cols": ["fy"]}}


def test_load_missing_version_rejected(tmp_path: Path) -> None:
    path = tmp_path / "missing-version.pbproj"
    path.write_text('{"name": "工程", "items": [], "views": {}}', encoding="utf-8")

    with pytest.raises(ValueError, match="版本不支持"):
        load_project(path)


@pytest.mark.parametrize("version", [None, True, 0, 2, 99, "1", 1.5])
def test_load_unknown_version_rejected(tmp_path: Path, version) -> None:
    path = tmp_path / "future.pbproj"
    path.write_text(json.dumps({
        "format_version": version, "name": "未来", "items": [], "views": {},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="版本不支持"):
        load_project(path)
