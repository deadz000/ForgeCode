"""Memory 子包测试：Store CRUD、Manager 索引加载/截断/更新。"""

from __future__ import annotations

import os

from forgecode.memory.store import Store
from forgecode.memory.types import NoteType, UpdateAction


def _make_create_action(**kwargs) -> UpdateAction:
    defaults = {
        "action": "create",
        "level": "project",
        "type": "project_knowledge",
        "title": "项目用中文回复",
        "slug": "chinese_replies",
        "content": "用户要求所有回复使用简体中文。",
    }
    defaults.update(kwargs)
    return UpdateAction(**defaults)


def _make_update_action(**kwargs) -> UpdateAction:
    defaults = {
        "action": "update",
        "level": "project",
        "filename": "project_knowledge_chinese_replies.md",
        "title": "项目用中文回复（更新）",
        "content": "用户要求所有回复使用简体中文，且不使用繁体。",
    }
    defaults.update(kwargs)
    return UpdateAction(**defaults)


def _make_delete_action(**kwargs) -> UpdateAction:
    defaults = {
        "action": "delete",
        "level": "project",
        "filename": "project_knowledge_chinese_replies.md",
    }
    defaults.update(kwargs)
    return UpdateAction(**defaults)


# ── Store 测试 ────────────────────────────────────


def test_store_create_note(tmp_path):
    """apply create → 文件存在、frontmatter 正确、MEMORY.md 有对应行。"""
    store = Store(str(tmp_path))
    action = _make_create_action()
    store.apply([action])

    # 文件存在
    note_path = os.path.join(str(tmp_path), "project_knowledge_chinese_replies.md")
    assert os.path.isfile(note_path)

    # frontmatter 正确
    content = open(note_path, encoding="utf-8").read()
    assert "type: project_knowledge" in content
    assert "title: 项目用中文回复" in content
    assert "created:" in content
    assert "updated:" in content
    assert "用户要求所有回复使用简体中文" in content

    # MEMORY.md 有对应行
    index_path = os.path.join(str(tmp_path), "MEMORY.md")
    assert os.path.isfile(index_path)
    index_content = open(index_path, encoding="utf-8").read()
    assert "项目用中文回复" in index_content


def test_store_update_note(tmp_path):
    """apply update → 文件内容更新、MEMORY.md 对应行更新。"""
    store = Store(str(tmp_path))

    # 先创建
    store.apply([_make_create_action()])

    # 再更新
    update_action = _make_update_action()
    store.apply([update_action])

    note_path = os.path.join(str(tmp_path), "project_knowledge_chinese_replies.md")
    content = open(note_path, encoding="utf-8").read()
    assert "简体中文，且不使用繁体" in content
    assert "created:" in content  # created 保留
    assert "updated:" in content


def test_store_delete_note(tmp_path):
    """apply delete → 文件不存在、MEMORY.md 对应行消失。"""
    store = Store(str(tmp_path))

    # 先创建
    store.apply([_make_create_action()])

    # 再删除
    store.apply([_make_delete_action()])

    note_path = os.path.join(str(tmp_path), "project_knowledge_chinese_replies.md")
    assert not os.path.isfile(note_path)

    # MEMORY.md 对应行消失
    index_path = os.path.join(str(tmp_path), "MEMORY.md")
    if os.path.isfile(index_path):
        index_content = open(index_path, encoding="utf-8").read()
        assert "项目用中文回复" not in index_content


def test_store_load_index_empty(tmp_path):
    """空目录 → load_index 返回空字符串。"""
    store = Store(str(tmp_path))
    assert store.load_index() == ""


def test_store_load_index_after_create(tmp_path):
    """创建笔记后 load_index 有内容。"""
    store = Store(str(tmp_path))
    store.apply([_make_create_action()])
    idx = store.load_index()
    assert len(idx) > 0


def test_store_ensure_dir(tmp_path):
    """ensure_dir 创建目录。"""
    d = os.path.join(str(tmp_path), "sub", "deep")
    store = Store(d)
    store.ensure_dir()
    assert os.path.isdir(d)


# ── Manager 测试 ──────────────────────────────────


def test_manager_load_index_empty(tmp_path):
    """空两级目录 → load_index 返回空字符串。"""
    from forgecode.memory.manager import Manager

    project_dir = str(tmp_path / "proj_mem")
    user_dir = str(tmp_path / "user_mem")
    mgr = Manager(project_dir=project_dir, user_dir=user_dir)
    assert mgr.load_index() == ""


def test_manager_load_index_merged(tmp_path):
    """两级各有索引 → 合并返回，项目级在前。"""
    from forgecode.memory.manager import Manager

    project_dir = str(tmp_path / "proj_mem")
    user_dir = str(tmp_path / "user_mem")

    # 创建两级存储
    proj_store = Store(project_dir)
    proj_store.apply(
        [
            UpdateAction(
                action="create",
                level="project",
                type="project_knowledge",
                title="项目知识",
                slug="proj_know",
                content="项目相关知识内容。",
            )
        ]
    )

    user_store = Store(user_dir)
    user_store.apply(
        [
            UpdateAction(
                action="create",
                level="user",
                type="user_preference",
                title="用户偏好",
                slug="user_pref",
                content="用户偏好内容。",
            )
        ]
    )

    mgr = Manager(project_dir=project_dir, user_dir=user_dir)
    merged = mgr.load_index()
    assert "项目知识" in merged
    assert "用户偏好" in merged

    # 项目级在前
    idx_proj = merged.index("项目知识")
    idx_user = merged.index("用户偏好")
    assert idx_proj < idx_user


def test_manager_load_index_truncate(tmp_path):
    """构造超 25KB 索引 → 截断 + (index truncated) 标注。"""
    from forgecode.memory.manager import MAX_INDEX_INJECT_BYTES, Manager

    project_dir = str(tmp_path / "proj_mem")
    user_dir = str(tmp_path / "user_mem")

    # 创建一个超大的索引文件
    proj_store = Store(project_dir)
    proj_store.ensure_dir()
    big_content = "x" * (MAX_INDEX_INJECT_BYTES + 5000)
    with open(os.path.join(project_dir, "MEMORY.md"), "w", encoding="utf-8") as f:
        f.write(big_content)

    mgr = Manager(project_dir=project_dir, user_dir=user_dir)
    result = mgr.load_index()
    assert "(index truncated)" in result
    assert len(result.encode("utf-8")) <= MAX_INDEX_INJECT_BYTES + 100  # 留一些余量


def test_manager_set_provider(tmp_path):
    """set_provider 延迟设置。"""
    from forgecode.memory.manager import Manager

    mgr = Manager(
        project_dir=str(tmp_path / "proj"),
        user_dir=str(tmp_path / "user"),
    )
    assert mgr._provider is None

    # Mock provider using simple object
    from unittest.mock import Mock

    mock_provider = Mock()
    mock_provider.config.model = "test-model"

    mgr.set_provider(mock_provider, "test-model")
    assert mgr._provider is not None
    assert mgr._model == "test-model"


def test_update_action_parse():
    """验证 UpdateAction 结构。"""
    a = _make_create_action()
    assert a.action == "create"
    assert a.level == "project"
    assert a.type == "project_knowledge"
    assert a.filename == ""  # create 时 filename 可选


def test_note_types():
    """验证 NoteType 枚举。"""
    assert NoteType.USER_PREFERENCE == "user_preference"
    assert NoteType.CORRECTION_FEEDBACK == "correction_feedback"
    assert NoteType.PROJECT_KNOWLEDGE == "project_knowledge"
    assert NoteType.REFERENCE_MATERIAL == "reference_material"
