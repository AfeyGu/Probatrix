"""后端核心验证：模板目录加载/刷新/报错隔离、计算执行报错捕获、工程文件读写。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from calcbook.engine import run_template
from calcbook.loader import TemplateLoader, file_hash
from calcbook.project import (
    CalcItem,
    new_project,
    load_project,
    save_project,
)

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


# ----------------------------------------------------------------------
# loader：目录扫描
# ----------------------------------------------------------------------
def _load_example(name: str):
    path = EXAMPLES / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def tpl_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离的模板目录：装入示例 gl.py，并把 examples 目录从 sys.path 移除干扰。"""
    (tmp_path / "gl.py").write_text(
        (EXAMPLES / "gl.py").read_text(encoding="utf-8"), encoding="utf-8",
    )
    return tmp_path


def test_loader_scans_and_fills_id(tpl_dir: Path) -> None:
    loader = TemplateLoader(tpl_dir)
    loader.scan()
    assert "gl.calc" in loader.entries
    assert loader.errors == []
    entry = loader.entries["gl.calc"]
    assert entry.meta.name == "钢梁强度验算"
    assert entry.hash == file_hash(tpl_dir / "gl.py")
    assert len(entry.hash) == 64


def test_loader_rerun_is_idempotent(tpl_dir: Path) -> None:
    loader = TemplateLoader(tpl_dir)
    loader.scan()
    loader.scan()
    assert list(loader.entries) == ["gl.calc"]


def test_loader_refresh_picks_up_edits(tpl_dir: Path) -> None:
    loader = TemplateLoader(tpl_dir)
    loader.scan()
    src = (tpl_dir / "gl.py").read_text(encoding="utf-8")
    (tpl_dir / "gl.py").write_text(
        src.replace('template("钢梁强度验算"', 'template("钢梁强度验算V2"'),
        encoding="utf-8",
    )
    loader.scan()                                # 不重启、直接刷新
    assert loader.entries["gl.calc"].meta.name == "钢梁强度验算V2"


def test_loader_error_isolation(tmp_path: Path) -> None:
    (tmp_path / "gl.py").write_text(
        (EXAMPLES / "gl.py").read_text(encoding="utf-8"), encoding="utf-8",
    )
    (tmp_path / "bad.py").write_text("raise RuntimeError('故意坏文件')\n", encoding="utf-8")
    loader = TemplateLoader(tmp_path)
    loader.scan()
    assert "gl.calc" in loader.entries           # 好文件不受影响
    assert len(loader.errors) == 1
    assert loader.errors[0].file.name == "bad.py"
    assert "故意坏文件" in loader.errors[0].error  # traceback 原样可读


def test_loader_plain_data_module(tmp_path: Path) -> None:
    """数据模块（如 Hsteel.py）+ 模板内普通 import 引用它：两条路都通。"""
    (tmp_path / "gl.py").write_text(
        (EXAMPLES / "gl.py").read_text(encoding="utf-8"), encoding="utf-8",
    )
    (tmp_path / "Hsteel.py").write_text("TABLE = {'HN400x200': {'Wx': 3.0e6}}\n", encoding="utf-8")
    (tmp_path / "use_dep.py").write_text(
        "import Hsteel\n"                      # 模板引同目录数据模块
        "from pydantic import BaseModel\n"
        "from calcbook import CalcBook, template\n"
        "class P(BaseModel):\n"
        "    model: str = 'HN400x200'\n"
        "@template('用依赖的模板')\n"
        "def calc(p: P) -> CalcBook:\n"
        "    return CalcBook().p(str(Hsteel.TABLE[p.model]['Wx']))\n",
        encoding="utf-8",
    )
    loader = TemplateLoader(tmp_path)
    loader.scan()
    assert loader.errors == []
    assert set(loader.entries) == {"gl.calc", "use_dep.calc"}
    # 数据模块被普通 import 解析，模板内可用
    result = run_template(loader.entries["use_dep.calc"].meta, {})
    assert result.ok and "3000000.0" in result.md


def test_loader_data_modules_do_not_leak_across_dirs(tmp_path: Path) -> None:
    """A、B 两个模板目录各有同名数据模块：各自拿到自己目录的表。

    曾踩坑：先扫 A 后扫 B，B 的模板 import 命中 sys.modules 里 A 的缓存，
    静默算错数（_forget_dir_modules 当时只清当前目录）。
    """
    tpl = (
        "import Hsteel\n"
        "from pydantic import BaseModel\n"
        "from calcbook import CalcBook, template\n"
        "class P(BaseModel):\n"
        "    x: float = 1\n"
        "@template('用数据模块')\n"
        "def calc(p: P) -> CalcBook:\n"
        "    return CalcBook().p(str(Hsteel.WX))\n"
    )
    dirs = []
    for name, wx in (("a", 1111), ("b", 2222)):
        d = tmp_path / name
        d.mkdir()
        (d / "Hsteel.py").write_text(f"WX = {wx}\n", encoding="utf-8")
        (d / "t.py").write_text(tpl, encoding="utf-8")
        dirs.append(d)

    la, lb = TemplateLoader(dirs[0]), TemplateLoader(dirs[1])
    la.scan()
    lb.scan()
    assert "2222" in run_template(lb.entries["t.calc"].meta, {}).md   # B 用自己的表
    # 再扫回 A：必须重新拿到自己的表（而不是 B 留在缓存里的）
    la.scan()
    assert "1111" in run_template(la.entries["t.calc"].meta, {}).md
    assert str(dirs[0]) in sys.path                  # 当前目录在 sys.path
    assert str(dirs[1]) not in sys.path              # 旧模板目录已移除


# ----------------------------------------------------------------------
# engine：计算执行与报错
# ----------------------------------------------------------------------
def _gl_meta():
    mod = _load_example("gl")
    return next(
        m.__calcbook_template__ for m in vars(mod).values()
        if hasattr(m, "__calcbook_template__")
    )


def test_run_template_success() -> None:
    result = run_template(_gl_meta(), {})
    assert result.ok is True
    assert result.error == ""
    assert result.all_ok is True
    assert result.max_ratio == pytest.approx(0.443, abs=1e-3)
    assert result.checks[0]["name"] == "抗弯强度"
    assert "验算项" in result.md                 # 末尾结论表


def test_run_template_validation_error() -> None:
    result = run_template(_gl_meta(), {"fy": 0})
    assert result.ok is False
    assert result.error_title == "参数校验失败"
    assert "fy" in result.error                  # 校验详情可见


def test_run_template_crash_captured(tmp_path: Path) -> None:
    """计算中途抛异常：traceback 原样进 error，不向上抛。"""
    (tmp_path / "crash.py").write_text(
        "from pydantic import BaseModel\n"
        "from calcbook import CalcBook, template\n"
        "class P(BaseModel):\n"
        "    x: float = 1\n"
        "@template('崩')\n"
        "def calc(p: P) -> CalcBook:\n"
        "    return 1 / 0\n",
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location("crash", tmp_path / "crash.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    meta = mod.calc.__calcbook_template__
    result = run_template(meta, {})
    assert result.ok is False
    assert result.error_title == "计算出错"
    assert "ZeroDivisionError" in result.error


def test_run_template_duck_object_does_not_raise() -> None:
    """模板返回带 to_html 但缺 checks 的鸭子对象：结果读取失败进 RunResult，不抛。

    run_template 的契约是「永不抛异常」；from_book 曾在这类对象上让
    AttributeError 逃逸、把 API 变成 500。
    """
    from pydantic import BaseModel

    from calcbook.template import TemplateMeta

    class P(BaseModel):
        x: float = 1.0

    class Duck:                       # 有渲染方法，但没有 checks/max_ratio
        def to_html(self) -> str:
            return ""

        def to_markdown(self) -> str:
            return ""

    result = run_template(
        TemplateMeta(name="X", func=lambda p: Duck(), params_model=P), {})
    assert result.ok is False
    assert result.error_title == "计算结果读取失败"
    assert "AttributeError" in result.error


# ----------------------------------------------------------------------
# project：.cbproj 读写
# ----------------------------------------------------------------------
def test_project_roundtrip(tmp_path: Path) -> None:
    proj = new_project("测试工程")
    proj.items.append(CalcItem(
        name="GL-1", template_id="gl.calc",
        template_hash="a" * 64,
        params={"Mx": 100, "steel": "Q235B"},
    ))
    proj.items.append(CalcItem(
        name="GL-2", template_id="gl.calc",
        template_hash="a" * 64,
        params={"Mx": 150},
    ))
    proj.views["gl.calc"] = {"hidden_cols": ["fy"]}
    path = save_project(proj, tmp_path / "t.cbproj")

    text = path.read_text(encoding="utf-8")
    assert '"format_version": 1' in text
    assert '"GL-1"' in text                      # 人类可读、中文不转义

    back = load_project(path)
    assert back.name == "测试工程"
    assert [it.name for it in back.items] == ["GL-1", "GL-2"]
    assert back.items[0].params["Mx"] == 100
    assert back.views["gl.calc"]["hidden_cols"] == ["fy"]
    # id 稳定复现
    assert [it.id for it in back.items] == [it.id for it in proj.items]


def test_project_rejects_unknown_version(tmp_path: Path) -> None:
    path = tmp_path / "bad.cbproj"
    path.write_text('{"format_version": 99}', encoding="utf-8")
    with pytest.raises(ValueError, match="版本不支持"):
        load_project(path)


def test_save_project_is_atomic_no_tmp_left(tmp_path: Path) -> None:
    """原子写落盘：成功后无 .tmp 残留，内容完整可读回。"""
    proj = new_project("P")
    proj.items.append(CalcItem(
        name="GL-1", template_id="gl.calc", template_hash="", params={}))
    path = save_project(proj, tmp_path / "x.cbproj")
    assert path.is_file()
    assert not (tmp_path / "x.cbproj.tmp").exists()
    assert load_project(path).items[0].name == "GL-1"


def test_load_project_bad_json_readable(tmp_path: Path) -> None:
    """坏 JSON：给可读的 ValueError（API 层转 400），而不是裸 JSONDecodeError。"""
    path = tmp_path / "bad.cbproj"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="不是有效的 JSON"):
        load_project(path)


def test_load_project_missing_field_readable(tmp_path: Path) -> None:
    """计算项缺 template_id：给出第几项缺什么，而不是 KeyError。"""
    path = tmp_path / "bad.cbproj"
    path.write_text('{"format_version": 1, "items": [{"name": "a"}]}',
                    encoding="utf-8")
    with pytest.raises(ValueError, match="缺少 template_id"):
        load_project(path)


def test_project_hash_matches_loader(tmp_path: Path, tpl_dir: Path) -> None:
    """工程里存的模板 hash 与 loader 算的一致（同源校验）。"""
    loader = TemplateLoader(tpl_dir)
    loader.scan()
    entry = loader.entries["gl.calc"]
    proj = new_project()
    proj.items.append(CalcItem(
        name="GL-1", template_id=entry.meta.template_id,
        template_hash=entry.hash, params={},
    ))
    path = save_project(proj, tmp_path / "p.cbproj")
    back = load_project(path)
    assert back.items[0].template_hash == file_hash(tpl_dir / "gl.py")
