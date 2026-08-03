"""tui.tasks 单测：build_task_notification 渲染。"""

from __future__ import annotations

from forgecode.task.manager import BackgroundTask, Status
from forgecode.tui.tasks import build_task_notification


def _bt(status: Status, name: str = "w", result: str = "", err: Exception | None = None) -> BackgroundTask:
    return BackgroundTask(
        id="task_0001",
        name=name,
        sub_agent=None,
        conv=None,
        task="t",
        status=status,
        result=result,
        err=err,
    )


def test_notification_completed() -> None:
    notif = build_task_notification(_bt(Status.COMPLETED, name="worker", result="行数: 42"))
    assert "<task-notification>" in notif
    assert 'name="worker"' in notif
    assert "completed" in notif
    assert "Result: 行数: 42" in notif


def test_notification_failed() -> None:
    notif = build_task_notification(_bt(Status.FAILED, err=RuntimeError("boom")))
    assert "failed" in notif
    assert "Error: boom" in notif


def test_notification_empty_name() -> None:
    notif = build_task_notification(_bt(Status.COMPLETED, name="", result="x"))
    assert 'name=""' in notif
