"""项目指令加载器测试：三层加载、@include 展开、边界检测。"""

from __future__ import annotations

from forgecode.instructions import Loader


def test_load_all_empty(tmp_path):
    """三个路径都没有 FORGECODE.md → 返回空字符串。"""
    loader = Loader(project_root=str(tmp_path), user_home=str(tmp_path))
    result = loader.load()
    assert result == ""


def test_load_project_root_only(tmp_path):
    """只在项目根有 FORGECODE.md → 只包含项目根的内容。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "FORGECODE.md").write_text("项目规范", encoding="utf-8")

    loader = Loader(project_root=str(root), user_home=str(tmp_path))
    result = loader.load()
    assert "项目规范" in result


def test_load_three_layers_order(tmp_path):
    """三层加载：高优先级在前。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "FORGECODE.md").write_text("ROOT", encoding="utf-8")
    (root / ".forgecode").mkdir()
    (root / ".forgecode" / "FORGECODE.md").write_text("PROJECT", encoding="utf-8")

    user_home = tmp_path / "home"
    user_home.mkdir()
    (user_home / ".forgecode").mkdir()
    (user_home / ".forgecode" / "FORGECODE.md").write_text("USER", encoding="utf-8")

    loader = Loader(project_root=str(root), user_home=str(user_home))
    result = loader.load()

    # ROOT 应在 PROJECT 之前，PROJECT 在 USER 之前
    idx_root = result.index("ROOT")
    idx_project = result.index("PROJECT")
    idx_user = result.index("USER")
    assert idx_root < idx_project < idx_user


def test_include_basic(tmp_path):
    """@include 正常展开。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "rules").mkdir()
    (root / "rules" / "style.md").write_text("代码风格：缩进用 4 空格", encoding="utf-8")
    (root / "FORGECODE.md").write_text("项目规范\n@include rules/style.md", encoding="utf-8")

    loader = Loader(project_root=str(root))
    result = loader.load()
    assert "代码风格：缩进用 4 空格" in result
    assert "@include" not in result  # 应该被替换


def test_include_nested(tmp_path):
    """@include 嵌套展开：A include B, B include C。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.md").write_text("A\n@include b.md", encoding="utf-8")
    (root / "b.md").write_text("B\n@include c.md", encoding="utf-8")
    (root / "c.md").write_text("C", encoding="utf-8")

    loader = Loader(project_root=str(root))
    # 直接测试 _load_file
    result = loader._load_file(
        str(root / "a.md"), boundary=str(root), depth=1, visited=set()
    )
    assert "A" in result
    assert "B" in result
    assert "C" in result
    assert "@include" not in result


def test_include_max_depth(tmp_path):
    """@include 超过 5 层深度 → 截断并附警告。"""
    root = tmp_path / "proj"
    root.mkdir()
    # 构造链: 0.md → 1.md → 2.md → 3.md → 4.md → 5.md → 6.md
    for i in range(7):
        path = root / f"{i}.md"
        target = f"{i + 1}.md"
        path.write_text(f"level_{i}\n@include {target}", encoding="utf-8")

    loader = Loader(project_root=str(root), max_depth=5)
    result = loader._load_file(
        str(root / "0.md"), boundary=str(root), depth=1, visited=set()
    )
    assert "level_0" in result
    assert "level_4" in result
    # 第 6 层（depth=6）应该被截断，level_5 不应出现
    assert "level_5" not in result
    assert "超过最大嵌套深度" in result


def test_include_cycle_detection(tmp_path):
    """@include 环路检测：A include B, B include A。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.md").write_text("A\n@include b.md", encoding="utf-8")
    (root / "b.md").write_text("B\n@include a.md", encoding="utf-8")

    loader = Loader(project_root=str(root))
    result = loader._load_file(
        str(root / "a.md"), boundary=str(root), depth=1, visited=set()
    )
    assert "A" in result
    assert "B" in result
    assert "检测到环路" in result


def test_include_path_escape(tmp_path):
    """项目级 FORGECODE.md 中 @include 跳出项目根 → 不加载，出现警告。"""
    root = tmp_path / "proj"
    root.mkdir()
    # 尝试 include 上级目录的文件
    outside = tmp_path / "outside.md"
    outside.write_text("SECRET", encoding="utf-8")
    (root / "FORGECODE.md").write_text("项目\n@include ../outside.md", encoding="utf-8")

    loader = Loader(project_root=str(root))
    result = loader.load()
    assert "SECRET" not in result
    assert "路径超出允许范围" in result


def test_include_missing_file(tmp_path):
    """@include 指向不存在的文件 → 静默跳过。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "FORGECODE.md").write_text("项目\n@include nonexistent.md", encoding="utf-8")

    loader = Loader(project_root=str(root))
    result = loader.load()
    assert "项目" in result
    # 不存在的文件静默跳过，无警告


def test_include_binary_file(tmp_path):
    """@include 指向二进制文件 → 跳过并附警告。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "binary.bin").write_bytes(b"\x00\x01\x02\x03")
    (root / "FORGECODE.md").write_text("项目\n@include binary.bin", encoding="utf-8")

    loader = Loader(project_root=str(root))
    result = loader.load()
    assert "项目" in result
    assert "二进制" in result


def test_empty_optional_skipped():
    """空 instructions/memory 时对应模块不在系统提示中。"""
    from forgecode.prompt import build_system_prompt

    result = build_system_prompt("", "")
    assert "自定义指令" not in result
    assert "长期记忆" not in result
    # 固定模块仍存在
    assert "ForgeCode" in result
