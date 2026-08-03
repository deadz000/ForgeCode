"""ActiveSkills 单测。"""

from __future__ import annotations

from forgecode.skills.active import ActiveSkills


def test_activate_clear_snapshot():
    active = ActiveSkills()
    active.activate("commit", "body-a")
    active.activate("review", "body-b")
    assert active.names() == ["commit", "review"]
    active.activate("commit", "body-a2")
    assert active.names() == ["commit", "review"]
    assert active.snapshot()[0].body == "body-a2"
    active.clear()
    assert active.names() == []
