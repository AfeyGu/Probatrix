"""工程文件 .cbproj 磁盘格式回归：版本号写入/读取、历史无版本文件按 v1 读、未知版本拒绝、deps 保留。

窄回归：只测 project.py 的落盘契约，不起服务。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from calcbook.project import (
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
    path = save_project(_project(), tmp_path / "中文工程.cbproj")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["format_version"] == FORMAT_VERSION == 1
    assert doc["items"][0]["deps"] == {"Hsteel": "b" * 64}
    assert doc["items"][0]["params"] == {"Mx": 100, "steel": "Q235B"}


def test_round_trip_keeps_deps_and_views(tmp_path: Path) -> None:
    path = save_project(_project(), tmp_path / "p.cbproj")
    back = load_project(path)
    assert back.name == "中文工程名"
    assert back.items[0].deps == {"Hsteel": "b" * 64}
    assert back.items[0].params["steel"] == "Q235B"
    assert back.views == {"gl.calc": {"hidden_cols": ["fy"]}}


# ----------------------------------------------------------------------
# 读：历史无版本文件（旧 Web 落盘）按 v1 接受
# ----------------------------------------------------------------------
def test_load_legacy_file_without_version(tmp_path: Path) -> None:
    path = tmp_path / "legacy.cbproj"
    path.write_text(json.dumps({
        "name": "旧工程",
        "items": [{"id": "x1", "name": "GL-1", "template_id": "gl.calc",
                   "template_hash": "c" * 64, "params": {"Mx": 1},
                   "deps": {}}],
        "views": {},
    }, ensure_ascii=False), encoding="utf-8")

    proj = load_project(path)
    assert proj.name == "旧工程"
    assert proj.items[0].template_id == "gl.calc" and proj.items[0].params == {"Mx": 1}


def test_load_legacy_file_without_deps(tmp_path: Path) -> None:
    """更早的文件连 deps 都没有：读成空 dict，不报错。"""
    path = tmp_path / "older.cbproj"
    path.write_text(json.dumps({"name": "n", "items": [
        {"name": "GL-1", "template_id": "gl.calc", "template_hash": "", "params": {}},
    ]}), encoding="utf-8")
    assert load_project(path).items[0].deps == {}


# ----------------------------------------------------------------------
# 读：明确的未知版本继续拒绝（不能当成 v1 猜）
# ----------------------------------------------------------------------
@pytest.mark.parametrize("version", [None, 0, 2, 99, "1", 1.5])
def test_load_unknown_version_rejected(tmp_path: Path, version) -> None:
    path = tmp_path / "future.cbproj"
    path.write_text(json.dumps({
        "format_version": version, "name": "未来", "items": [], "views": {},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="版本不支持"):
        load_project(path)
