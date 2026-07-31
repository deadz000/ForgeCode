"""自动笔记系统：笔记 CRUD、索引管理、异步 LLM 更新。"""

from forgecode.memory.manager import Manager
from forgecode.memory.types import Note, NoteType, UpdateAction

__all__ = ["Manager", "Note", "NoteType", "UpdateAction"]
