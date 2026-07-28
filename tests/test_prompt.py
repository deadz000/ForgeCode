"""系统提示工程化单测：装配顺序、空槽跳过、N1 确定性、双重强化。"""

from __future__ import annotations

from forgecode.prompt import (
    Environment,
    Module,
    assemble_system,
    build_system_prompt,
    fixed_modules,
    gather_environment,
    optional_modules,
    plan_reminder,
    system_reminder,
)

# ── T4.1: 装配顺序 ─────────────────────────────────


def test_assemble_order():
    """固定模块按优先级升序排列，身份段在工具使用段之前。"""
    sys = build_system_prompt()
    # 身份(10) 应在 工具使用(50) 之前
    pos_identity = sys.find("ForgeCode")
    pos_tool_usage = sys.find("工具使用原则")
    assert pos_identity >= 0, "系统提示应含身份标识"
    assert pos_tool_usage >= 0, "系统提示应含工具使用原则"
    assert pos_identity < pos_tool_usage, f"身份({pos_identity})应在工具使用({pos_tool_usage})之前"


def test_modules_separated_by_blank_lines():
    """模块间以空行分隔。"""
    sys = build_system_prompt()
    # 至少有 6 处 "\n\n" 分隔（7个模块）
    assert sys.count("\n\n") >= 6, (
        f"模块应空行分隔，实际只有 {sys.count(chr(10) + chr(10))} 处双换行"
    )


def test_all_seven_modules_present():
    """七个固定模块全部参与装配。"""
    fixed = fixed_modules()
    assert len(fixed) == 7
    names = [m.name for m in fixed]
    assert names == ["身份", "系统约束", "任务模式", "动作执行", "工具使用", "语气风格", "文本输出"]


# ── T4.2: 可选空槽 ─────────────────────────────────


def test_empty_modules_skipped():
    """空 content 模块不出现、不产生多余空行。"""
    mods = [
        Module(name="A", priority=10, content="hello"),
        Module(name="B", priority=20, content=""),  # 空 → 跳过
        Module(name="C", priority=30, content="world"),
        Module(name="D", priority=40, content=""),  # 空 → 跳过
    ]
    result = assemble_system(mods)
    assert "hello" in result
    assert "world" in result
    assert "B" not in result, "空模块名不应出现在输出"
    assert "D" not in result, "空模块名不应出现在输出"
    # 无连续空行
    assert "\n\n\n" not in result, f"不应有连续空行: {repr(result)}"


def test_optional_empty_slots():
    """三个可选空槽 content="" 在 build_system_prompt 中不出现。"""
    sys = build_system_prompt()
    assert "自定义指令" not in sys, "空槽'自定义指令'不应出现在输出"
    assert "已激活 Skill" not in sys, "空槽'已激活 Skill'不应出现在输出"
    assert "长期记忆" not in sys, "空槽'长期记忆'不应出现在输出"


def test_optional_module_count():
    """三个可选空槽均存在但内容为空。"""
    opt = optional_modules()
    assert len(opt) == 3
    assert all(m.content == "" for m in opt)
    assert [m.name for m in opt] == ["自定义指令", "已激活 Skill", "长期记忆"]


# ── T4.3: N1 缓存确定性 ────────────────────────────


def test_deterministic_build():
    """连续两次 build_system_prompt() 结果逐字节相等。"""
    a = build_system_prompt()
    b = build_system_prompt()
    assert a == b, "系统提示必须确定"
    assert len(a) == len(b)


def test_stable_block_independent_of_environment():
    """改变环境信息不改变稳定块内容。"""
    stable = build_system_prompt()

    # 构造两个不同环境不应影响 stable
    env_a = gather_environment("1.0", "gpt-4")
    env_b = gather_environment("2.0", "claude-3")
    stable_a = build_system_prompt()
    stable_b = build_system_prompt()

    assert stable_a == stable
    assert stable_b == stable
    # 环境信息不应混入稳定块
    assert "1.0" not in stable
    assert "gpt-4" not in stable
    assert env_a.render() != env_b.render()  # 环境不同


def test_stable_block_no_temporal_content():
    """稳定块不含日期/git/cwd 等时变内容。"""
    sys = build_system_prompt()
    import os

    cwd = os.getcwd()
    assert cwd not in sys, f"稳定块不应含当前目录: {cwd}"


# ── T4.4: F5 双重强化 ──────────────────────────────


def test_double_reinforcement_edit():
    """系统提示含「编辑前先读取」类表述。"""
    sys = build_system_prompt()
    # 工具使用模块(50) 应强调编辑前必先读取
    assert "编辑前必先读取" in sys or "先读后改" in sys or "必须先通过" in sys, (
        "系统提示应强调编辑前先读取"
    )


def test_double_reinforcement_dedicated_tools():
    """系统提示含「优先用专用工具」表述。"""
    sys = build_system_prompt()
    assert "优先使用专用工具" in sys or "不要用 bash 拼凑" in sys, "系统提示应强调优先使用专用工具"
    # 应提及具体工具名
    assert "read_file" in sys
    assert "glob" in sys
    assert "grep" in sys


# ── T4.5: 环境采集与渲染 ────────────────────────────


def test_environment_render_includes_key_fields():
    """环境信息渲染含关键字段。"""
    env = Environment(
        working_dir="/home/test",
        platform="linux",
        date="2026-01-15",
        git_status="3 个文件有改动",
        version="1.0",
        model="test-model",
    )
    rendered = env.render()
    assert "/home/test" in rendered
    assert "linux" in rendered
    assert "2026-01-15" in rendered
    assert "git" in rendered.lower() or "Git" in rendered
    assert "1.0" in rendered
    assert "test-model" in rendered


def test_environment_render_skips_empty():
    """空值项在渲染中省略。"""
    env = Environment(working_dir="/tmp", platform="", date="", git_status="", version="", model="")
    rendered = env.render()
    assert "/tmp" in rendered
    assert "平台" not in rendered or "platform" not in rendered.lower()


def test_gather_environment_basic():
    """gather_environment 在任意目录不抛异常。"""
    env = gather_environment("test-version", "test-model")
    assert env.working_dir != ""  # 至少应有工作目录
    assert env.platform != ""
    assert env.date != ""
    assert env.version == "test-version"
    assert env.model == "test-model"
    # git_status 可为空（非 git 目录降级）
    assert isinstance(env.git_status, str)


def test_gather_environment_non_git():
    """非 git 目录 git_status 降级为空，不中断。"""
    import os
    import tempfile

    orig = os.getcwd()
    tmpdir = tempfile.mkdtemp()
    try:
        os.chdir(tmpdir)
        env = gather_environment("v1", "m1")
        # 非 git 目录：git_status 应为空或提示干净
        assert isinstance(env.git_status, str)
        rendered = env.render()
        assert tmpdir in rendered
    finally:
        os.chdir(orig)
        # Windows 下需要先切回目录再清理
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


# ── T4.6: 挂载即扩展 ───────────────────────────────


def test_plug_in_new_module():
    """新增模块只需出现在列表中，装配自动按优先级插入。"""
    mods = fixed_modules() + [
        Module(name="测试模块", priority=15, content="## 测试\n自定义内容"),
    ]
    result = assemble_system(mods)
    # priority 15 应在 priority 10（身份）之后、20（系统约束）之前
    pos_test = result.find("测试")
    pos_identity = result.find("ForgeCode")
    pos_constraint = result.find("操作边界")
    assert pos_identity < pos_test < pos_constraint, (
        f"新增模块应排在身份({pos_identity})之后、系统约束({pos_constraint})之前，"
        f"实际测试模块在 {pos_test}"
    )


# ── T4.7: 补充消息机制 ─────────────────────────────


def test_system_reminder_wrapped():
    """system_reminder 输出含 <system-reminder> 标签。"""
    msg = system_reminder("测试内容")
    assert "<system-reminder>" in msg
    assert "</system-reminder>" in msg
    assert "测试内容" in msg


def test_plan_reminder_full_vs_concise():
    """完整版和精简版提醒不同。"""
    full = plan_reminder(True)
    concise = plan_reminder(False)
    assert len(full) > len(concise)
    assert "<system-reminder>" in full
    assert "<system-reminder>" in concise
    # 完整版含"计划模式"
    assert "计划模式" in full
    assert "调研" in full or "只读" in full


def test_plan_reminder_concise_shorter():
    """精简版应明显短于完整版。"""
    full = plan_reminder(True)
    concise = plan_reminder(False)
    assert len(concise) < len(full) * 0.8, f"精简版({len(concise)})应明显短于完整版({len(full)})"
