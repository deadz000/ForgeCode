"""对话管理模块测试。"""

from forgecode.conversation.history import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    Conversation,
    Message,
    ToolCall,
    ToolResult,
)


def test_message_creation():
    msg = Message(role="user", content="hello")
    assert msg.role == ROLE_USER
    assert msg.content == "hello"
    assert msg.tool_calls == []
    assert msg.tool_results == []


def test_conversation_add_user():
    conv = Conversation()
    conv.add_user("hello")
    assert len(conv.messages) == 1
    assert conv.messages[0].role == ROLE_USER


def test_conversation_add_assistant():
    conv = Conversation()
    conv.add_assistant("hi")
    assert len(conv.messages) == 1
    assert conv.messages[0].role == ROLE_ASSISTANT


def test_conversation_clear():
    conv = Conversation()
    conv.add_user("hello")
    conv.clear()
    assert len(conv.messages) == 0


def test_conversation_messages_is_copy():
    conv = Conversation()
    conv.add_user("hello")
    msgs = conv.messages
    msgs.append(Message(role="assistant", content="x"))
    assert len(conv.messages) == 1


def test_conversation_order():
    conv = Conversation()
    conv.add_user("first")
    conv.add_assistant("second")
    assert conv.messages[0].content == "first"
    assert conv.messages[1].content == "second"


def test_add_assistant_with_tool_calls():
    conv = Conversation()
    calls = [ToolCall(id="c1", name="read_file", input='{"path":"x"}')]
    conv.add_user("read x")
    conv.add_assistant_with_tool_calls("let me read", calls)
    msg = conv.messages[1]
    assert msg.role == ROLE_ASSISTANT
    assert msg.content == "let me read"
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].name == "read_file"


def test_add_tool_results():
    conv = Conversation()
    results = [
        ToolResult(tool_call_id="c1", content="file content", is_error=False)
    ]
    conv.add_user("test")
    conv.add_assistant_with_tool_calls(
        "", [ToolCall(id="c1", name="r", input="{}")]
    )
    conv.add_tool_results(results)
    conv.add_assistant("done")

    msgs = conv.messages
    assert len(msgs) == 4
    assert msgs[0].role == ROLE_USER
    assert msgs[1].role == ROLE_ASSISTANT
    assert msgs[2].role == ROLE_TOOL
    assert msgs[2].tool_results[0].content == "file content"
    assert msgs[3].role == ROLE_ASSISTANT
