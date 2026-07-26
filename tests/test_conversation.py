"""对话管理模块测试。"""

from forgecode.conversation.history import Conversation, Message


def test_message_creation():
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"


def test_conversation_add():
    conv = Conversation()
    conv.add("user", "hello")
    conv.add("assistant", "hi")
    assert len(conv.messages) == 2


def test_conversation_clear():
    conv = Conversation()
    conv.add("user", "hello")
    conv.clear()
    assert len(conv.messages) == 0


def test_conversation_messages_is_copy():
    conv = Conversation()
    conv.add("user", "hello")
    msgs = conv.messages
    msgs.append(Message(role="assistant", content="x"))
    assert len(conv.messages) == 1  # 原始列表不变


def test_conversation_order():
    conv = Conversation()
    conv.add("user", "first")
    conv.add("user", "second")
    assert conv.messages[0].content == "first"
    assert conv.messages[1].content == "second"
