"""记忆系统数据类型：笔记类型、笔记、更新操作。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class NoteType(StrEnum):
    """笔记分类。"""

    USER_PREFERENCE = "user_preference"
    CORRECTION_FEEDBACK = "correction_feedback"
    PROJECT_KNOWLEDGE = "project_knowledge"
    REFERENCE_MATERIAL = "reference_material"


@dataclass
class Note:
    """一条笔记的内存表示。"""

    type: NoteType
    title: str
    slug: str
    content: str
    filename: str
    created: datetime
    updated: datetime


@dataclass
class UpdateAction:
    """LLM 返回的单条记忆更新操作。"""

    action: str  # "create" / "update" / "delete"
    level: str  # "project" / "user"
    type: str = ""  # NoteType（create 时必需）
    title: str = ""
    slug: str = ""
    content: str = ""
    filename: str = ""  # update / delete 时必需
