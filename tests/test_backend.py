"""后端核心验证：模板目录加载/刷新/报错隔离、计算执行报错捕获、工程文件读写。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from probatrix.engine import run_template
from probatrix.loader import TemplateLoader, file_hash
from probatrix.project import (
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
        "from probatrix import Probatrix, template\n"
        "class P(BaseModel):\n"
        "    model: str = 'HN400x200'\n"
        "@template('用依赖的模板')\n"
        "def calc(p: P) -> Probatrix:\n"
        "    return Probatrix().p(str(Hsteel.TABLE[p.model]['Wx']))\n",
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
        "from probatrix import Probatrix, template\n"
        "class P(BaseModel):\n"
        "    x: float = 1\n"
        "@template('用数据模块')\n"
        "def calc(p: P) -> Probatrix:\n"
        "    return Probatrix().p(str(Hsteel.WX))\n"
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
# loader：文件夹模板（<名>/template.py）与单文件模板并存
# ----------------------------------------------------------------------
FOLDER_TPL = """\
from pydantic import BaseModel
from probatrix import Probatrix, template
from .materials import WX

class P(BaseModel):
    n: float = 1.0

@template("文件夹模板")
def calc(p: P) -> Probatrix:
    from .extra import FACTOR       # 懒导入：调用时才解析，也属相对导入
    return Probatrix().p(str(WX * p.n * FACTOR))
"""


def _folder_template(root: Path, folder: str = "steel", wx: float = 21,
                     factor: float = 2) -> Path:
    """在 root 下建文件夹模板 <folder>/template.py 及配套私有模块、资源目录。"""
    d = root / folder
    (d / "images").mkdir(parents=True)
    (d / "template.py").write_text(FOLDER_TPL, encoding="utf-8")
    (d / "materials.py").write_text(f"WX = {wx}\n", encoding="utf-8")
    (d / "extra.py").write_text(f"FACTOR = {factor}\n", encoding="utf-8")
    (d / "images" / "section.png").write_bytes(b"png")
    return d


def test_loader_folder_template_uses_folder_name_as_stem(tmp_path: Path) -> None:
    """<名>/template.py 的模板 id = <名>.函数名——老工程按 id 引用，不能变成 template.calc。"""
    _folder_template(tmp_path)
    loader = TemplateLoader(tmp_path)
    loader.scan()
    assert loader.errors == []
    assert list(loader.entries) == ["steel.calc"]
    entry = loader.entries["steel.calc"]
    assert entry.meta.name == "文件夹模板"
    assert entry.file == tmp_path / "steel" / "template.py"
    # hash 只覆盖入口文件：资源与私有模块改了不该判成模板变了
    assert entry.hash == file_hash(tmp_path / "steel" / "template.py")


def test_loader_two_layouts_coexist_files_first_then_folders(tmp_path: Path) -> None:
    """两种布局并存：先单文件（按文件名，同旧行为），再文件夹（按名字）。"""
    (tmp_path / "gl.py").write_text(
        (EXAMPLES / "gl.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "aaa.py").write_text(
        (EXAMPLES / "stair.py").read_text(encoding="utf-8"), encoding="utf-8")
    _folder_template(tmp_path, folder="document")
    loader = TemplateLoader(tmp_path)
    loader.scan()
    assert loader.errors == []
    assert list(loader.entries)[:2] == ["aaa.calc", "gl.calc"]   # 单文件按文件名，顺序不乱
    assert list(loader.entries)[-1] == "document.calc"            # 文件夹排在单文件之后


def test_loader_folder_template_private_modules(tmp_path: Path) -> None:
    """私有模块用 `from .materials import ...`：顶层与懒导入都通，不靠 sys.path。"""
    _folder_template(tmp_path, wx=21, factor=2)
    loader = TemplateLoader(tmp_path)
    loader.scan()
    assert loader.errors == []
    result = run_template(loader.entries["steel.calc"].meta, {})
    assert result.ok, result.error
    assert "42.0" in result.md
    assert str(tmp_path / "steel") not in sys.path    # 文件夹模板不往 sys.path 加目录


def test_loader_folder_template_allows_dot_and_space_in_name(tmp_path: Path) -> None:
    """文件夹名带点或空格：id 直接拼名字（不引入斜杠），相对导入照常可用。"""
    _folder_template(tmp_path, folder="steel.v2")
    _folder_template(tmp_path, folder="图文 计算书")
    loader = TemplateLoader(tmp_path)
    loader.scan()
    assert loader.errors == []
    assert set(loader.entries) == {"steel.v2.calc", "图文 计算书.calc"}
    assert all("/" not in tid for tid in loader.entries)
    for tid in loader.entries:
        result = run_template(loader.entries[tid].meta, {})
        assert result.ok, result.error
        assert "42.0" in result.md


def test_loader_folder_template_ignores_other_py_and_resource_dirs(tmp_path: Path) -> None:
    """只认 <名>/template.py：文件夹里其他 *.py 不扫，没有 template.py 的文件夹不扫。"""
    d = _folder_template(tmp_path)
    (d / "helper.py").write_text(
        "from pydantic import BaseModel\n"
        "from probatrix import Probatrix, template\n"
        "class Q(BaseModel):\n    x: float = 0\n"
        "@template('不该被扫到')\n"
        "def calc(q: Q) -> Probatrix:\n    return Probatrix()\n",
        encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "notes.py").write_text("X = 1\n", encoding="utf-8")
    loader = TemplateLoader(tmp_path)
    loader.scan()
    assert loader.errors == []
    assert list(loader.entries) == ["steel.calc"]


def test_loader_same_stem_conflict_keeps_single_file(tmp_path: Path) -> None:
    """gl.py 与 gl/template.py 同名：保留单文件，文件夹报可读错误（不悄悄接管）。"""
    (tmp_path / "gl.py").write_text(
        (EXAMPLES / "gl.py").read_text(encoding="utf-8"), encoding="utf-8")
    _folder_template(tmp_path, folder="gl")
    loader = TemplateLoader(tmp_path)
    loader.scan()
    assert list(loader.entries) == ["gl.calc"]
    assert loader.entries["gl.calc"].meta.name == "钢梁强度验算"     # 来自单文件
    assert loader.entries["gl.calc"].file == tmp_path / "gl.py"
    assert len(loader.errors) == 1
    err = loader.errors[0]
    assert err.file == tmp_path / "gl" / "template.py"
    assert "同名冲突" in err.error
    assert "gl.py" in err.error and "template.py" in err.error
    assert "Traceback" not in err.error                  # 给人看的说明，不是栈


def test_loader_folder_template_sees_root_data_module(tmp_path: Path) -> None:
    """文件夹模板里 `import Hsteel` 仍指向模板目录根部的数据表（老做法不变）。"""
    d = _folder_template(tmp_path)
    (d / "template.py").write_text(
        FOLDER_TPL.replace("return Probatrix().p(str(WX * p.n * FACTOR))",
                           "import Hsteel\n"
                           "    return Probatrix().p(str(Hsteel.WX + WX * p.n * FACTOR))"),
        encoding="utf-8")
    (tmp_path / "Hsteel.py").write_text("WX = 7\n", encoding="utf-8")
    loader = TemplateLoader(tmp_path)
    loader.scan()
    assert loader.errors == []
    result = run_template(loader.entries["steel.calc"].meta, {})
    assert result.ok, result.error
    assert "49.0" in result.md                           # 7 + 21*2


def test_loader_folder_private_data_does_not_leak_across_dirs(tmp_path: Path) -> None:
    """两个模板目录各有 steel/：各用自己的 materials.py；刷新后同样各归各。"""
    dirs = []
    for name, wx in (("a", 1111), ("b", 2222)):
        d = tmp_path / name
        d.mkdir()
        _folder_template(d, wx=wx, factor=1)
        dirs.append(d)

    la, lb = TemplateLoader(dirs[0]), TemplateLoader(dirs[1])
    la.scan()
    lb.scan()
    assert "2222" in run_template(lb.entries["steel.calc"].meta, {}).md
    assert "1111" in run_template(la.entries["steel.calc"].meta, {}).md   # 没被 B 顶掉


def test_loader_folder_lazy_relative_import_survives_other_loader(tmp_path: Path) -> None:
    """两个目录各扫一次后，各自文件夹的懒导入仍取自己的 materials。

    模块名带文件夹路径哈希，扫 B 时不拆 A 的模块——否则先加载的模板在算第二次时
    `from .materials import ...` 要么报找不到，要么悄悄用另一个文件夹的表。
    """
    lazy = (
        "from pydantic import BaseModel\n"
        "from probatrix import Probatrix, template\n"
        "class P(BaseModel):\n    n: float = 1.0\n"
        "@template('懒导入文件夹模板')\n"
        "def calc(p: P) -> Probatrix:\n"
        "    from .materials import WX\n"
        "    return Probatrix().p(str(WX))\n"
    )
    dirs = []
    for name, wx in (("a", 1111), ("b", 2222)):
        d = tmp_path / name
        (d / "steel").mkdir(parents=True)
        (d / "steel" / "template.py").write_text(lazy, encoding="utf-8")
        (d / "steel" / "materials.py").write_text(f"WX = {wx}\n", encoding="utf-8")
        dirs.append(d)

    la, lb = TemplateLoader(dirs[0]), TemplateLoader(dirs[1])
    la.scan()
    lb.scan()
    assert "1111" in run_template(la.entries["steel.calc"].meta, {}).md
    assert "2222" in run_template(lb.entries["steel.calc"].meta, {}).md


def test_loader_folder_refresh_reloads_private_modules(tmp_path: Path) -> None:
    """改 materials.py 后直接 scan()：私有模块必须重新导入，不拿旧缓存。"""
    d = _folder_template(tmp_path, wx=1, factor=1)
    loader = TemplateLoader(tmp_path)
    loader.scan()
    assert "1.0" in run_template(loader.entries["steel.calc"].meta, {}).md
    (d / "materials.py").write_text("WX = 500\n", encoding="utf-8")
    loader.scan()
    assert "500.0" in run_template(loader.entries["steel.calc"].meta, {}).md


# ----------------------------------------------------------------------
# engine：计算执行与报错
# ----------------------------------------------------------------------
def _gl_meta():
    mod = _load_example("gl")
    return next(
        m.__probatrix_template__ for m in vars(mod).values()
        if hasattr(m, "__probatrix_template__")
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
        "from probatrix import Probatrix, template\n"
        "class P(BaseModel):\n"
        "    x: float = 1\n"
        "@template('崩')\n"
        "def calc(p: P) -> Probatrix:\n"
        "    return 1 / 0\n",
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location("crash", tmp_path / "crash.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    meta = mod.calc.__probatrix_template__
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

    from probatrix.template import TemplateMeta

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
# project：.pbproj 读写
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
    path = save_project(proj, tmp_path / "t.pbproj")

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
    path = tmp_path / "bad.pbproj"
    path.write_text('{"format_version": 99}', encoding="utf-8")
    with pytest.raises(ValueError, match="版本不支持"):
        load_project(path)


def test_save_project_is_atomic_no_tmp_left(tmp_path: Path) -> None:
    """原子写落盘：成功后无 .tmp 残留，内容完整可读回。"""
    proj = new_project("P")
    proj.items.append(CalcItem(
        name="GL-1", template_id="gl.calc", template_hash="", params={}))
    path = save_project(proj, tmp_path / "x.pbproj")
    assert path.is_file()
    assert not (tmp_path / "x.pbproj.tmp").exists()
    assert load_project(path).items[0].name == "GL-1"


def test_load_project_bad_json_readable(tmp_path: Path) -> None:
    """坏 JSON：给可读的 ValueError（API 层转 400），而不是裸 JSONDecodeError。"""
    path = tmp_path / "bad.pbproj"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="不是有效的 JSON"):
        load_project(path)


def test_load_project_missing_field_readable(tmp_path: Path) -> None:
    """计算项缺 template_id：给出第几项缺什么，而不是 KeyError。"""
    path = tmp_path / "bad.pbproj"
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
    path = save_project(proj, tmp_path / "p.pbproj")
    back = load_project(path)
    assert back.items[0].template_hash == file_hash(tpl_dir / "gl.py")
