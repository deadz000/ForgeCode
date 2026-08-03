"""Skill 执行器：inline 注入主对话，fork 起子 Agent。"""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import replace

from forgecode.skills.parser import _parse_frontmatter_and_body
from forgecode.skills.render import render_body
from forgecode.skills.types import Skill


class Executor:
    """Skill 执行入口。"""

    def __init__(
        self,
        catalog,
        active,
        registry,
        provider,
        engine,
        version: str,
        runtime=None,
    ) -> None:
        self._catalog = catalog
        self._active = active
        self._registry = registry
        self._provider = provider
        self._engine = engine
        self._version = version
        self._runtime = runtime

    async def execute(self, ctx, ui, name: str, args: str = "") -> None:
        skill = self._catalog.get(name)
        if skill is None:
            ui.error(f"skill not found: {name}")
            return

        fresh = _reload_skill(skill)
        rendered = render_body(fresh, args)

        if not fresh.meta.is_fork():
            ui.inject_and_send(f"/{name}", rendered)
            return

        # Fork: 启动后台任务，不阻塞 dispatch
        ui.println(f"[dim]⚒ /{name} 正在 fork 模式中执行...[/dim]")
        asyncio.create_task(self._run_fork_and_finish(ui, fresh, rendered))

    async def _run_fork_and_finish(self, ui, skill: Skill, rendered: str) -> None:
        """fork 后台任务：执行子 Agent 后把结果写回主对话。"""
        try:
            final_text = await self._run_fork(ui, skill, rendered)
            await ui.append_assistant_message(final_text)
        except Exception as e:
            await ui.append_assistant_message(f"[skill {skill.meta.name} failed: {e}]")

    async def _run_fork(self, ui, skill: Skill, rendered: str) -> str:
        conv = _make_fork_conversation(ui, rendered, skill.meta.fork_context)
        provider = _fork_provider(self._provider, skill)

        # 复用 SubAgent 底座（AC17）：装饰参数后调公共 launch_fork
        from forgecode.agent.launch import launch_fork

        try:
            final_text = await launch_fork(
                provider=provider,
                registry=self._registry,
                engine=self._engine,
                version=self._version,
                conv=conv,
                task="",  # conv 已由 _make_fork_conversation 装填任务
                allowed_tools=skill.meta.allowed_tools or None,
                hook_engine=None,
            )
            if not final_text:
                final_text = f"[skill {skill.meta.name} finished with no output]"
        except asyncio.CancelledError:
            final_text = f"[skill {skill.meta.name} failed: cancelled]"
        except Exception as e:
            final_text = f"[skill {skill.meta.name} failed: {e}]"
        return final_text


def _reload_skill(skill: Skill) -> Skill:
    try:
        raw = (skill.source_dir / "SKILL.md").read_text(encoding="utf-8")
        _, body = _parse_frontmatter_and_body(raw)
        return replace(skill, prompt_body=body)
    except Exception as e:
        warnings.warn(f"skill {skill.meta.name}: reload SKILL.md failed, use cache: {e}", stacklevel=3)
        return skill


def _make_fork_conversation(ui, rendered: str, fork_context: str):
    from forgecode.conversation.history import Conversation

    if fork_context in ("recent", "full"):
        if fork_context == "full":
            warnings.warn("fork_context=full 本期按 recent 处理", stacklevel=3)
        msgs = ui.recent_messages(5)
        conv = Conversation.from_messages(list(msgs))
    else:
        conv = Conversation()
    conv.add_user(rendered)
    return conv


def _fork_provider(provider, skill: Skill):
    if not skill.meta.model:
        return provider
    if provider.config.protocol not in ("anthropic", "openai"):
        return provider
    try:
        from forgecode.providers import create_provider

        new_config = replace(provider.config, model=skill.meta.model)
        return create_provider(new_config)
    except Exception as e:
        warnings.warn(f"skill {skill.meta.name}: model override failed, use main provider: {e}", stacklevel=3)
        return provider
