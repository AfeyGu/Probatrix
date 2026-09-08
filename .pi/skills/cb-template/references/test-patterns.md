# CalcBook 模板测试模式

写完模板后，按本文档的两层测试验证。两层都过才能算「完成」。

---

## 1. 单元：契约 + 端到端测试

照 CalcBook 项目的 `tests/test_contract.py` 末尾 `test_example_gl_end_to_end` 的写法，
给新模板加一个 `test_xxx_end_to_end`。

**测试文件位置**：项目根目录 `tests/test_xxx.py`（与模板同名）。
**如果没有 CalcBook 项目目录**（独立环境），可以单独建 `test_xxx.py` 放在模板同目录，
但要保证 `from calcbook import ...` 能 import（`pip install calcbook` 后即可）。

### 1.1 最小测试模板

```python
"""<模板名> 端到端契约测试。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from calcbook import CalcBook


def _load_template(name: str, path: Path):
    """从 .py 文件 importlib 加载模板（不依赖包结构）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _find_template_meta(mod):
    metas = [m.__calcbook_template__ for m in vars(mod).values()
             if hasattr(m, "__calcbook_template__")]
    assert len(metas) == 1, f"应只有一个 @template，实际 {len(metas)} 个"
    return metas[0]


TEMPLATE_PATH = Path(__file__).parent / "xxx.py"   # 改成你的模板路径


def test_xxx_default_params_pass() -> None:
    """默认参数应满足。"""
    meta = _find_template_meta(_load_template("xxx", TEMPLATE_PATH))
    book = meta.run(meta.make_params({}))
    md = book.to_markdown()
    # 三件套断言
    assert "# <标题>" in md
    assert "## 1. <章节>" in md
    assert "**满足**" in md
    # 结论表
    assert "| 验算项" in md
    # 属性
    assert book.all_ok is True
    assert book.max_ratio is not None
    assert book.max_ratio < 1.0


def test_xxx_overload_fails() -> None:
    """故意越界应不满足。"""
    meta = _find_template_meta(_load_template("xxx", TEMPLATE_PATH))
    # 选一个会让 check 不满足的参数组合
    book = meta.run(meta.make_params({<越界参数>}))
    md = book.to_markdown()
    assert "**不满足**" in md
    assert book.all_ok is False
    assert book.max_ratio > 1.0


def test_xxx_invalid_param_rejected() -> None:
    """声明里的 gt/ge/le 校验应生效。"""
    from pydantic import ValidationError
    meta = _find_template_meta(_load_template("xxx", TEMPLATE_PATH))
    with pytest.raises(ValidationError):
        meta.make_params({<故意非法参数>})            # 例如 fy=0 触发 gt=0


def test_xxx_cite_present() -> None:
    """每个 check 都应带 cite（结论表才有「依据」列）。"""
    meta = _find_template_meta(_load_template("xxx", TEMPLATE_PATH))
    book = meta.run(meta.make_params({}))
    assert len(book.checks) >= 1
    for c in book.checks:
        assert c.get("cite"), f"check '{c.get('name')}' 缺 cite"
```

### 1.2 跑测试

```bash
# 在 CalcBook 项目根目录
python -m pytest tests -q

# 只跑新加的
python -m pytest tests/test_xxx.py -q
```

**期望**：原有测试 + 你的新测试全绿。任何红先修，不准带病过阶段。

### 1.3 断言要写什么

| 断言 | 检查什么 | 失败说明 |
|---|---|---|
| `"# <title>" in md` | `CalcBook(title=...)` 生效 | 漏了 title 或算式里 # 撞车 |
| `"## 1. ..." in md` | `h2("1. ...")` 生效 | 漏了 h2 或编号格式错 |
| `"**满足**" in md` 或 `"**不满足**" in md` | `check` 渲染了判定行 | 漏了 check 或条件没触发 |
| `"\| 验算项" in md` | 末尾结论汇总表存在 | 没有任何 check |
| `book.all_ok` 是 bool | check 闭环正确 | check 的 op/limit 写反了 |
| `book.max_ratio` 是 float | 至少一个 check | 漏了 check |
| `c.get("cite")` 都有值 | 每个 check 都有依据 | 漏 cite（反模式 §9） |

---

## 2. 端到端：起服务 + curl 冒烟

### 2.1 起服务

```bash
# 模板在 examples/ 下
calcbook serve --templates examples --port 8317 --no-browser

# 模板在别处
calcbook serve --templates <你的模板目录> --port 8317 --no-browser
```

等出现 `Uvicorn running on http://127.0.0.1:8317` 再继续。

### 2.2 curl 验真

```bash
# 1. 模板出现
curl -s http://127.0.0.1:8317/api/templates \
  | python -m json.tool \
  | grep "<你的 template_id>"        # 形如 "gl.calc"

# 2. 默认参数能跑
curl -s -X POST http://127.0.0.1:8317/api/run \
  -H "Content-Type: application/json" \
  -d "{\"template_id\": \"<你的 template_id>\", \"params\": {}}"
# 期望返回 JSON 里 result.error 为空字符串，
# result.max_ratio 是数字，result.markdown 含计算书全文

# 3. 越界参数应不满足
curl -s -X POST http://127.0.0.1:8317/api/run \
  -H "Content-Type: application/json" \
  -d "{\"template_id\": \"<你的 template_id>\", \"params\": {<越界参数>}}"
# 期望 result.all_ok == false，或 result.max_ratio > 1.0
```

### 2.3 报错可见性自检（推荐）

临时把公式改坏（例如把 `b.formula` 注释掉，或把分母改成 0）→
重跑 2.2 的第 2 步 → 确认返回 JSON 的 `result.error` 含完整 Python traceback。
**改回后必须再跑一遍 2.2 确认恢复**。

模板作者的调试界面就是这个 traceback——它必须真的出现在前端/响应里。

### 2.4 关服务

```bash
# Windows（按端口找 PID，不要 taskkill /IM python.exe）
netstat -ano | findstr :8317
taskkill /F /PID <pid>

# Linux / macOS
lsof -ti:8317 | xargs kill -9
```

---

## 3. 完整度勾选

阶段 4 通过条件（**每条都要打勾**）：

- [ ] `python -m pytest tests -q` 全绿
- [ ] `GET /api/templates` 列出新模板
- [ ] `POST /api/run` 默认参数 → `error=""` + `all_ok=true`
- [ ] `POST /api/run` 越界参数 → `all_ok=false` + `max_ratio > 1.0`
- [ ] 临时改坏 → traceback 出现在响应 → 改回 → 仍绿
- [ ] 服务已关（端口释放）

---

## 4. 没有 pytest / 没有服务时的最低验证

如果没有 CalcBook 项目环境（独立 .py），最低验证：

```python
# 在模板同目录写一个 smoke.py
import importlib.util, sys
spec = importlib.util.spec_from_file_location("xxx", "xxx.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
meta = next(m.__calcbook_template__ for m in vars(mod).values()
            if hasattr(m, "__calcbook_template__"))
book = meta.run(meta.make_params({}))
print("max_ratio:", book.max_ratio)
print("all_ok:", book.all_ok)
print("markdown 长度:", len(book.to_markdown()))
assert book.all_ok
assert book.max_ratio is not None
```

跑 `python smoke.py` 不抛异常即过。装上 `pip install calcbook` 就能跑（不需要克隆项目）。
