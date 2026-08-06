"""ForgeCode 命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from forgecode.agent.agent_tool import AgentTool
from forgecode.agent.runtime import SessionRuntime
from forgecode.command import Registry as CmdRegistry
from forgecode.command import register_builtins
from forgecode.command.skills import register_skills_as_commands, remove_skill_commands
from forgecode.command.ui import SkillSummary
from forgecode.compact.state import CompactCircuitBreaker, ContentReplacementState, RecoveryState
from forgecode.compact.state import new_session_context as _new_session_context
from forgecode.config.loader import load_config
from forgecode.config.schema import effective_context_window
from forgecode.conversation.history import Conversation
from forgecode.hook import load as load_hook
from forgecode.hook.event import Event as HookEvent
from forgecode.instructions import Loader
from forgecode.mcp import load_config as load_mcp_config
from forgecode.mcp import new_manager as new_mcp_manager
from forgecode.memory import Manager as MemoryManager
from forgecode.permission.engine import new_engine
from forgecode.providers import create_provider
from forgecode.session import Writer, clean_expired
from forgecode.skills import ActiveSkills, Catalog, Executor
from forgecode.subagent import load_catalog as load_subagent_catalog
from forgecode.task import (
    Manager as TaskManager,
)
from forgecode.task import (
    SendMessageTool as TaskSendMessageTool,
)
from forgecode.task import (
    TaskGetTool as TaskGetBackgroundTool,
)
from forgecode.task import (
    TaskListTool as TaskListBackgroundTool,
)
from forgecode.task import (
    TaskStopTool,
)
from forgecode.team import Manager as TeamManager
from forgecode.team.registry import AgentNameRegistry
from forgecode.team.tools import (
    SendMessageTool as TeamSendMessageTool,
)
from forgecode.team.tools import (
    TaskCreateTool,
    TaskUpdateTool,
    TeamCreateTool,
    TeamDeleteTool,
)
from forgecode.team.tools import (
    TaskGetTool as TeamTaskGetTool,
)
from forgecode.team.tools import (
    TaskListTool as TeamTaskListTool,
)
from forgecode.tool import new_default_registry
from forgecode.tool.install_skill import InstallSkillTool
from forgecode.tool.load_skill import LoadSkillTool
from forgecode.tui.app import VERSION, ForgeApp
from forgecode.worktree import Manager as WorktreeManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="forgecode",
        description="命令行 AI 编程助手",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="指定使用的供应商名称（不指定则使用第一个）",
    )
    # ── Team 队员子进程模式（Pane 后端 spawn 用）──
    parser.add_argument("--team-member", action="store_true", help="以 Team 队员模式运行（Pane 后端子进程）")
    parser.add_argument("--team", type=str, default="", help="队员所属 Team（--team-member）")
    parser.add_argument("--member", type=str, default="", help="队员名（--team-member）")
    parser.add_argument("--agent-id", type=str, default="", help="队员 agent_id（--team-member）")
    parser.add_argument("--session-dir", type=str, default="", help="队员 session 目录（--team-member）")
    parser.add_argument("--worktree", type=str, default="", help="队员 worktree 路径（--team-member）")
    parser.add_argument("--agent-type", type=str, default="", help="队员角色定义名（--team-member）")
    parser.add_argument("--model", type=str, default="", help="模型覆盖（--team-member）")
    parser.add_argument("--plan-mode", action="store_true", help="以 plan 模式起步（--team-member）")
    return parser.parse_args()


def cli() -> None:
    """同步入口（供 pyproject.toml scripts 调用）。"""
    args = parse_args()

    try:
        app_config = load_config(args.provider)
    except ValueError as e:
        print(f"配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 获取活动供应商配置
    active_config = None
    for p in app_config.providers:
        if p.name == app_config.active_provider_name:
            active_config = p
            break

    if active_config is None:
        print("错误: 无可用供应商", file=sys.stderr)
        sys.exit(1)

    try:
        provider = create_provider(active_config)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    conversation = Conversation()
    registry = new_default_registry()

    # ── 构造 SessionRuntime ──
    workspace = str(Path.cwd())
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=_new_session_context(workspace),
        context_window=effective_context_window(active_config),
    )

    # 启动异步主流程（含 MCP 连接 + TUI）
    try:
        asyncio.run(_amain(app_config, provider, conversation, registry, runtime, args))
    except KeyboardInterrupt:
        pass


async def _amain(app_config, provider, conversation, registry, runtime, args) -> None:
    """异步主流程：MCP 连接 → 注册工具 → 启动 TUI → 关闭 MCP。"""
    root = os.getcwd()
    user_home = os.path.expanduser("~")

    # ── 1. 加载项目指令 ──
    loader = Loader(project_root=root, user_home=user_home)
    instruction_text = loader.load()

    # ── 2. 初始化记忆管理器 ──
    project_mem_dir = os.path.join(root, ".forgecode", "memory")
    user_mem_dir = os.path.join(user_home, ".forgecode", "memory")
    mem_mgr = MemoryManager(
        project_dir=project_mem_dir,
        user_dir=user_mem_dir,
        provider=provider,
        model=provider.config.model,
    )
    memory_text = mem_mgr.load_index()

    # ── 3. 创建 Session Writer ──
    sessions_dir = os.path.join(root, ".forgecode", "sessions")
    writer = Writer(runtime.session.session_dir)

    # ── 设置 Conversation 回调 ──
    model_name = provider.config.model
    _first_call = True

    def _on_append(msg) -> None:
        nonlocal _first_call
        writer.append(msg, model=model_name, is_first=_first_call)
        _first_call = False

    def _on_replace(msgs) -> None:
        writer.write_compact_marker()
        writer.append_all(msgs)

    conversation._on_append = _on_append
    conversation._on_replace = _on_replace

    # ── 4. 后台会话清理 ──
    asyncio.create_task(asyncio.to_thread(clean_expired, sessions_dir, timedelta(days=30)))

    # ── MCP 后台连接（不阻塞 TUI）──
    mcp_cfg = load_mcp_config(root)
    mcp_mgr = await new_mcp_manager(mcp_cfg, version=VERSION, registry=registry)

    try:
        engine, err = new_engine(".")
        if err is not None:
            print(f"权限引擎降级: {err}", file=sys.stderr)

        # ── Hook 引擎加载（错误一律 stderr，不阻断启动）──
        hook_engine = load_hook(root)

        # ── SubAgent：角色 Catalog + 后台任务 Manager + 5 个新工具 ──
        subagent_catalog = load_subagent_catalog(root)
        task_mgr = TaskManager()

        # ── Worktree 隔离管理器（失败降级为 None，不阻断启动）──
        try:
            worktree_mgr = WorktreeManager(root)
        except Exception as exc:
            print(f"Worktree 管理器降级: {exc}", file=sys.stderr)
            worktree_mgr = None
        if worktree_mgr is not None:
            # 后台跑一次过期临时 Worktree 清理，不阻塞启动
            asyncio.create_task(worktree_mgr.sweep_stale(datetime.now() - timedelta(hours=24)))

        # ── Team 管理器 + 名称注册表（失败降级 None，不阻断启动）──
        name_reg = AgentNameRegistry()
        task_mgr.set_name_registry(name_reg)
        try:
            team_mgr = TeamManager(user_home, root, worktree_mgr, task_mgr, name_reg)
        except Exception as exc:
            print(f"Team 管理器降级: {exc}", file=sys.stderr)
            team_mgr = None
        if team_mgr is not None:
            team_mgr.bind_spawn_deps(
                provider=provider,
                engine=engine,
                registry=registry,
                catalog=subagent_catalog,
                version=VERSION,
                hook_engine=hook_engine,
                fork_enabled=getattr(app_config.features, "fork_teammate", False),
            )

        # ── 注册工具 ──
        registry.register(TaskListBackgroundTool(task_mgr))
        registry.register(TaskGetBackgroundTool(task_mgr))
        registry.register(TaskStopTool(task_mgr))
        registry.register(TaskSendMessageTool(task_mgr))
        registry.register(
            AgentTool(
                subagent_catalog,
                task_mgr,
                parent=None,
                bg_enabled=app_config.effective_enable_subagent_background(),
                worktree_mgr=worktree_mgr,
                team_hook=team_mgr,  # type: ignore[arg-type]
            )
        )

        if team_mgr is not None:
            # Team 管理工具（主 Agent 可见）
            registry.register(TeamCreateTool(team_mgr))
            registry.register(TeamDeleteTool(team_mgr))
            registry.register(TaskCreateTool(team_mgr))
            registry.register(TaskUpdateTool(team_mgr))
            # 协作工具覆盖 ch13 同名（保留 fallback 分流）
            registry.register_skill_tool(TeamTaskListTool(team_mgr, fallback=registry.get("TaskList")))
            registry.register_skill_tool(TeamTaskGetTool(team_mgr, fallback=registry.get("TaskGet")))
            registry.register_skill_tool(TeamSendMessageTool(team_mgr, fallback=registry.get("SendMessage")))

            # 队员结束 → is_active=False + Lead idle 通知
            async def _on_team_task_done(task_id: str) -> None:
                if team_mgr is not None:
                    await team_mgr.handle_task_done(task_id)

            task_mgr.on_task_done(_on_team_task_done)

        if runtime.active_skills is None:
            runtime.active_skills = ActiveSkills()

        catalog = Catalog.load(Path(root))
        registry.register(LoadSkillTool(catalog, runtime.active_skills, registry))
        install_tool = InstallSkillTool(catalog, Path(root))
        registry.register(install_tool)

        issues = catalog.validate_tools(registry)
        for issue in issues:
            print(
                "[skills] error: skill "
                f"{issue.skill_name}: allowed_tool "
                f'"{issue.tool_name}" not registered, skipped',
                file=sys.stderr,
            )
            catalog.remove(issue.skill_name)

        cmd_reg = CmdRegistry()
        register_builtins(cmd_reg)
        for skill in catalog.list():
            if cmd_reg.lookup(skill.meta.name) is not None:
                print(
                    f"[skills] warn: skip /{skill.meta.name}: conflict with builtin command",
                    file=sys.stderr,
                )
                catalog.remove(skill.meta.name)

        executor = Executor(
            catalog=catalog,
            active=runtime.active_skills,
            registry=registry,
            provider=provider,
            engine=engine,
            version=VERSION,
            runtime=runtime,
        )

        summaries = [
            SkillSummary(
                name=s.meta.name,
                description=s.meta.description,
                source=str(s.source),
                mode=s.meta.mode,
            )
            for s in catalog.list()
        ]

        def _reload_skill_commands() -> None:
            remove_skill_commands(cmd_reg)
            register_skills_as_commands(cmd_reg, summaries, executor)

        install_tool._on_reloaded = _reload_skill_commands
        register_skills_as_commands(cmd_reg, summaries, executor)

        # ── --team-member：子进程自治循环，不构造 TUI ──
        if args.team_member:
            from forgecode.team_member import run_team_member

            await run_team_member(
                {
                    "args": args,
                    "provider": provider,
                    "registry": registry,
                    "engine": engine,
                    "hook_engine": hook_engine,
                    "subagent_catalog": subagent_catalog,
                    "team_mgr": team_mgr,
                    "task_mgr": task_mgr,
                    "version": VERSION,
                    "writer": writer,
                    "runtime": runtime,
                }
            )
            return

        # ── Coordinator Mode 检测（双锁）──
        coordinator_mode = False
        from forgecode.coordinator import is_enabled as _coord_enabled

        if _coord_enabled(app_config):
            coordinator_mode = True

        app = ForgeApp(
            config=app_config,
            provider=provider,
            conversation=conversation,
            registry=registry,
            engine=engine,
            runtime=runtime,
            writer=writer,
            mem_mgr=mem_mgr,
            instruction_text=instruction_text,
            memory_text=memory_text,
            sessions_dir=sessions_dir,
            cmd_registry=cmd_reg,
            catalog=catalog,
            executor=executor,
            hook_engine=hook_engine,
            task_mgr=task_mgr,
            subagent_catalog=subagent_catalog,
            worktree_mgr=worktree_mgr,
            team_mgr=team_mgr,
            coordinator_mode=coordinator_mode,
        )
        app_finished = False
        try:
            await app.run_async()
            app_finished = True
        finally:
            if hook_engine is not None and not app_finished:
                # 兜底 SessionEnd（Ctrl+C / 异常路径未走到 run_async 末尾）
                payload = {
                    "event": "SessionEnd",
                    "session_id": runtime.session.session_id if runtime and runtime.session else "",
                    "cwd": os.getcwd(),
                    "mode": app.mode.name.lower() if app.mode else "default",
                }
                await hook_engine.dispatch(HookEvent.SESSION_END, payload)
    finally:
        await mcp_mgr.close()
        writer.close()


if __name__ == "__main__":
    cli()
